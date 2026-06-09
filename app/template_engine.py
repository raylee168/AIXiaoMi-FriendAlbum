from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps


def render_template_image(template_json: dict, photo_paths: list[str], watermark: bool = False) -> Image.Image:
    renderer = TemplateRendererFactory.create(template_json)
    return renderer.render(photo_paths, watermark=watermark)


class TemplateRendererFactory:
    @staticmethod
    def create(template_json: dict):
        template_type = template_json.get("template_type") or (template_json.get("layout") or {}).get("type") or "grid_fill"
        if template_type in {"subject_cutout", "base_portrait_overflow"}:
            return SubjectCutoutRenderer(template_json)
        return GridFillRenderer(template_json)


class BaseTemplateRenderer:
    def __init__(self, template_json: dict):
        self.template_json = template_json
        self.layout = template_json.get("layout") or {}
        self.render_params = template_json.get("render_instructions") or {}
        self.width, self.height = self._canvas_size(self.layout.get("canvas_ratio", "1:1"))

    def _canvas(self) -> Image.Image:
        base_path = self.render_params.get("base_image_path")
        if base_path and Path(base_path).exists():
            with Image.open(base_path) as image:
                return ImageOps.fit(image.convert("RGB"), (self.width, self.height))
        return Image.new("RGB", (self.width, self.height), self.render_params.get("background") or "#f8fafc")

    def _canvas_size(self, ratio: str) -> tuple[int, int]:
        if ratio == "3:4":
            return 900, 1200
        if ratio == "4:3":
            return 1200, 900
        if ratio == "9:16":
            return 900, 1600
        if ratio == "16:9":
            return 1280, 720
        return 1080, 1080

    def _box(self, slot: dict) -> tuple[int, int, int, int]:
        x = int(slot.get("x", 0) * self.width)
        y = int(slot.get("y", 0) * self.height)
        w = int(slot.get("w", 0.2) * self.width)
        h = int(slot.get("h", 0.2) * self.height)
        return x, y, x + w, y + h

    def _draw_watermark(self, draw: ImageDraw.ImageDraw) -> None:
        draw.text((int(self.width * 0.70), int(self.height * 0.95)), "AIXiaoMi Smart Album", fill="#666666")


