import base64
from io import BytesIO

import httpx
from PIL import Image, ImageDraw

from app.core.config import get_settings


TEMPLATE_BASE_IMAGE_SYSTEM_PROMPT = """
You are generating base images for a WeChat Moments creative album template.
The image is not the final user album. It is a reusable template background.
Follow these rules:
1. Do not include real people, faces, celebrity likenesses, logos, QR codes, watermarks, or UI chrome.
2. Keep important decorative elements away from user-photo slots.
3. Leave clean visual areas where the renderer may later place user photos or a cutout subject.
4. The result should look like a designed social collage template, not a finished photo album.
5. Use soft lighting, clear composition, high resolution, and enough negative space.
"""


def build_template_base_prompt(template_type: str, user_prompt: str, slot_summary: str = "") -> str:
    type_hint = {
        "grid_fill": (
            "Template type: grid-fill collage. Create a designed background for a nine-grid style collage. "
            "Reserve visually clean rectangular zones for later user photos. Decorative fixed content may appear "
            "in the center row or margin areas, but should not cover the photo slots."
        ),
        "subject_cutout": (
            "Template type: subject cutout floating on a fake nine-grid scene. Create a scenic or graphic background "
            "split subtly by white grid dividers. Leave a strong foreground space where a cutout human subject can be "
            "placed later with shadow."
        ),
    }.get(template_type, "Template type: creative album background.")
    return "\n".join(
        [
            TEMPLATE_BASE_IMAGE_SYSTEM_PROMPT.strip(),
            type_hint,
            f"Slot plan: {slot_summary or 'renderer controlled slots'}",
            f"Theme and style request: {user_prompt}",
        ]
    )


def generate_template_base_image(template_type: str, user_prompt: str, size: str = "1024x1024", slot_summary: str = "") -> tuple[Image.Image, dict]:
    settings = get_settings()
    prompt = build_template_base_prompt(template_type, user_prompt, slot_summary)
    if settings.mock_image_generation or not settings.agnes_image_api_key:
        return _mock_base_image(template_type, user_prompt, size), {
            "provider": "local_mock",
            "prompt": prompt,
            "model": "local-template-placeholder",
        }

    response = httpx.post(
        settings.agnes_image_base_url,
        headers={
            "Authorization": f"Bearer {settings.agnes_image_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": settings.agnes_image_model,
            "prompt": prompt,
            "size": size,
            "return_base64": True,
        },
        timeout=90,
    )
    response.raise_for_status()
    payload = response.json()
    image_b64 = _extract_base64(payload)
    image = Image.open(BytesIO(base64.b64decode(image_b64))).convert("RGB")
    return image, {
        "provider": "agnes-ai",
        "prompt": prompt,
        "model": settings.agnes_image_model,
        "size": size,
    }


def _extract_base64(payload: dict) -> str:
    if payload.get("data") and isinstance(payload["data"], list):
        first = payload["data"][0] or {}
        if first.get("b64_json"):
            return first["b64_json"]
        if first.get("base64"):
            return first["base64"]
    if payload.get("b64_json"):
        return payload["b64_json"]
    if payload.get("base64"):
        return payload["base64"]
    raise ValueError("image_generation_response_missing_base64")


def _mock_base_image(template_type: str, user_prompt: str, size: str) -> Image.Image:
    width, height = _parse_size(size)
    bg = "#f8fff4" if "端午" in user_prompt else "#f8fafc"
    image = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(image)
    if template_type == "subject_cutout":
        _draw_fake_grid_landscape(draw, width, height)
    else:
        _draw_grid_background(draw, width, height)
    draw.text((32, 28), (user_prompt or "Template")[:28], fill="#166534")
    return image


def _parse_size(size: str) -> tuple[int, int]:
    try:
        w, h = size.lower().split("x", 1)
        return max(256, int(w)), max(256, int(h))
    except Exception:
        return 1024, 1024


def _draw_grid_background(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    margin = int(width * 0.04)
    gap = int(width * 0.018)
    cell = (width - margin * 2 - gap * 2) // 3
    for row in range(3):
        for col in range(3):
            x = margin + col * (cell + gap)
            y = margin + row * (cell + gap)
            if row == 1:
                draw.rounded_rectangle((x, y, x + cell, y + cell), radius=18, fill="#fff7ed", outline="#ffffff", width=6)
            else:
                draw.rounded_rectangle((x, y, x + cell, y + cell), radius=18, fill="#ffffff", outline="#dbeafe", width=4)
    draw.text((margin + cell, margin + cell + gap + cell // 2 - 12), "节日祝福", fill="#16a34a")


def _draw_fake_grid_landscape(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    for y in range(height):
        ratio = y / max(1, height)
        if ratio < 0.45:
            color = (238, int(230 - ratio * 80), 140)
        else:
            color = (int(130 - ratio * 30), int(170 - ratio * 45), 60)
        draw.line((0, y, width, y), fill=color)
    for x in [width // 3, width * 2 // 3]:
        draw.rectangle((x - 8, 0, x + 8, height), fill="#ffffff")
    for y in [height // 3, height * 2 // 3]:
        draw.rectangle((0, y - 8, width, y + 8), fill="#ffffff")
    draw.ellipse((width * 0.48, height * 0.18, width * 0.58, height * 0.28), fill="#fff7ad")
