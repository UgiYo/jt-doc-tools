from __future__ import annotations

import base64
import hashlib
import io
import statistics
import unicodedata

import numpy as np
from PIL import Image

from app.tools.editable_slides.pptx_io import import_pptx

from .image_edit import edit_text, estimate_background, estimate_foreground, to_png
from .pptx_core import read_media


def _data_bytes(src: str) -> bytes:
    if not src.startswith("data:image/") or ";base64," not in src:
        return b""
    return base64.b64decode(src.split(",", 1)[1], validate=True)


def _valid_words(words: list[dict]) -> list[dict]:
    result = []
    for index, word in enumerate(words):
        try:
            left, top, width, height = (int(word[k]) for k in ("left", "top", "width", "height"))
        except (KeyError, TypeError, ValueError):
            continue
        if width > 1 and height > 1 and str(word.get("text", "")).strip():
            result.append({**word, "_index": index, "left": left, "top": top, "width": width, "height": height})
    return result


def _text_mask(image: Image.Image, words: list[dict]) -> np.ndarray:
    pixels = np.asarray(image.convert("RGB"))
    mask = np.zeros(pixels.shape[:2], dtype=np.uint8)
    for word in _valid_words(words):
        x0, y0 = max(0, word["left"]), max(0, word["top"])
        x1, y1 = min(image.width, x0 + word["width"]), min(image.height, y0 + word["height"])
        if x1 <= x0 or y1 <= y0:
            continue
        bg = np.asarray(estimate_background(image, (x0, y0, x1, y1)), dtype=np.int16)
        crop = pixels[y0:y1, x0:x1].astype(np.int16)
        distance = np.sqrt(np.sum((crop - bg) ** 2, axis=2))
        mask[y0:y1, x0:x1] = np.maximum(mask[y0:y1, x0:x1], (distance > 42).astype(np.uint8) * 255)
    return mask


def _clean_image(raw: bytes, words: list[dict]) -> bytes:
    png, _ = to_png(raw)
    image = Image.open(io.BytesIO(png)).convert("RGB")
    try:
        import cv2
        mask = _text_mask(image, words)
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.dilate(mask, kernel, iterations=1)
        repaired = cv2.inpaint(cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR), mask, 3, cv2.INPAINT_TELEA)
        output = Image.fromarray(cv2.cvtColor(repaired, cv2.COLOR_BGR2RGB))
        buffer = io.BytesIO()
        output.save(buffer, "PNG")
        return buffer.getvalue()
    except (ImportError, AttributeError):
        current = png
        for word in sorted(_valid_words(words), key=lambda item: item["top"], reverse=True):
            current = edit_text(current, box=(word["left"], word["top"], word["left"] + word["width"], word["top"] + word["height"]), new_text="")
        return current


def _word_colors(raw: bytes, words: list[dict]) -> dict[int, str]:
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    colors = {}
    for word in _valid_words(words):
        box = (word["left"], word["top"], word["left"] + word["width"], word["top"] + word["height"])
        bg = estimate_background(image, box)
        fg = estimate_foreground(image, box, bg)
        colors[word["_index"]] = "#" + "".join(f"{channel:02x}" for channel in fg)
    return colors


def _line_segments(words: list[dict]) -> list[list[dict]]:
    lines: list[list[dict]] = []
    for word in sorted(_valid_words(words), key=lambda item: (item["top"] + item["height"] / 2, item["left"])):
        center = word["top"] + word["height"] / 2
        best = None
        best_distance = float("inf")
        for line in lines:
            line_center = statistics.median(item["top"] + item["height"] / 2 for item in line)
            line_height = statistics.median(item["height"] for item in line)
            distance = abs(center - line_center)
            if distance <= max(word["height"], line_height) * .55 and distance < best_distance:
                best, best_distance = line, distance
        (best if best is not None else lines.append([word]) or lines[-1]).append(word) if best is not None else None

    segments = []
    for line in lines:
        ordered = sorted(line, key=lambda item: item["left"])
        current = [ordered[0]]
        for word in ordered[1:]:
            previous = current[-1]
            gap = word["left"] - (previous["left"] + previous["width"])
            typical_height = statistics.median(item["height"] for item in current + [word])
            if gap > typical_height * 2.2:
                segments.append(current)
                current = [word]
            else:
                current.append(word)
        segments.append(current)
    return segments


