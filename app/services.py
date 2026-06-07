import json
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageStat
from sqlalchemy import and_, func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    AlbumCleanupTask,
    AlbumCostItem,
    AlbumDecisionJob,
    AlbumDecisionJobPhoto,
    AlbumGenerationResult,
    AlbumGenerationTask,
    AlbumGenerationTaskPhoto,
    AlbumPushTask,
    PhotoFile,
    PhotoPreprocessResult,
    PluginEvent,
    SchedulerRunLog,
)
from app.schemas import PhotoRejectApply


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:24]}"


def _log(db: Session, name: str, started: datetime, scanned: int, processed: int, failed: int, error: str | None = None) -> None:
    db.add(
        SchedulerRunLog(
            scheduler_name=name,
            run_id=_id("run"),
            status="failed" if error else ("partial_success" if failed else "success"),
            scanned_count=scanned,
            processed_count=processed,
            failed_count=failed,
            started_at=started,
            finished_at=datetime.utcnow(),
            error_message=error,
        )
    )
    db.commit()


def scan_events(db: Session, limit: int = 100) -> dict:
    started = datetime.utcnow()
    now = datetime.utcnow()
    events = list(
        db.scalars(
            select(PluginEvent)
            .where(
                PluginEvent.event_type == "photo_uploaded",
                PluginEvent.status.in_(["pending", "retrying"]),
                PluginEvent.next_run_at <= now,
            )
            .order_by(PluginEvent.created_at)
            .limit(limit)
        )
    )
    processed = 0
    failed = 0
    for event in events:
        try:
            photo_ids = event.payload_json.get("photo_ids", [])
            photos = list(db.scalars(select(PhotoFile).where(PhotoFile.photo_id.in_(photo_ids))))
            if len(photos) != len(photo_ids):
                raise ValueError("photo_files_missing")
            for photo in photos:
                if photo.preprocess_status not in {"success", "system_rejected"}:
                    photo.preprocess_status = "pending"
            event.status = "success"
            event.processed_at = datetime.utcnow()
            processed += 1
        except Exception as exc:
            event.retry_count += 1
            event.status = "failed" if event.retry_count >= event.max_retry else "retrying"
            event.error_message = str(exc)
            event.next_run_at = datetime.utcnow() + timedelta(seconds=30)
            failed += 1
    db.commit()
    _log(db, "event_scan", started, len(events), processed, failed)
    return {"scanned": len(events), "processed": processed, "failed": failed}


def _average_hash(image: Image.Image) -> str:
    gray = ImageOps.grayscale(image).resize((8, 8))
    pixels = list(gray.getdata())
    avg = sum(pixels) / len(pixels)
    bits = "".join("1" if pixel >= avg else "0" for pixel in pixels)
    return f"{int(bits, 2):016x}"


def _colors(image: Image.Image) -> list[str]:
    thumb = image.convert("RGB").resize((64, 64))
    colors = thumb.getcolors(maxcolors=4096) or []
    top = sorted(colors, reverse=True)[:5]
    return [f"#{r:02x}{g:02x}{b:02x}" for _, (r, g, b) in top]


