import base64
import json
import re
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
from app.schemas import AlbumTemplateFactoryGenerate


REQUIRED_TEMPLATE_KEYS = {"layout", "matching_rules", "llm_prompt", "render_instructions"}


BASE_TEMPLATE_LIBRARY = [
    {
        "base_template_id": "base_grid_1",
        "name": "1张图填充",
        "photo_count_min": 1,
        "photo_count_max": 1,
        "family": "grid",
        "description": "单张照片填满九宫格画布，适合高质量主图、封面感图片。",
        "layout": {"type": "base_grid_1", "canvas_ratio": "1:1", "slots": [{"x": 0.06, "y": 0.14, "w": 0.88, "h": 0.72, "role": "main", "source": "user"}]},
    },
    {
        "base_template_id": "base_grid_2",
        "name": "2张图填充",
        "photo_count_min": 2,
        "photo_count_max": 2,
        "family": "grid",
        "description": "两张照片左右并排，适合对比、情侣、朋友、双主体场景。",
        "layout": {"type": "base_grid_2", "canvas_ratio": "1:1", "slots": [{"x": 0.06, "y": 0.20, "w": 0.42, "h": 0.60, "source": "user"}, {"x": 0.52, "y": 0.20, "w": 0.42, "h": 0.60, "source": "user"}]},
    },
    {
        "base_template_id": "base_grid_3",
        "name": "3张图填充",
        "photo_count_min": 3,
        "photo_count_max": 3,
        "family": "grid",
        "description": "一张主图加两张辅助图，适合旅行、美食、聚会的重点叙事。",
        "layout": {"type": "base_grid_3", "canvas_ratio": "1:1", "slots": [{"x": 0.06, "y": 0.16, "w": 0.58, "h": 0.68, "role": "main", "source": "user"}, {"x": 0.68, "y": 0.16, "w": 0.26, "h": 0.31, "source": "user"}, {"x": 0.68, "y": 0.53, "w": 0.26, "h": 0.31, "source": "user"}]},
    },
    {
        "base_template_id": "base_grid_4",
        "name": "4张图填充",
        "photo_count_min": 4,
        "photo_count_max": 4,
        "family": "grid",
        "description": "标准四宫格，适合整齐、干净、主题统一的照片组。",
        "layout": {"type": "base_grid_4", "canvas_ratio": "1:1", "slots": [{"x": 0.06 + (i % 2) * 0.45, "y": 0.14 + (i // 2) * 0.38, "w": 0.42, "h": 0.34, "source": "user"} for i in range(4)]},
    },
    {
        "base_template_id": "base_grid_5",
        "name": "5张图填充",
        "photo_count_min": 5,
        "photo_count_max": 5,
        "family": "grid",
        "description": "一张主图带四张辅助图，适合有明确主角的生活碎片。",
        "layout": {"type": "base_grid_5", "canvas_ratio": "1:1", "slots": [{"x": 0.06, "y": 0.16, "w": 0.54, "h": 0.54, "role": "main", "source": "user"}] + [{"x": 0.64 + (i % 2) * 0.15, "y": 0.16 + (i // 2) * 0.28, "w": 0.13, "h": 0.24, "source": "user"} for i in range(4)]},
    },
    {
        "base_template_id": "base_grid_6",
        "name": "6张图填充",
        "photo_count_min": 6,
        "photo_count_max": 6,
        "family": "grid",
        "description": "2行3列均衡网格，适合朋友圈常规多图展示。",
        "layout": {"type": "base_grid_6", "canvas_ratio": "1:1", "slots": [{"x": 0.06 + (i % 3) * 0.30, "y": 0.18 + (i // 3) * 0.32, "w": 0.28, "h": 0.28, "source": "user"} for i in range(6)]},
    },
    {
        "base_template_id": "base_grid_7",
        "name": "7张图填充",
        "photo_count_min": 7,
        "photo_count_max": 7,
        "family": "grid",
        "description": "一张横向主图加六张小图，适合游记、活动回顾。",
        "layout": {"type": "base_grid_7", "canvas_ratio": "1:1", "slots": [{"x": 0.06, "y": 0.12, "w": 0.88, "h": 0.30, "role": "main", "source": "user"}] + [{"x": 0.06 + (i % 3) * 0.30, "y": 0.48 + (i // 3) * 0.22, "w": 0.28, "h": 0.20, "source": "user"} for i in range(6)]},
    },
    {
        "base_template_id": "base_grid_8",
        "name": "8张图填充",
        "photo_count_min": 8,
        "photo_count_max": 8,
        "family": "grid",
        "description": "预留一个主题位的九宫格，适合节日祝福图加用户照片。",
        "layout": {"type": "base_grid_8", "canvas_ratio": "1:1", "slots": [{"x": 0.06 + (i % 3) * 0.30, "y": 0.15 + (i // 3) * 0.25, "w": 0.28, "h": 0.22, "source": "generated" if i == 4 else "user"} for i in range(9)]},
    },
    {
        "base_template_id": "base_grid_9",
        "name": "9张图填充",
        "photo_count_min": 9,
        "photo_count_max": 9,
        "family": "grid",
        "description": "完整九宫格，适合照片数量充足、视觉整齐的朋友圈相册。",
        "layout": {"type": "base_grid_9", "canvas_ratio": "1:1", "slots": [{"x": 0.06 + (i % 3) * 0.30, "y": 0.15 + (i // 3) * 0.25, "w": 0.28, "h": 0.22, "source": "user"} for i in range(9)]},
    },
    {
        "base_template_id": "base_portrait_overflow",
        "name": "人像主图放大越界",
        "photo_count_min": 1,
        "photo_count_max": 6,
        "family": "creative",
        "description": "人像主图放大并越出九宫格边界，后方保留小图和祝福位，适合封面感、人物感强的相册。",
        "layout": {"type": "base_portrait_overflow", "canvas_ratio": "1:1", "slots": [{"x": 0.42, "y": -0.03, "w": 0.56, "h": 0.82, "role": "main", "source": "user", "overflow": True}, {"x": 0.07, "y": 0.24, "w": 0.28, "h": 0.22, "source": "user"}, {"x": 0.07, "y": 0.50, "w": 0.28, "h": 0.22, "source": "generated"}, {"x": 0.07, "y": 0.76, "w": 0.28, "h": 0.18, "source": "empty"}]},
    },
    {
        "base_template_id": "base_blessing_mix",
        "name": "照片祝福混排",
        "photo_count_min": 1,
        "photo_count_max": 6,
        "family": "festival",
        "description": "用户照片、节日祝福图、空白留白混排，适合少量照片生成丰富节日相册。",
        "layout": {"type": "base_blessing_mix", "canvas_ratio": "1:1", "slots": [{"x": 0.06 + (i % 3) * 0.30, "y": 0.15 + (i // 3) * 0.25, "w": 0.28, "h": 0.22, "source": "user" if i in [0, 2, 3, 5, 6, 8] else ("generated" if i in [1, 4] else "empty")} for i in range(9)]},
    },
]


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
    else:
        stmt = stmt.where(AlbumTemplate.status != "archived")
    if category:
        stmt = stmt.where(AlbumTemplate.category == category)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(AlbumTemplate.name.like(like))
    templates = list(db.scalars(stmt.order_by(AlbumTemplate.sort_order, AlbumTemplate.created_at.desc())))
    return {"items": [_template_payload(db, template, include_preview=True) for template in templates]}


def list_base_templates() -> dict:
    return {"items": BASE_TEMPLATE_LIBRARY}


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
        _draw_slot_preview(draw, (x, y, x + w, y + h), slot, idx, border, template_json)
    text_areas = render.get("text_areas") or []
    for area in text_areas:
        x = int(area.get("x", 0.05) * width)
        y = int(area.get("y", 0.05) * height)
        draw.text((x, y), area.get("text", title)[:24], fill=accent)
    for deco in render.get("decorations") or []:
        draw.text((int(deco.get("x", 0.85) * width), int(deco.get("y", 0.08) * height)), deco.get("text", "*"), fill=accent)
    return canvas


def _draw_slot_preview(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], slot: dict, idx: int, border: int, template_json: dict) -> None:
    source = slot.get("source", "user")
    if source == "generated":
        _draw_generated_card(draw, box, template_json, idx)
        return
    if source == "empty":
        draw.rounded_rectangle(box, radius=18, fill="#ffffff", outline="#d7eadc", width=max(2, border // 2))
        draw.text((box[0] + 12, box[1] + 12), "留白", fill="#86a58f")
        return
    color = _slot_color(idx)
    draw.rounded_rectangle(box, radius=18, fill=color, outline="white", width=border)
    label = "主图" if slot.get("role") == "main" else f"用户图{idx + 1}"
    draw.text((box[0] + 14, box[1] + 12), label, fill="#263238")


def _draw_generated_card(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], template_json: dict, idx: int) -> None:
    render = template_json.get("render_instructions") or {}
    theme = render.get("theme") or "端午节"
    blessings = render.get("blessing_texts") or ["端午安康", "粽有好运", "夏日清欢", "平安喜乐"]
    text = blessings[idx % len(blessings)]
    accent = render.get("accent_color") or "#16a34a"
    draw.rounded_rectangle(box, radius=18, fill="#fff7ed", outline="#ffffff", width=6)
    draw.text((box[0] + 14, box[1] + 12), theme, fill=accent)
    draw.text((box[0] + 14, box[1] + max(34, (box[3] + box[1]) // 2 - 12)), text, fill="#92400e")
    draw.text((box[2] - 52, box[3] - 30), "AI图", fill="#c2410c")


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


def generate_templates_from_dialog(db: Session, payload: AlbumTemplateFactoryGenerate) -> dict:
    plan = _plan_from_dialog(payload)
    job = AlbumTemplateGenerationJob(
        generation_job_id=_id("tpljob"),
        festival=plan["theme"],
        target_count=plan["target_count"],
        photo_count_min=plan["photo_count_min"],
        photo_count_max=plan["photo_count_max"],
        style_direction=plan["style_direction"],
        status="success",
        request_json=payload.model_dump(),
        template_ids_json=[],
        result_json={"plan": plan, "base_template_ids": [item["base_template_id"] for item in plan["base_templates"]]},
    )
    db.add(job)
    template_ids = []
    for seed in _dialog_template_seeds(plan):
        created = create_template(db, AlbumTemplateCreate(**seed, created_by=payload.created_by))
        template_ids.append(created["template_id"])
    job.template_ids_json = template_ids
    job.result_json = {**(job.result_json or {}), "created": len(template_ids)}
    db.commit()
    return {
        "generation_job_id": job.generation_job_id,
        "created": len(template_ids),
        "template_ids": template_ids,
        "plan": plan,
    }


def _plan_from_dialog(payload: AlbumTemplateFactoryGenerate) -> dict:
    prompt = payload.prompt.strip()
    photo_min, photo_max = _extract_photo_range(prompt)
    target_count = payload.target_count or _extract_target_count(prompt) or 8
    theme = payload.theme or _extract_theme(prompt) or "端午节"
    photo_min = payload.photo_count_min or photo_min or 1
    photo_max = payload.photo_count_max or photo_max or 6
    photo_min = max(1, min(photo_min, 9))
    photo_max = max(photo_min, min(photo_max, 9))
    target_count = max(1, min(target_count, 20))
    base_templates = _select_base_templates(photo_min, photo_max, target_count, prompt)
    return {
        "prompt": prompt,
        "theme": theme,
        "target_count": target_count,
        "photo_count_min": photo_min,
        "photo_count_max": photo_max,
        "style_direction": _extract_style_direction(prompt),
        "base_templates": base_templates,
        "strategy": "local_rule_planner_ready_for_llm",
    }


def _extract_target_count(prompt: str) -> int | None:
    match = re.search(r"(\d+)\s*个", prompt)
    return int(match.group(1)) if match else None


def _extract_photo_range(prompt: str) -> tuple[int | None, int | None]:
    match = re.search(r"(\d+)\s*[-到至]\s*(\d+)\s*张", prompt)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.search(r"(\d+)\s*张", prompt)
    if match:
        value = int(match.group(1))
        return value, value
    return None, None


def _extract_theme(prompt: str) -> str | None:
    match = re.search(r"以(.{1,12}?)(?:为主题|主题)", prompt)
    if match:
        return match.group(1).strip(" ，。,.")
    if "端午" in prompt:
        return "端午节"
    return None


def _extract_style_direction(prompt: str) -> str:
    hints = []
    for word in ["创意", "清新", "国风", "手账", "祝福", "朋友圈", "高级", "可爱", "美食", "亲子", "旅行"]:
        if word in prompt:
            hints.append(word)
    return "、".join(hints or ["朋友圈", "创意", "节日氛围"])


def _select_base_templates(photo_min: int, photo_max: int, target_count: int, prompt: str) -> list[dict]:
    candidates = [
        item for item in BASE_TEMPLATE_LIBRARY
        if item["photo_count_min"] <= photo_max and item["photo_count_max"] >= photo_min
    ]
    if "人像" in prompt or "主图" in prompt or "越出" in prompt:
        candidates.sort(key=lambda item: 0 if item["base_template_id"] == "base_portrait_overflow" else 1)
    if not candidates:
        candidates = BASE_TEMPLATE_LIBRARY[:]
    return [candidates[idx % len(candidates)] for idx in range(target_count)]


def _dialog_template_seeds(plan: dict) -> list[dict]:
    seeds = []
    styles = ["粽香祝福", "清新艾草", "国风留白", "手账拼贴", "夏日小聚", "朋友圈封面", "亲子温暖", "旅行随拍"]
    for idx, base in enumerate(plan["base_templates"]):
        style = styles[idx % len(styles)]
        name = f"{plan['theme']}{style}{idx + 1:02d}"
        min_count = max(plan["photo_count_min"], base["photo_count_min"])
        max_count = min(plan["photo_count_max"], base["photo_count_max"])
        if min_count > max_count:
            min_count, max_count = plan["photo_count_min"], plan["photo_count_max"]
        template_json = _user_template_from_base(base, plan, idx, name)
        matching_rules = {
            "theme_tags": [plan["theme"], "朋友圈", "节日", style],
            "style_tags": [style, plan["style_direction"]],
            "min_photo_count": min_count,
            "max_photo_count": max_count,
            "preferred_scenes": [plan["theme"], "美食", "亲子", "朋友", "旅行", "人像"],
            "mood": ["warm", "fresh", "happy"],
            "base_template_id": base["base_template_id"],
        }
        llm_prompt = (
            f"这是由底层模板“{base['name']}”预加工出的用户模板。"
            f"主题是{plan['theme']}，用户只需要上传{min_count}-{max_count}张照片。"
            "source=user 的槽位填用户照片，source=generated 的槽位使用系统预生成祝福图，source=empty 保持留白。"
            "选图优先清晰、有节日氛围、主体明确的照片；人像主图模板优先选择半身或全身人像。"
        )
        seeds.append(
            {
                "name": name,
                "category": "factory",
                "min_photo_count": min_count,
                "max_photo_count": max_count,
                "theme_tags": [plan["theme"], "朋友圈", "节日", style],
                "style_tags": [style, "对话生成", base["family"]],
                "description": f"基于“{base['name']}”生成：{base['description']}",
                "template_json": template_json,
                "llm_prompt": llm_prompt,
                "matching_rules": matching_rules,
                "render_params": template_json["render_instructions"],
            }
        )
    return seeds


def _user_template_from_base(base: dict, plan: dict, idx: int, name: str) -> dict:
    layout = json.loads(json.dumps(base["layout"]))
    slots = layout.get("slots") or []
    user_budget = min(plan["photo_count_max"], sum(1 for slot in slots if slot.get("source", "user") == "user"))
    used_user = 0
    for slot_idx, slot in enumerate(slots):
        if slot.get("source", "user") == "user":
            used_user += 1
            if used_user > user_budget:
                slot["source"] = "empty"
        slot.setdefault("slot_id", f"s{slot_idx + 1}")
    blessings = _theme_blessings(plan["theme"], idx)
    return {
        "base_template_id": base["base_template_id"],
        "layout": layout,
        "matching_rules": {},
        "llm_prompt": "",
        "render_instructions": {
            "theme": plan["theme"],
            "background": _theme_background(idx),
            "accent_color": _theme_accent(idx),
            "border_width": 8,
            "blessing_texts": blessings,
            "decorations": [{"text": plan["theme"], "x": 0.82, "y": 0.06}],
            "text_areas": [{"x": 0.06, "y": 0.04, "text": name}],
            "watermark_area": {"x": 0.72, "y": 0.94, "w": 0.24, "h": 0.04},
        },
    }


def _theme_blessings(theme: str, idx: int) -> list[str]:
    if "端午" in theme:
        groups = [
            ["端午安康", "粽有好运", "仲夏清欢"],
            ["一口香粽", "万事顺意", "平安喜乐"],
            ["艾草清香", "好运常在", "岁岁安康"],
        ]
        return groups[idx % len(groups)]
    return [f"{theme}快乐", "平安喜乐", "好事发生"]


def _theme_background(idx: int) -> str:
    return ["#f8fff4", "#fff7ed", "#f0fdfa", "#f8fafc", "#fff1f2"][idx % 5]


def _theme_accent(idx: int) -> str:
    return ["#16a34a", "#b45309", "#0f766e", "#334155", "#be123c"][idx % 5]


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
    user_idx = 0
    for idx, slot in enumerate(slots):
        source = slot.get("source", "user")
        x = int(slot.get("x", 0) * width)
        y = int(slot.get("y", 0) * height)
        w = int(slot.get("w", 0.2) * width)
        h = int(slot.get("h", 0.2) * height)
        if source == "generated":
            _draw_generated_card(draw, (x, y, x + w, y + h), template_json, idx)
            continue
        if source == "empty":
            draw.rounded_rectangle((x, y, x + w, y + h), radius=16, fill="#ffffff", outline="#d7eadc", width=4)
            continue
        if user_idx >= len(photos):
            draw.rounded_rectangle((x, y, x + w, y + h), radius=16, fill="#f8fafc", outline="#e2e8f0", width=4)
            continue
        photo = photos[user_idx]
        user_idx += 1
        image_path = photo.thumbnail_path if Path(photo.thumbnail_path).exists() else photo.original_path
        with Image.open(image_path) as img:
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