def _display_width(text: str) -> float:
    return sum(1.0 if unicodedata.east_asian_width(char) in {"W", "F"} else .55 for char in text) or 1


def _segment_text(segment: list[dict], edit_map: dict, analysis_index: int) -> str:
    pieces = []
    for position, word in enumerate(segment):
        edit = edit_map.get((analysis_index, word["_index"]), {})
        text = str(edit.get("new_text", word.get("text", ""))).strip()
        if not text:
            continue
        if pieces:
            previous = segment[position - 1]
            gap = word["left"] - (previous["left"] + previous["width"])
            if gap > max(previous["height"], word["height"]) * .18:
                pieces.append(" ")
        pieces.append(text)
    return "".join(pieces)


def build_editable_deck(pptx_bytes: bytes, analyses: list[dict], edits: list[dict]) -> dict:
    """Convert image text into repaired picture backgrounds plus native, line-based text boxes."""
    deck = import_pptx(pptx_bytes)
    edit_map = {(int(e.get("image_index", -1)), int(e.get("word_index", -1))): e for e in edits}
    by_digest: dict[str, dict] = {}
    for analysis in analyses:
        media_path = analysis.get("media_path")
        words = analysis.get("words") or []
        if not media_path or not analysis.get("width") or not analysis.get("height"):
            continue
        original = read_media(pptx_bytes, media_path)
        by_digest[hashlib.sha256(original).hexdigest()] = {
            **analysis, "cleaned": _clean_image(original, words), "colors": _word_colors(original, words)
        }

    for slide in deck["slides"]:
        overlays = []
        for image in [element for element in slide["elements"] if element["type"] == "image"]:
            original = _data_bytes(image.get("src", ""))
            analysis = by_digest.get(hashlib.sha256(original).hexdigest())
            if not analysis:
                continue
            image["src"] = "data:image/png;base64," + base64.b64encode(analysis["cleaned"]).decode("ascii")
            image["ocrCandidate"] = False
            pw, ph = float(analysis["width"]), float(analysis["height"])
            analysis_index = int(analysis["index"])
            for si, segment in enumerate(_line_segments(analysis["words"])):
                text = _segment_text(segment, edit_map, analysis_index)
                if not text:
                    continue
                left = min(word["left"] for word in segment)
                top = min(word["top"] for word in segment)
                right = max(word["left"] + word["width"] for word in segment)
                bottom = max(word["top"] + word["height"] for word in segment)
                x = image["x"] + left / pw * image["width"]
                y = image["y"] + top / ph * image["height"]
                width = max(.12, (right - left) / pw * image["width"] * 1.04)
                height = max(.12, (bottom - top) / ph * image["height"] * 1.18)
                height_points = height * 72 * .78
                width_points = width * 72 / (_display_width(text) * .58)
                first_edit = next((edit_map.get((analysis_index, word["_index"])) for word in segment if edit_map.get((analysis_index, word["_index"]))), {})
                colors = [analysis["colors"].get(word["_index"], "#111827") for word in segment]
                overlays.append({
                    "id": f"ocr-{analysis_index}-{si}-{len(overlays)}", "type": "text",
                    "x": round(x, 4), "y": round(y - height * .06, 4),
                    "width": round(width, 4), "height": round(height, 4),
                    "text": text, "fontSize": round(float(first_edit.get("font_size") or max(7, min(54, height_points, width_points))), 1),
                    "fontFamily": first_edit.get("font_family") or "Microsoft JhengHei",
                    "color": first_edit.get("text_color") or statistics.mode(colors),
                    "bold": bool(first_edit.get("bold", False)), "align": "left",
                    "source": "ocr", "fitText": True,
                })
        slide["elements"].extend(overlays)
    deck["title"] = "OCR editable presentation"
    return deck