def _preprocess_one(db: Session, photo: PhotoFile) -> None:
    existing = db.scalar(select(PhotoPreprocessResult).where(PhotoPreprocessResult.photo_id == photo.photo_id))
    if existing:
        photo.preprocess_status = "success" if existing.system_reject_level == "none" else "system_rejected"
        return
    with Image.open(photo.original_path) as img:
        rgb = img.convert("RGB")
        gray = ImageOps.grayscale(rgb)
        brightness = ImageStat.Stat(gray).mean[0] / 255
        edges = gray.filter(ImageFilter.FIND_EDGES)
        sharpness = min(ImageStat.Stat(edges).stddev[0] / 64, 1)
        stat = ImageStat.Stat(rgb)
        colorfulness = min((sum(stat.stddev) / 3) / 90, 1)
        quality = max(0, min((brightness * 0.25) + (sharpness * 0.45) + (colorfulness * 0.30), 1))
        is_blurry = sharpness < 0.08
        aspect = photo.width / max(photo.height, 1)
        is_screenshot = int(aspect > 1.9 or aspect < 0.45)
        system_reject_level = "hard" if is_blurry else ("soft" if is_screenshot else "none")
        reason = "图片严重模糊" if is_blurry else ("疑似截图比例" if is_screenshot else None)
        result = PhotoPreprocessResult(
            photo_id=photo.photo_id,
            user_id=photo.user_id,
            quality_score=round(quality, 4),
            sharpness_score=round(sharpness, 4),
            brightness_score=round(brightness, 4),
            colorfulness_score=round(colorfulness, 4),
            is_blurry=int(is_blurry),
            is_duplicate=0,
            is_screenshot=is_screenshot,
            is_document=0,
            is_qrcode=0,
            has_person=0,
            face_count=0,
            main_face_score=0,
            object_detection_json={"provider": "mock-local-cv", "objects": []},
            scene_tags_json=["daily", "life"],
            scene_candidates_json=[{"scene": "daily", "score": 0.7}],
            mood_hint="happy" if brightness > 0.45 else "neutral",
            dominant_colors_json=_colors(rgb),
            phash=_average_hash(rgb),
            local_cv_cost_tokens=100,
            system_reject_level=system_reject_level,
            system_reject_reason=reason,
            processed_at=datetime.utcnow(),
        )
        db.add(result)
        photo.preprocess_status = "success" if system_reject_level == "none" else "system_rejected"


def preprocess_photos(db: Session, limit: int = 50) -> dict:
    started = datetime.utcnow()
    now = datetime.utcnow()
    photos = list(
        db.scalars(
            select(PhotoFile)
            .where(
                PhotoFile.preprocess_status == "pending",
                PhotoFile.cleanup_status != "cleaned",
                PhotoFile.expire_at > now,
            )
            .order_by(PhotoFile.uploaded_at)
            .limit(limit)
        )
    )
    processed = 0
    failed = 0
    for photo in photos:
        try:
            photo.preprocess_status = "processing"
            _preprocess_one(db, photo)
            processed += 1
        except Exception as exc:
            photo.preprocess_status = "failed"
            failed += 1
            db.rollback()
            photo = db.scalar(select(PhotoFile).where(PhotoFile.photo_id == photo.photo_id))
            if photo:
                photo.preprocess_status = "failed"
                db.commit()
    db.commit()
    _log(db, "photo_preprocess", started, len(photos), processed, failed)
    return {"scanned": len(photos), "processed": processed, "failed": failed}


def _eligible_photos(db: Session, user_id: str, now: datetime) -> list[PhotoFile]:
    settings = get_settings()
    window_start = now - timedelta(minutes=settings.trigger_window_minutes)
    return list(
        db.scalars(
            select(PhotoFile)
            .join(PhotoPreprocessResult, PhotoPreprocessResult.photo_id == PhotoFile.photo_id)
            .where(
                PhotoFile.user_id == user_id,
                PhotoFile.uploaded_at >= window_start,
                PhotoFile.preprocess_status == "success",
                PhotoFile.smart_reject_status != "rejected_final",
                PhotoFile.used_in_generation == 0,
                PhotoPreprocessResult.system_reject_level == "none",
            )
            .order_by(PhotoFile.uploaded_at)
        )
    )


def _summary_for_photos(db: Session, photos: list[PhotoFile]) -> dict:
    results = list(
        db.scalars(
            select(PhotoPreprocessResult).where(
                PhotoPreprocessResult.photo_id.in_([photo.photo_id for photo in photos])
            )
        )
    )
    avg_quality = float(sum(float(result.quality_score) for result in results) / len(results)) if results else 0.0
    return {
        "photo_count": len(photos),
        "usable_photo_count": len(photos),
        "photo_ids": [photo.photo_id for photo in photos],
        "scene_summary": sorted({tag for result in results for tag in (result.scene_tags_json or [])}),
        "quality_summary": {"avg_quality_score": round(avg_quality, 4)},
        "people_summary": {
            "has_people_count": sum(1 for result in results if result.has_person),
            "face_count_avg": round(sum(result.face_count for result in results) / len(results), 2) if results else 0,
        },
    }


