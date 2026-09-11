from __future__ import annotations

import io
import math

from PIL import Image, ImageDraw, ImageFont


def to_png(image_bytes: bytes) -> tuple[bytes, tuple[int, int]]:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue(), img.size


def _clip_box(box: tuple[int, int, int, int], size: tuple[int, int]) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = box
    w, h = size
    return max(0, x0), max(0, y0), min(w, x1), min(h, y1)


def estimate_background(img: Image.Image, box: tuple[int, int, int, int]) -> tuple[int, int, int]:
    """Estimate a solid background from a ring immediately outside the OCR box."""
    x0, y0, x1, y1 = _clip_box(box, img.size)
    pad = max(2, round(max(1, y1 - y0) * 0.18))
    samples = []
    regions = [
        (x0 - pad, y0 - pad, x1 + pad, y0),
        (x0 - pad, y1, x1 + pad, y1 + pad),
        (x0 - pad, y0, x0, y1),
        (x1, y0, x1 + pad, y1),
    ]
    for region in regions:
        r = _clip_box(region, img.size)
        if r[2] <= r[0] or r[3] <= r[1]:
            continue
        crop = img.crop(r).convert("RGB")
        samples.extend(crop.resize((min(16, crop.width), min(16, crop.height))).get_flattened_data())
    if not samples:
        return (255, 255, 255)
    mid = len(samples) // 2
    return tuple(sorted(p[i] for p in samples)[mid] for i in range(3))


def estimate_foreground(img: Image.Image, box: tuple[int, int, int, int], background: tuple[int, int, int]) -> tuple[int, int, int]:
    crop = img.crop(_clip_box(box, img.size)).convert("RGB")
    pixels = list(crop.get_flattened_data())
    if not pixels:
        return (0, 0, 0)
    def dist(p):
        return math.sqrt(sum((p[i] - background[i]) ** 2 for i in range(3)))
    contrasting = [p for p in pixels if dist(p) >= 55]
    if not contrasting:
        return (0, 0, 0) if sum(background) > 382 else (255, 255, 255)
    contrasting.sort(key=lambda p: dist(p), reverse=True)
    top = contrasting[: max(1, len(contrasting) // 5)]
    return tuple(int(sum(p[i] for p in top) / len(top)) for i in range(3))


def _load_font(font_path: str | None, size: int):
    if font_path:
        try:
            return ImageFont.truetype(font_path, size=size)
        except OSError:
            pass
    for candidate in ("DejaVuSans.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit_font(draw: ImageDraw.ImageDraw, text: str, target_w: int, target_h: int, font_path: str | None):
    lo, hi = 5, max(6, int(target_h * 1.45))
    best = _load_font(font_path, lo)
    while lo <= hi:
        mid = (lo + hi) // 2
        font = _load_font(font_path, mid)
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        if w <= target_w and h <= target_h:
            best = font
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def edit_text(image_bytes: bytes, *, box: tuple[int, int, int, int], new_text: str,
              font_path: str | None = None, pad_px: int = 2) -> bytes:
    """Erase one OCR box using estimated background and draw replacement text."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    x0, y0, x1, y1 = _clip_box(box, img.size)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("invalid edit box")
    bg = estimate_background(img, (x0, y0, x1, y1))
    fg = estimate_foreground(img, (x0, y0, x1, y1), bg)
    draw = ImageDraw.Draw(img)
    erase = _clip_box((x0 - pad_px, y0 - pad_px, x1 + pad_px, y1 + pad_px), img.size)
    draw.rectangle(erase, fill=bg)
    if new_text:
        target_w = max(1, erase[2] - erase[0] - 2)
        target_h = max(1, erase[3] - erase[1] - 2)
        font = _fit_font(draw, new_text, target_w, target_h, font_path)
        tb = draw.textbbox((0, 0), new_text, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        tx = erase[0] + max(1, (target_w - tw) // 2)
        ty = erase[1] + max(1, (target_h - th) // 2) - tb[1]
        draw.text((tx, ty), new_text, font=font, fill=fg)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
