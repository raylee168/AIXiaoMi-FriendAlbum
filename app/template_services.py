import base64
import json
from datetime import datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageDraw, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    AlbumTemplate,
    AlbumTemplateAsset,
    AlbumTemplateGenerationJob,
    AlbumTemplateVersion,
    PhotoFile,
    PhotoPreprocessResult,
)
from app.schemas import AlbumTemplateCreate, AlbumTemplateMatchTest, AlbumTemplateSeasonalGenerate, AlbumTemplateUpdate


REQUIRED_TEMPLATE_KEYS = {"layout", "matching_rules", "llm_prompt", "render_instructions"}


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:24]}"


def _template_dir(template_id: str, version: str = "v1") -> Path:
    path = Path(get_settings().storage_root) / "templates" / template_id / version
    path.mkdir(parents=True, exist_ok=True)
    return path


def _validate_template_json(template_json: dict) -> None:
    missing = REQUIRED_TEMPLATE_KEYS - set(template_json.keys())
    if missing:
        raise ValueError(f"template_json_missing_keys:{','.join(sorted(missing))}")
    layout = template_json.get("layout") or {}
    if not layout.get("type"):
        raise ValueError("template_layout_type_required")
    slots = layout.get("slots") or []
    if not isinstance(slots, list) or not slots:
        raise ValueError("template_layout_slots_required")


def _preview_asset(db: Session, template_id: str, version: str) -> AlbumTemplateAsset | None:
    return db.scalar(
        select(AlbumTemplateAsset)
        .where(
            AlbumTemplateAsset.template_id == template_id,
            AlbumTemplateAsset.version == version,
            AlbumTemplateAsset.asset_type == "preview",
        )
        .order_by(AlbumTemplateAsset.created_at.desc())
    )


def _data_url(path: str | None, mime_type: str = "image/jpeg") -> str | None:
    if not path or not Path(path).exists():
        return None
    payload = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{payload}"


def _version_payload(version: AlbumTemplateVersion | None) -> dict | None:
    if not version:
        return None
    return {
        "version": version.version,
        "status": version.status,
        "template_json": version.template_json,
        "llm_prompt": version.llm_prompt,
        "matching_rules": version.matching_rules_json,
        "render_params": version.render_params_json,
        "created_by": version.created_by,
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "updated_at": version.updated_at.isoformat() if version.updated_at else None,
    }


def _template_payload(db: Session, template: AlbumTemplate, include_preview: bool = True) -> dict:
    version = db.scalar(
        select(AlbumTemplateVersion).where(
            AlbumTemplateVersion.template_id == template.template_id,
            AlbumTemplateVersion.version == template.current_version,
        )
    )
    asset = _preview_asset(db, template.template_id, template.current_version)
    return {
        "template_id": template.template_id,
        "name": template.name,
        "category": template.category,
        "status": template.status,
        "min_photo_count": template.min_photo_count,
        "max_photo_count": template.max_photo_count,
        "theme_tags": template.theme_tags_json or [],
        "style_tags": template.style_tags_json or [],
        "sort_order": template.sort_order,
        "description": template.description,
        "current_version": template.current_version,
        "published_at": template.published_at.isoformat() if template.published_at else None,
        "archived_at": template.archived_at.isoformat() if template.archived_at else None,
        "created_at": template.created_at.isoformat() if template.created_at else None,
        "updated_at": template.updated_at.isoformat() if template.updated_at else None,
        "version": _version_payload(version),
        "preview_asset": {
            "asset_id": asset.asset_id,
            "width": asset.width,
            "height": asset.height,
            "summary": asset.summary_json or {},
            "data_url": _data_url(asset.file_path, asset.mime_type) if include_preview else None,
        }
        if asset
        else None,
    }


def list_templates(db: Session, status: str | None = None, category: str | None = None, q: str | None = None) -> dict:
    stmt = select(AlbumTemplate)
    if status:
        stmt = stmt.where(AlbumTemplate.status == status)
    if category:
        stmt = stmt.where(AlbumTemplate.category == category)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(AlbumTemplate.name.like(like))
    templates = list(db.scalars(stmt.order_by(AlbumTemplate.sort_order, AlbumTemplate.created_at.desc())))
    return {"items": [_template_payload(db, template, include_preview=True) for template in templates]}