def _local_decision(summary: dict) -> dict:
    return {
        "content": {
            "decision": "should_generate",
            "reason": "Mock 判断：可用照片数量达标，适合生成朋友圈相册。",
            "confidence": 0.86,
            "selected_photo_ids": summary["photo_ids"][:9],
            "keep_photo_ids": summary["photo_ids"][9:],
            "reject_photo_ids": [],
            "reject_reasons": {},
            "template_matches": [{"template_id": "mvp_grid_001", "score": 0.9}],
        },
        "cost": {"charged_tokens": 1200},
        "usage": {"total_tokens": 1500},
        "model": "mock-local-decision",
    }


def _llm_decision(summary: dict, user_id: str, decision_job_id: str) -> dict:
    settings = get_settings()
    if settings.mock_llm or not settings.llm_proxy_base_url:
        return _local_decision(summary)
    try:
        with httpx.Client(timeout=20) as client:
            response = client.post(
                f"{settings.llm_proxy_base_url}/v1/chat/completions",
                json={
                    "model_type": "text_llm",
                    "purpose": "moments_album_decision",
                    "user_id": user_id,
                    "business_scenario": "moments_album",
                    "session_id": decision_job_id,
                    "request_id": f"decision_{decision_job_id}",
                    "messages": [
                        {"role": "system", "content": "你是朋友圈相册智能决策助手。请严格输出 JSON。"},
                        {"role": "user", "content": json.dumps(summary, ensure_ascii=False)},
                    ],
                    "response_format": "json",
                },
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("error"):
                raise RuntimeError(payload["error"]["code"])
            return payload
    except Exception:
        return {
            "content": {
                "decision": "wait_more_photos",
                "reason": "LLMProxy 调用失败，暂不生成。",
                "confidence": 0,
                "selected_photo_ids": [],
                "keep_photo_ids": summary["photo_ids"],
                "reject_photo_ids": [],
                "reject_reasons": {},
                "template_matches": [],
            },
            "cost": {"charged_tokens": 0},
            "usage": {"total_tokens": 0},
            "model": "llm-proxy-fallback",
        }


def make_decisions(db: Session) -> dict:
    started = datetime.utcnow()
    settings = get_settings()
    now = datetime.utcnow()
    user_ids = list(db.scalars(select(PhotoFile.user_id).where(PhotoFile.preprocess_status == "success").distinct()))
    processed = 0
    for user_id in user_ids:
        active = db.scalar(
            select(func.count()).select_from(AlbumGenerationTask).where(
                AlbumGenerationTask.user_id == user_id,
                AlbumGenerationTask.status.in_(["pending", "processing", "retrying"]),
            )
        )
        if active:
            continue
        photos = _eligible_photos(db, user_id, now)
        if len(photos) < settings.trigger_photo_threshold:
            continue
        existing = db.scalar(
            select(AlbumDecisionJob)
            .where(AlbumDecisionJob.user_id == user_id, AlbumDecisionJob.decision_window_end >= now - timedelta(seconds=30))
            .order_by(AlbumDecisionJob.created_at.desc())
        )
        if existing:
            continue
        summary = _summary_for_photos(db, photos)
        decision_job_id = _id("decision")
        llm_payload = _llm_decision(summary, user_id, decision_job_id)
        decision_content = llm_payload["content"]
        selected_ids = decision_content.get("selected_photo_ids") or [photo.photo_id for photo in photos[: min(9, len(photos))]]
        templates = decision_content.get("template_matches") or [{"template_id": "mvp_grid_001", "score": 0.9}]
        decision_result = decision_content.get("decision", "wait_more_photos")
        decision_tokens = int((llm_payload.get("cost") or {}).get("charged_tokens") or 0)
        job = AlbumDecisionJob(
            decision_job_id=decision_job_id,
            user_id=user_id,
            decision_window_start=now - timedelta(minutes=settings.trigger_window_minutes),
            decision_window_end=now,
            photo_count=len(photos),
            usable_photo_count=len(photos),
            summary_json=summary,
            decision_result=decision_result,
            decision_reason=decision_content.get("reason"),
            confidence=float(decision_content.get("confidence") or 0),
            template_matches_json=templates,
            suggested_album_count=settings.default_album_count,
            created_generation_count=settings.default_album_count if decision_result == "should_generate" else 0,
            processed_at=now,
        )
        db.add(job)
        reject_reasons = decision_content.get("reject_reasons") or {}
        reject_ids = set(decision_content.get("reject_photo_ids") or [])
        for idx, photo in enumerate(photos):
            role = "reject" if photo.photo_id in reject_ids else ("selected" if photo.photo_id in selected_ids else "keep")
            db.add(
                AlbumDecisionJobPhoto(
                    decision_job_id=decision_job_id,
                    photo_id=photo.photo_id,
                    user_id=user_id,
                    photo_role=role,
                    reject_reason=reject_reasons.get(photo.photo_id),
                    is_main_candidate=1 if idx == 0 else 0,
                    score=0.9 if idx == 0 else 0.75,
                )
            )
            if role == "reject":
                photo.smart_reject_count += 1
                photo.smart_reject_status = "rejected_final" if photo.smart_reject_count >= 2 else "rejected_once"
        if decision_result != "should_generate":
            processed += 1
            continue
        for album_index in range(1, settings.default_album_count + 1):
            task_id = _id("gen")
            task = AlbumGenerationTask(
                generation_task_id=task_id,
                user_id=user_id,
                decision_job_id=decision_job_id,
                template_id="mvp_grid_001",
                album_index=album_index,
                photo_ids_json=selected_ids,
                main_photo_id=selected_ids[0],
                generation_params_json={
                    "decision_cost": {
                        "charged_tokens": decision_tokens if album_index == 1 else 0,
                        "provider": llm_payload.get("provider") or ("llm-proxy" if not settings.mock_llm and settings.llm_proxy_base_url else "mock"),
                        "model_name": llm_payload.get("model"),
                        "usage": llm_payload.get("usage") or {},
                    }
                },
                estimated_token_cost=220000,
                max_frozen_tokens=settings.single_task_freeze_limit,
            )
            db.add(task)
            for slot, photo_id in enumerate(selected_ids):
                db.add(
                    AlbumGenerationTaskPhoto(
                        generation_task_id=task_id,
                        photo_id=photo_id,
                        user_id=user_id,
                        role="main" if slot == 0 else "slot",
                        slot_index=slot,
                    )
                )
        processed += 1
    db.commit()
    _log(db, "llm_decision", started, len(user_ids), processed, 0)
    return {"scanned": len(user_ids), "processed": processed, "failed": 0}


def _mock_freeze(task: AlbumGenerationTask) -> tuple[str, int, bool]:
    return f"mock_hold_{task.generation_task_id}", min(task.estimated_token_cost, task.max_frozen_tokens), True


def _freeze_account(task: AlbumGenerationTask) -> tuple[str, int, bool]:
    settings = get_settings()
    if settings.mock_account or not settings.account_server_base_url:
        return _mock_freeze(task)
    with httpx.Client(timeout=10) as client:
        summary = client.get(f"{settings.account_server_base_url}/internal/users/{task.user_id}/account-summary").json()
        hold = client.post(
            f"{settings.account_server_base_url}/internal/billing/token-holds",
            json={
                "user_id": task.user_id,
                "biz_type": "moments_album_generation",
                "biz_task_id": task.generation_task_id,
                "estimated_tokens": task.estimated_token_cost,
                "max_frozen_tokens": task.max_frozen_tokens,
            },
        )
        hold.raise_for_status()
        payload = hold.json()
        return payload["hold_id"], payload["frozen_tokens"], not summary.get("has_recharged", False)


def _fallback_copywriting() -> dict:
    return {
        "title": "把今天装进相册里",
        "copy_options": [
            {"style": "daily", "text": "今天的照片已经替我把开心记录好了。"},
            {"style": "cultural", "text": "光影有声，日子有回响。"},
            {"style": "funny", "text": "本来只是随手一拍，结果还挺能发。"},
        ],
    }


def _copywriting(task: AlbumGenerationTask, photos: list[PhotoFile]) -> tuple[dict, dict]:
    fallback = _fallback_copywriting()
    settings = get_settings()
    if settings.mock_llm or not settings.llm_proxy_base_url:
        return fallback, {"charged_tokens": 12000, "provider": "mock", "model_name": "mock-local-copy", "usage": {}}
    try:
        with httpx.Client(timeout=20) as client:
            response = client.post(
                f"{settings.llm_proxy_base_url}/v1/chat/completions",
                json={
                    "model_type": "text_llm",
                    "purpose": "moments_album_copywriting",
                    "user_id": task.user_id,
                    "business_scenario": "ai_secretary_moments_copywriting",
                    "session_id": task.generation_task_id,
                    "request_id": f"copy_{task.generation_task_id}",
                    "messages": [
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "generation_task_id": task.generation_task_id,
                                    "photo_ids": [photo.photo_id for photo in photos],
                                    "copy_style": task.copy_style,
                                },
                                ensure_ascii=False,
                            ),
                        }
                    ],
                    "response_format": "json",
                },
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("error"):
                raise RuntimeError(payload["error"]["code"])
            return payload["content"], {
                "charged_tokens": (payload.get("cost") or {}).get("charged_tokens", 12000),
                "provider": payload.get("provider") or "llm-proxy",
                "model_name": payload.get("model"),
                "usage": payload.get("usage") or {},
            }
    except Exception:
        return fallback, {"charged_tokens": 12000, "provider": "fallback", "model_name": "fallback-copy", "usage": {}}