class GridFillRenderer(BaseTemplateRenderer):
    def render(self, photo_paths: list[str], watermark: bool = False) -> Image.Image:
        canvas = self._canvas()
        draw = ImageDraw.Draw(canvas)
        photo_index = 0
        for idx, slot in enumerate(self.layout.get("slots") or []):
            source = slot.get("source", "user")
            box = self._box(slot)
            if source == "user":
                if photo_index < len(photo_paths):
                    self._paste_photo(canvas, draw, photo_paths[photo_index], box)
                    photo_index += 1
                else:
                    self._draw_empty(draw, box)
            elif source == "generated":
                self._draw_generated(draw, box, idx)
            elif source == "empty":
                self._draw_empty(draw, box)
        self._draw_texts(draw)
        if watermark:
            self._draw_watermark(draw)
        return canvas

    def _paste_photo(self, canvas: Image.Image, draw: ImageDraw.ImageDraw, path: str, box: tuple[int, int, int, int]) -> None:
        x1, y1, x2, y2 = box
        with Image.open(path) as image:
            fitted = ImageOps.fit(image.convert("RGB"), (x2 - x1, y2 - y1))
        canvas.paste(fitted, (x1, y1))
        draw.rounded_rectangle(box, radius=14, outline="white", width=int(self.render_params.get("border_width", 8)))

    def _draw_generated(self, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], idx: int) -> None:
        blessings = self.render_params.get("blessing_texts") or ["端午安康", "粽有好运", "平安喜乐"]
        accent = self.render_params.get("accent_color") or "#16a34a"
        draw.rounded_rectangle(box, radius=16, fill="#fff7ed", outline="white", width=6)
        draw.text((box[0] + 14, box[1] + 14), blessings[idx % len(blessings)], fill=accent)
        draw.text((box[0] + 14, box[3] - 34), "固定祝福图", fill="#b45309")

    def _draw_empty(self, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
        draw.rounded_rectangle(box, radius=14, fill="#ffffff", outline="#d8eadf", width=4)

    def _draw_texts(self, draw: ImageDraw.ImageDraw) -> None:
        for area in self.render_params.get("text_areas") or []:
            draw.text((int(area.get("x", 0.05) * self.width), int(area.get("y", 0.05) * self.height)), area.get("text", ""), fill=self.render_params.get("accent_color") or "#222222")


class SubjectCutoutRenderer(BaseTemplateRenderer):
    def render(self, photo_paths: list[str], watermark: bool = False) -> Image.Image:
        canvas = self._canvas()
        draw = ImageDraw.Draw(canvas)
        self._draw_grid_lines(draw)
        if photo_paths:
            subject = self._extract_subject(photo_paths[0])
            self._paste_subject(canvas, subject)
        else:
            self._draw_subject_placeholder(draw)
        self._draw_texts(draw)
        if watermark:
            self._draw_watermark(draw)
        return canvas

    def _draw_grid_lines(self, draw: ImageDraw.ImageDraw) -> None:
        if not self.render_params.get("draw_grid_lines", True):
            return
        line_width = int(self.render_params.get("grid_line_width", 14))
        color = self.render_params.get("grid_line_color") or "#ffffff"
        for x in [self.width // 3, self.width * 2 // 3]:
            draw.rectangle((x - line_width // 2, 0, x + line_width // 2, self.height), fill=color)
        for y in [self.height // 3, self.height * 2 // 3]:
            draw.rectangle((0, y - line_width // 2, self.width, y + line_width // 2), fill=color)

    def _extract_subject(self, photo_path: str) -> Image.Image:
        with Image.open(photo_path) as image:
            source = image.convert("RGBA")
        crop = ImageOps.fit(source, (620, 860), centering=(0.5, 0.42))
        mask = Image.new("L", crop.size, 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((70, 20, crop.width - 70, crop.height - 20), fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(5))
        crop.putalpha(mask)
        return crop

    def _paste_subject(self, canvas: Image.Image, subject: Image.Image) -> None:
        placement = self.render_params.get("subject_placement") or {"x": 0.34, "y": 0.08, "w": 0.42, "h": 0.82}
        x = int(placement.get("x", 0.34) * self.width)
        y = int(placement.get("y", 0.08) * self.height)
        w = int(placement.get("w", 0.42) * self.width)
        h = int(placement.get("h", 0.82) * self.height)
        subject = ImageOps.contain(subject, (w, h))
        shadow = Image.new("RGBA", subject.size, (0, 0, 0, 0))
        alpha = subject.getchannel("A").filter(ImageFilter.GaussianBlur(16))
        shadow.putalpha(alpha.point(lambda value: int(value * 0.32)))
        canvas.paste(shadow, (x + 18, y + 24), shadow)
        canvas.paste(subject, (x, y), subject)

    def _draw_subject_placeholder(self, draw: ImageDraw.ImageDraw) -> None:
        placement = self.render_params.get("subject_placement") or {"x": 0.34, "y": 0.08, "w": 0.42, "h": 0.82}
        box = (
            int(placement.get("x", 0.34) * self.width),
            int(placement.get("y", 0.08) * self.height),
            int((placement.get("x", 0.34) + placement.get("w", 0.42)) * self.width),
            int((placement.get("y", 0.08) + placement.get("h", 0.82)) * self.height),
        )
        draw.ellipse(box, fill="#ffffff88", outline="#16a34a", width=6)
        draw.text((box[0] + 24, box[1] + 24), "主体抠图位", fill="#166534")

    def _draw_texts(self, draw: ImageDraw.ImageDraw) -> None:
        for area in self.render_params.get("text_areas") or []:
            draw.text((int(area.get("x", 0.05) * self.width), int(area.get("y", 0.05) * self.height)), area.get("text", ""), fill=self.render_params.get("accent_color") or "#ffffff")