def get_template(db: Session, template_id: str) -> dict:
    template = db.scalar(select(AlbumTemplate).where(AlbumTemplate.template_id == template_id))
    if not template:
        raise ValueError("template_not_found")
    return _template_payload(db, template, include_preview=True)


def create_template(db: Session, payload: AlbumTemplateCreate) -> dict:
    template_json = _normalized_template_json(payload.template_json, payload.llm_prompt, payload.matching_rules)
    _validate_template_json(template_json)
    template_id = _id("tpl")
    template = AlbumTemplate(
        template_id=template_id,
        name=payload.name,
        category=payload.category,
        status="draft",
        min_photo_count=payload.min_photo_count,
        max_photo_count=payload.max_photo_count,
        theme_tags_json=payload.theme_tags,
        style_tags_json=payload.style_tags,
        description=payload.description,
        current_version="v1",
    )
    version = AlbumTemplateVersion(
        template_id=template_id,
        version="v1",
        status="draft",
        template_json=template_json,
        llm_prompt=payload.llm_prompt,
        matching_rules_json=payload.matching_rules or template_json.get("matching_rules") or {},
        render_params_json=payload.render_params or template_json.get("render_instructions") or {},
        created_by=payload.created_by,
    )
    db.add(template)
    db.add(version)
    db.commit()
    generate_template_preview(db, template_id)
    return get_template(db, template_id)


def update_template(db: Session, template_id: str, payload: AlbumTemplateUpdate) -> dict:
    template = db.scalar(select(AlbumTemplate).where(AlbumTemplate.template_id == template_id))
    if not template:
        raise ValueError("template_not_found")
    version = db.scalar(
        select(AlbumTemplateVersion).where(
            AlbumTemplateVersion.template_id == template_id,
            AlbumTemplateVersion.version == template.current_version,
        )
    )
    if not version:
        raise ValueError("template_version_not_found")
    for field in ["name", "category", "min_photo_count", "max_photo_count", "description"]:
        value = getattr(payload, field)
        if value is not None:
            setattr(template, field, value)
    if payload.theme_tags is not None:
        template.theme_tags_json = payload.theme_tags
    if payload.style_tags is not None:
        template.style_tags_json = payload.style_tags
    if payload.llm_prompt is not None:
        version.llm_prompt = payload.llm_prompt
    if payload.matching_rules is not None:
        version.matching_rules_json = payload.matching_rules
    if payload.render_params is not None:
        version.render_params_json = payload.render_params
    if payload.template_json is not None:
        template_json = _normalized_template_json(payload.template_json, version.llm_prompt, version.matching_rules_json)
        _validate_template_json(template_json)
        version.template_json = template_json
    version.status = "draft" if template.status != "published" else "published"
    db.commit()
    generate_template_preview(db, template_id)
    return get_template(db, template_id)


def publish_template(db: Session, template_id: str) -> dict:
    template = db.scalar(select(AlbumTemplate).where(AlbumTemplate.template_id == template_id))
    if not template:
        raise ValueError("template_not_found")
    version = db.scalar(
        select(AlbumTemplateVersion).where(
            AlbumTemplateVersion.template_id == template_id,
            AlbumTemplateVersion.version == template.current_version,
        )
    )
    if not version:
        raise ValueError("template_version_not_found")
    _validate_template_json(version.template_json)
    asset = _preview_asset(db, template_id, template.current_version)
    if not asset or not asset.file_path or not Path(asset.file_path).exists():
        raise ValueError("template_preview_required")
    template.status = "published"
    template.published_at = datetime.utcnow()
    template.archived_at = None
    version.status = "published"
    db.commit()
    return get_template(db, template_id)