def _render_album(task: AlbumGenerationTask, photos: list[PhotoFile]) -> tuple[str, str, dict, dict, int, int, int]:
    result_dir = Path(get_settings().storage_root) / "results" / task.generation_task_id
    result_dir.mkdir(parents=True, exist_ok=True)
    image_path = result_dir / f"album_{task.album_index:03d}.jpg"
    thumb_path = result_dir / f"album_{task.album_index:03d}_thumb.jpg"
    canvas = Image.new("RGB", (1080, 1080), "#f7f7f2")
    draw = ImageDraw.Draw(canvas)
    selected = photos[:6]
    cell_w, cell_h = 330, 300
    x0, y0 = 45, 120
    for idx, photo in enumerate(selected):
        with Image.open(photo.thumbnail_path if Path(photo.thumbnail_path).exists() else photo.original_path) as img:
            img = ImageOps.fit(img.convert("RGB"), (cell_w, cell_h))
            x = x0 + (idx % 3) * (cell_w + 15)
            y = y0 + (idx // 3) * (cell_h + 15)
            canvas.paste(img, (x, y))
    copy, copy_cost = _copywriting(task, photos)
    draw.text((48, 40), copy["title"], fill="#252525")
    draw.text((48, 780), copy["copy_options"][0]["text"], fill="#252525")
    if task.has_watermark:
        draw.text((770, 1020), "AIXiaoMi Smart Album", fill="#666666")
    canvas.save(image_path, format="JPEG", quality=90)
    thumb = canvas.copy()
    thumb.thumbnail((320, 320))
    thumb.save(thumb_path, format="JPEG", quality=82)
    return str(image_path), str(thumb_path), copy, copy_cost, canvas.width, canvas.height, image_path.stat().st_size


def generate_albums(db: Session, limit: int = 10) -> dict:
    started = datetime.utcnow()
    tasks = list(
        db.scalars(
            select(AlbumGenerationTask)
            .where(AlbumGenerationTask.status == "pending")
            .order_by(AlbumGenerationTask.created_at)
            .limit(limit)
        )
    )
    processed = 0
    failed = 0
    for task in tasks:
        try:
            started_at = datetime.utcnow()
            claimed = db.execute(
                update(AlbumGenerationTask)
                .where(
                    AlbumGenerationTask.generation_task_id == task.generation_task_id,
                    AlbumGenerationTask.status == "pending",
                )
                .values(status="processing", started_at=started_at)
            ).rowcount
            db.commit()
            if not claimed:
                continue
            task = db.scalar(
                select(AlbumGenerationTask).where(AlbumGenerationTask.generation_task_id == task.generation_task_id)
            )
            hold_id, frozen_tokens, has_watermark = _freeze_account(task)
            task.account_hold_id = hold_id
            task.frozen_token_amount = frozen_tokens
            task.has_watermark = int(has_watermark)
            photos = list(db.scalars(select(PhotoFile).where(PhotoFile.photo_id.in_(task.photo_ids_json))))
            image_path, thumb_path, copy, copy_cost, width, height, file_size = _render_album(task, photos)
            decision_cost = (task.generation_params_json or {}).get("decision_cost") or {}
            decision_tokens = int(decision_cost.get("charged_tokens") or 0)
            copy_tokens = int(copy_cost.get("charged_tokens", 12000))
            actual_cost = decision_tokens + copy_tokens + 60000 + get_settings().platform_service_fee_tokens
            task.actual_token_cost = actual_cost
            task.result_dir = str(Path(image_path).parent)
            task.result_album_path = image_path
            task.result_copy_json = copy
            task.status = "success"
            task.finished_at = datetime.utcnow()
            for photo in photos:
                photo.used_in_generation = 1
            result = AlbumGenerationResult(
                result_id=_id("result"),
                generation_task_id=task.generation_task_id,
                user_id=task.user_id,
                album_title=copy["title"],
                copy_text=copy["copy_options"][0]["text"],
                copy_options_json=copy["copy_options"],
                image_path=image_path,
                thumbnail_path=thumb_path,
                width=width,
                height=height,
                file_size=file_size,
                has_watermark=task.has_watermark,
                expire_at=datetime.utcnow() + timedelta(hours=get_settings().result_expire_hours),
            )
            db.add(result)
            for cost_type, name, tokens in [
                ("text_llm_decision", "智能生成判断", decision_tokens),
                ("text_llm_copywriting", "朋友圈文案生成", copy_tokens),
                ("image_rendering", "相册渲染与图片处理", 60000),
                ("platform_service_fee", "平台服务费", get_settings().platform_service_fee_tokens),
            ]:
                is_copy = cost_type == "text_llm_copywriting"
                is_decision = cost_type == "text_llm_decision"
                db.add(
                    AlbumCostItem(
                        generation_task_id=task.generation_task_id,
                        user_id=task.user_id,
                        cost_type=cost_type,
                        cost_name=name,
                        provider=copy_cost.get("provider", "mock") if is_copy else decision_cost.get("provider", "mock") if is_decision else "mock",
                        model_name=copy_cost.get("model_name", "mock-v1") if is_copy else decision_cost.get("model_name", "mock-v1") if is_decision else "mock-v1",
                        usage_json=copy_cost.get("usage", {}) if is_copy else decision_cost.get("usage", {}) if is_decision else {},
                        actual_cost_yuan=0,
                        charged_tokens=tokens,
                        visible_to_user=1,
                    )
                )
            db.flush()
            db.add(
                AlbumPushTask(
                    push_task_id=_id("push"),
                    user_id=task.user_id,
                    generation_task_id=task.generation_task_id,
                    result_id=result.result_id,
                    push_channel="mock",
                    push_payload_json={
                        "type": "album_result",
                        "images": [image_path],
                        "text": result.copy_text,
                        "copy_options": result.copy_options_json,
                        "cost_tokens": actual_cost,
                    },
                )
            )
            processed += 1
        except Exception as exc:
            task.status = "failed"
            task.error_message = str(exc)
            failed += 1
    db.commit()
    _log(db, "album_generation", started, len(tasks), processed, failed)
    return {"scanned": len(tasks), "processed": processed, "failed": failed}


def _send_via_agent(task: AlbumPushTask) -> str:
    settings = get_settings()
    with httpx.Client(timeout=10) as client:
        response = client.post(
            f"{settings.agent_base_url.rstrip('/')}/internal/channels/send-message",
            json={
                "user_id": task.user_id,
                "channel_type": task.push_channel,
                "trace_id": task.push_task_id,
                "message": task.push_payload_json,
            },
        )
        response.raise_for_status()
        payload = response.json()
        return payload["message_id"]


def push_results(db: Session, limit: int = 20) -> dict:
    started = datetime.utcnow()
    tasks = list(
        db.scalars(select(AlbumPushTask).where(AlbumPushTask.status == "pending").order_by(AlbumPushTask.created_at).limit(limit))
    )
    processed = 0
    failed = 0
    for task in tasks:
        claimed = db.execute(
            update(AlbumPushTask)
            .where(AlbumPushTask.push_task_id == task.push_task_id, AlbumPushTask.status == "pending")
            .values(status="processing")
        ).rowcount
        db.commit()
        if not claimed:
            continue
        task = db.scalar(select(AlbumPushTask).where(AlbumPushTask.push_task_id == task.push_task_id))
        generation = db.scalar(select(AlbumGenerationTask).where(AlbumGenerationTask.generation_task_id == task.generation_task_id))
        result = db.scalar(select(AlbumGenerationResult).where(AlbumGenerationResult.result_id == task.result_id))
        try:
            if get_settings().agent_base_url and not get_settings().mock_push:
                message_id = _send_via_agent(task)
            else:
                message_id = _id("msg")
            if generation and not get_settings().mock_account and get_settings().account_server_base_url:
                with httpx.Client(timeout=10) as client:
                    client.post(
                        f"{get_settings().account_server_base_url}/internal/billing/token-holds/{generation.account_hold_id}/settle",
                        json={"actual_consumed_tokens": generation.actual_token_cost, "cost_items": []},
                    ).raise_for_status()
            task.status = "success"
            task.message_id = message_id
            task.pushed_at = datetime.utcnow()
            cleanup_paths = []
            if result:
                cleanup_paths.extend([result.image_path, result.thumbnail_path])
            if generation and generation.result_dir:
                cleanup_paths.append(generation.result_dir)
            db.add(
                AlbumCleanupTask(
                    cleanup_task_id=_id("cleanup"),
                    user_id=task.user_id,
                    generation_task_id=task.generation_task_id,
                    cleanup_scope_json={"paths": cleanup_paths},
                    expire_at=result.expire_at if result else datetime.utcnow() + timedelta(hours=3),
                )
            )
            processed += 1
        except Exception as exc:
            task.status = "failed"
            task.error_message = str(exc)
            failed += 1
    db.commit()
    _log(db, "album_push", started, len(tasks), processed, failed)
    return {"scanned": len(tasks), "processed": processed, "failed": failed}


def _cleanup_path(item: str) -> tuple[int, int]:
    path = Path(item)
    if not path.exists():
        return 0, 0
    try:
        if path.is_dir():
            cleaned = 0
            for child in sorted(path.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink(missing_ok=True)
                    cleaned += 1
                elif child.is_dir():
                    try:
                        child.rmdir()
                    except OSError:
                        pass
            try:
                path.rmdir()
            except OSError:
                pass
            return cleaned, 0
        path.unlink()
        return 1, 0
    except Exception:
        return 0, 1


def _cleanup_expired_photos(db: Session, now: datetime, limit: int) -> dict:
    photos = list(
        db.scalars(
            select(PhotoFile)
            .where(PhotoFile.cleanup_status != "cleaned", PhotoFile.expire_at <= now)
            .order_by(PhotoFile.expire_at)
            .limit(limit)
        )
    )
    processed = 0
    failed = 0
    files_cleaned = 0
    for photo in photos:
        cleaned = 0
        failed_count = 0
        for item in {photo.original_path, photo.compressed_path, photo.thumbnail_path}:
            item_cleaned, item_failed = _cleanup_path(item)
            cleaned += item_cleaned
            failed_count += item_failed
        files_cleaned += cleaned
        if failed_count:
            photo.cleanup_status = "failed"
            failed += 1
        else:
            photo.cleanup_status = "cleaned"
            photo.cleaned_at = datetime.utcnow()
            processed += 1
    return {"scanned": len(photos), "processed": processed, "failed": failed, "files_cleaned": files_cleaned}


def cleanup_files(db: Session, limit: int = 50) -> dict:
    started = datetime.utcnow()
    now = datetime.utcnow()
    tasks = list(
        db.scalars(
            select(AlbumCleanupTask)
            .where(AlbumCleanupTask.status == "pending", AlbumCleanupTask.expire_at <= now)
            .order_by(AlbumCleanupTask.expire_at)
            .limit(limit)
        )
    )
    processed = 0
    failed = 0
    task_files_cleaned = 0
    for task in tasks:
        cleaned = 0
        failed_count = 0
        for item in task.cleanup_scope_json.get("paths", []):
            item_cleaned, item_failed = _cleanup_path(item)
            cleaned += item_cleaned
            failed_count += item_failed
        task.cleaned_file_count = cleaned
        task.failed_file_count = failed_count
        task.status = "success" if failed_count == 0 else "failed"
        task.cleaned_at = datetime.utcnow()
        task_files_cleaned += cleaned
        processed += int(failed_count == 0)
        failed += int(failed_count > 0)
    photo_cleanup = _cleanup_expired_photos(db, now, limit)
    db.commit()
    scanned = len(tasks) + photo_cleanup["scanned"]
    total_processed = processed + photo_cleanup["processed"]
    total_failed = failed + photo_cleanup["failed"]
    _log(db, "cleanup", started, scanned, total_processed, total_failed)
    return {
        "scanned": scanned,
        "processed": total_processed,
        "failed": total_failed,
        "cleanup_tasks": {"scanned": len(tasks), "processed": processed, "failed": failed, "files_cleaned": task_files_cleaned},
        "expired_photos": photo_cleanup,
    }


def apply_photo_rejects(db: Session, payload: PhotoRejectApply) -> dict:
    photo_ids = list(payload.reject_reasons.keys())
    photos = list(
        db.scalars(
            select(PhotoFile).where(
                PhotoFile.user_id == payload.user_id,
                PhotoFile.photo_id.in_(photo_ids),
            )
        )
    )
    updated = 0
    final_rejected = 0
    for photo in photos:
        photo.smart_reject_count += 1
        if photo.smart_reject_count >= 2:
            photo.smart_reject_status = "rejected_final"
            final_rejected += 1
        else:
            photo.smart_reject_status = "rejected_once"
        updated += 1
    db.commit()
    return {"requested": len(photo_ids), "updated": updated, "final_rejected": final_rejected}


def run_all(db: Session) -> dict:
    return {
        "events": scan_events(db),
        "preprocess": preprocess_photos(db),
        "decision": make_decisions(db),
        "generation": generate_albums(db),
        "push": push_results(db),
    }