def archive_template(db: Session, template_id: str) -> dict:
    template = db.scalar(select(AlbumTemplate).where(AlbumTemplate.template_id == template_id))
    if not template:
        raise ValueError("template_not_found")
    template.status = "archived"
    template.archived_at = datetime.utcnow()
    versions = list(db.scalars(select(AlbumTemplateVersion).where(AlbumTemplateVersion.template_id == template_id)))
    for version in versions:
        version.status = "archived"
    db.commit()
    return get_template(db, template_id)


def generate_template_preview(db: Session, template_id: str) -> dict:
    template = db.scalar(select(AlbumTemplate).where(AlbumTemplate.template_id == template_id))
    if not template:
        raise ValueError("template_not_found")
    version = db.scalar(
        select(AlbumTemplateVersion).where(
            AlbumTemplateVersion.template_id == template_id,
            AlbumTemplateVersion.version == template.current_version,
        )
    )
    if not version:
        raise ValueError("template_version_not_found")
    image = render_template_preview_image(version.template_json, template.name)
    path = _template_dir(template_id, template.current_version) / "preview.jpg"
    image.save(path, format="JPEG", quality=88)
    asset = _preview_asset(db, template_id, template.current_version)
    if not asset:
        asset = AlbumTemplateAsset(
            asset_id=_id("asset"),
            template_id=template_id,
            version=template.current_version,
            asset_type="preview",
        )
        db.add(asset)
    asset.file_path = str(path)
    asset.mime_type = "image/jpeg"
    asset.width = image.width
    asset.height = image.height
    asset.summary_json = {
        "source": "local_preview_renderer",
        "copyright_policy": "abstracted_from_reference_not_copied",
    }
    db.commit()
    return get_template(db, template_id)


def render_template_preview_image(template_json: dict, title: str = "") -> Image.Image:
    layout = template_json.get("layout") or {}
    render = template_json.get("render_instructions") or {}
    ratio = layout.get("canvas_ratio", "1:1")
    width, height = _canvas_size(ratio)
    bg = render.get("background") or "#f8fafc"
    canvas = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(canvas)
    accent = render.get("accent_color") or "#22a06b"
    border = int(render.get("border_width", 8))
    for idx, slot in enumerate(layout.get("slots") or []):
        x = int(slot.get("x", 0) * width)
        y = int(slot.get("y", 0) * height)
        w = int(slot.get("w", 0.2) * width)
        h = int(slot.get("h", 0.2) * height)
        color = _slot_color(idx)
        draw.rounded_rectangle((x, y, x + w, y + h), radius=18, fill=color, outline="white", width=border)
        label = "主图" if slot.get("role") == "main" else str(idx + 1)
        draw.text((x + 14, y + 12), label, fill="#263238")
    text_areas = render.get("text_areas") or []
    for area in text_areas:
        x = int(area.get("x", 0.05) * width)
        y = int(area.get("y", 0.05) * height)
        draw.text((x, y), area.get("text", title)[:24], fill=accent)
    for deco in render.get("decorations") or []:
        draw.text((int(deco.get("x", 0.85) * width), int(deco.get("y", 0.08) * height)), deco.get("text", "*"), fill=accent)
    return canvas


def _canvas_size(ratio: str) -> tuple[int, int]:
    if ratio == "3:4":
        return 900, 1200
    if ratio == "4:3":
        return 1200, 900
    if ratio == "9:16":
        return 900, 1600
    if ratio == "16:9":
        return 1280, 720
    return 1080, 1080


def _slot_color(idx: int) -> str:
    colors = ["#b7e4c7", "#cde7ff", "#ffd6a5", "#ffc8dd", "#d8e2dc", "#fff3b0", "#cdb4db", "#bde0fe", "#f1f5f9"]
    return colors[idx % len(colors)]


def _normalized_template_json(template_json: dict, llm_prompt: str, matching_rules: dict) -> dict:
    result = dict(template_json or {})
    result.setdefault("matching_rules", matching_rules or {})
    result.setdefault("llm_prompt", llm_prompt)
    result.setdefault("render_instructions", {})
    return result


def generate_seasonal_templates(db: Session, payload: AlbumTemplateSeasonalGenerate) -> dict:
    target_count = max(1, min(payload.target_count, 20))
    seeds = _seasonal_seeds(payload.festival, payload.photo_count_min, payload.photo_count_max, payload.style_direction)
    job = AlbumTemplateGenerationJob(
        generation_job_id=_id("tpljob"),
        festival=payload.festival,
        target_count=target_count,
        photo_count_min=payload.photo_count_min,
        photo_count_max=payload.photo_count_max,
        style_direction=payload.style_direction,
        status="success",
        request_json=payload.model_dump(),
        template_ids_json=[],
        result_json={},
    )
    db.add(job)
    template_ids = []
    for seed in seeds[:target_count]:
        created = create_template(db, AlbumTemplateCreate(**seed, created_by=payload.created_by))
        template_ids.append(created["template_id"])
    job.template_ids_json = template_ids
    job.result_json = {"created": len(template_ids)}
    db.commit()
    return {"generation_job_id": job.generation_job_id, "created": len(template_ids), "template_ids": template_ids}


def _seasonal_seeds(festival: str, photo_min: int, photo_max: int, style_direction: str) -> list[dict]:
    base_tags = [festival, "朋友圈", "节日"]
    return [
        _seed("端午粽香美食", "food", 6, 9, base_tags + ["粽子", "美食"], ["清新", "暖色"], "grid", "适合粽子、餐桌、茶饮、家人一起吃饭的照片。"),
        _seed("端午亲子一日", "family", 4, 8, base_tags + ["亲子", "家庭"], ["可爱", "柔和"], "collage", "适合孩子、家人、手作香囊、包粽子照片。"),
        _seed("端午朋友小聚", "friends", 6, 9, base_tags + ["朋友", "聚会"], ["活泼", "手账"], "grid", "适合朋友聚餐、合照、饮品、聊天瞬间。"),
        _seed("端午出游随拍", "travel", 6, 12, base_tags + ["出游", "旅行"], ["明亮", "留白"], "long", "适合河边、海边、城市散步、户外旅行照片。"),
        _seed("国风端午节气", "festival", 3, 6, base_tags + ["国风", "节气"], ["雅致", "留白"], "poster", "适合粽叶、艾草、龙舟、传统节日氛围照片。"),
        _seed("清新九宫格", "daily", 9, 9, base_tags + ["九宫格"], ["极简", "清新"], "nine_grid", "适合 9 张亮色生活照，强调整齐、干净、朋友圈感。"),
        _seed("端午手账拼贴", "daily", 5, 8, base_tags + ["手账", "贴纸"], ["拼贴", "可爱"], "scrapbook", "适合生活碎片、小物、饮品、花束、书本照片。"),
        _seed("朋友圈封面感端午", "cover", 1, 3, base_tags + ["封面", "主图"], ["大图", "高级"], "cover", "适合一张高质量主图搭配少量补充图。"),
    ]


def _seed(name: str, category: str, min_count: int, max_count: int, theme_tags: list[str], style_tags: list[str], layout_type: str, prompt_hint: str) -> dict:
    slots = _slots_for_layout(layout_type, max_count)
    prompt = (
        f"模板名称：{name}。{prompt_hint} "
        "请根据用户照片选择清晰、情绪一致、主体明确的照片；优先把人物或最有代表性的照片放入主图位；"
        "不要选择模糊、重复、截图或文档照片；文案要适合朋友圈发布，简洁自然。"
    )
    matching_rules = {
        "theme_tags": theme_tags,
        "style_tags": style_tags,
        "min_photo_count": min_count,
        "max_photo_count": max_count,
        "preferred_scenes": theme_tags,
        "mood": ["happy", "warm", "fresh"],
    }
    template_json = {
        "layout": {"type": layout_type, "canvas_ratio": "1:1" if layout_type != "long" else "3:4", "slots": slots},
        "matching_rules": matching_rules,
        "llm_prompt": prompt,
        "render_instructions": {
            "background": "#f8fafc" if category != "festival" else "#fff7ed",
            "accent_color": "#16a34a" if category != "cover" else "#0f172a",
            "border_width": 8,
            "decorations": [{"text": "端午", "x": 0.82, "y": 0.08}],
            "text_areas": [{"x": 0.06, "y": 0.04, "text": name}],
            "watermark_area": {"x": 0.72, "y": 0.94, "w": 0.24, "h": 0.04},
        },
    }
    return {
        "name": name,
        "category": category,
        "min_photo_count": min_count,
        "max_photo_count": max_count,
        "theme_tags": theme_tags,
        "style_tags": style_tags,
        "description": prompt_hint,
        "template_json": template_json,
        "llm_prompt": prompt,
        "matching_rules": matching_rules,
        "render_params": template_json["render_instructions"],
    }


def _slots_for_layout(layout_type: str, max_count: int) -> list[dict]:
    if layout_type == "cover":
        return [{"x": 0.08, "y": 0.16, "w": 0.84, "h": 0.62, "role": "main"}]
    if layout_type == "poster":
        return [
            {"x": 0.10, "y": 0.18, "w": 0.52, "h": 0.56, "role": "main"},
            {"x": 0.66, "y": 0.18, "w": 0.24, "h": 0.26},
            {"x": 0.66, "y": 0.48, "w": 0.24, "h": 0.26},
        ]
    if layout_type == "long":
        return [
            {"x": 0.06, "y": 0.10, "w": 0.88, "h": 0.30, "role": "main"},
            {"x": 0.06, "y": 0.43, "w": 0.42, "h": 0.22},
            {"x": 0.52, "y": 0.43, "w": 0.42, "h": 0.22},
            {"x": 0.06, "y": 0.68, "w": 0.27, "h": 0.18},
            {"x": 0.365, "y": 0.68, "w": 0.27, "h": 0.18},
            {"x": 0.66, "y": 0.68, "w": 0.27, "h": 0.18},
        ]
    cols = 3
    rows = 3
    slots = []
    count = min(max_count, 9)
    for idx in range(count):
        slots.append(
            {
                "x": 0.06 + (idx % cols) * 0.30,
                "y": 0.15 + (idx // cols) * 0.25,
                "w": 0.28,
                "h": 0.22,
                "role": "main" if idx == 0 and layout_type == "collage" else "slot",
            }
        )
    return slots


def published_templates(db: Session) -> list[tuple[AlbumTemplate, AlbumTemplateVersion]]:
    templates = list(
        db.scalars(
            select(AlbumTemplate)
            .where(AlbumTemplate.status == "published")
            .order_by(AlbumTemplate.sort_order, AlbumTemplate.published_at.desc())
        )
    )
    result = []
    for template in templates:
        version = db.scalar(
            select(AlbumTemplateVersion).where(
                AlbumTemplateVersion.template_id == template.template_id,
                AlbumTemplateVersion.version == template.current_version,
                AlbumTemplateVersion.status == "published",
            )
        )
        asset = _preview_asset(db, template.template_id, template.current_version)
        if version and asset and asset.file_path and Path(asset.file_path).exists():
            result.append((template, version))
    return result


def match_templates(db: Session, payload: AlbumTemplateMatchTest) -> dict:
    summary = _summary_from_match_payload(db, payload)
    matches = _rank_templates(db, summary, payload.limit)
    return {"summary": summary, "matches": matches}


def _summary_from_match_payload(db: Session, payload: AlbumTemplateMatchTest) -> dict:
    if payload.upload_batch_id:
        photos = list(db.scalars(select(PhotoFile).where(PhotoFile.upload_batch_id == payload.upload_batch_id)))
        photo_ids = [photo.photo_id for photo in photos]
        results = list(db.scalars(select(PhotoPreprocessResult).where(PhotoPreprocessResult.photo_id.in_(photo_ids)))) if photo_ids else []
        scene_tags = sorted({tag for result in results for tag in (result.scene_tags_json or [])})
        return {
            "photo_count": len(photos),
            "scene_summary": scene_tags,
            "mood_hint": results[0].mood_hint if results else payload.mood,
            "photo_ids": photo_ids,
        }
    return {
        "photo_count": payload.photo_count or 0,
        "scene_summary": payload.scene_tags,
        "mood_hint": payload.mood,
        "photo_ids": [],
    }


def choose_templates_for_summary(db: Session, summary: dict, album_count: int) -> list[dict]:
    matches = _rank_templates(db, summary, max(album_count, 1))
    if matches:
        return [{"template_id": item["template_id"], "version": item["version"], "score": item["score"], "reason": item["reason"]} for item in matches]
    return [{"template_id": "mvp_grid_001", "version": "v1", "score": 0.5, "reason": "无已发布模板，使用内置回退模板"}]


def _rank_templates(db: Session, summary: dict, limit: int = 6) -> list[dict]:
    photo_count = int(summary.get("photo_count") or len(summary.get("photo_ids") or []) or 0)
    scene_tags = set(summary.get("scene_summary") or [])
    ranked = []
    for template, version in published_templates(db):
        score = 0.2
        reasons = []
        if template.min_photo_count <= photo_count <= template.max_photo_count:
            score += 0.45
            reasons.append("照片数量匹配")
        elif photo_count:
            score -= 0.25
            reasons.append("照片数量不完全匹配")
        rules = version.matching_rules_json or {}
        tags = set((rules.get("theme_tags") or []) + (rules.get("preferred_scenes") or []))
        hit_tags = sorted(scene_tags & tags)
        if hit_tags:
            score += min(0.25, 0.08 * len(hit_tags))
            reasons.append("场景命中：" + "、".join(hit_tags[:3]))
        if not reasons:
            reasons.append("通用模板")
        ranked.append(
            {
                "template_id": template.template_id,
                "version": version.version,
                "name": template.name,
                "category": template.category,
                "score": round(max(0.0, min(score, 0.99)), 4),
                "reason": "；".join(reasons),
                "llm_prompt": version.llm_prompt,
            }
        )
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked[: max(1, min(limit, 20))]


def get_template_definition(db: Session, template_id: str, version: str = "v1") -> dict | None:
    if template_id == "mvp_grid_001":
        return None
    record = db.scalar(
        select(AlbumTemplateVersion).where(
            AlbumTemplateVersion.template_id == template_id,
            AlbumTemplateVersion.version == version,
        )
    )
    return record.template_json if record else None


def render_album_with_template(task, photos: list[PhotoFile], template_json: dict | None) -> Image.Image:
    if not template_json:
        return None
    layout = template_json.get("layout") or {}
    render = template_json.get("render_instructions") or {}
    width, height = _canvas_size(layout.get("canvas_ratio", "1:1"))
    canvas = Image.new("RGB", (width, height), render.get("background") or "#f7f7f2")
    draw = ImageDraw.Draw(canvas)
    slots = layout.get("slots") or []
    for idx, slot in enumerate(slots):
        if idx >= len(photos):
            break
        photo = photos[idx]
        image_path = photo.thumbnail_path if Path(photo.thumbnail_path).exists() else photo.original_path
        with Image.open(image_path) as img:
            x = int(slot.get("x", 0) * width)
            y = int(slot.get("y", 0) * height)
            w = int(slot.get("w", 0.2) * width)
            h = int(slot.get("h", 0.2) * height)
            fitted = ImageOps.fit(img.convert("RGB"), (w, h))
            canvas.paste(fitted, (x, y))
            draw.rounded_rectangle((x, y, x + w, y + h), radius=16, outline="white", width=int(render.get("border_width", 8)))
    for area in render.get("text_areas") or []:
        draw.text((int(area.get("x", 0.05) * width), int(area.get("y", 0.05) * height)), area.get("text", ""), fill=render.get("accent_color") or "#222222")
    for deco in render.get("decorations") or []:
        draw.text((int(deco.get("x", 0.85) * width), int(deco.get("y", 0.08) * height)), deco.get("text", ""), fill=render.get("accent_color") or "#222222")
    if task.has_watermark:
        draw.text((int(width * 0.72), int(height * 0.95)), "AIXiaoMi Smart Album", fill="#666666")
    return canvas
