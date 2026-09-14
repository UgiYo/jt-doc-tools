from __future__ import annotations

import base64
import hashlib

from app.tools.editable_slides.pptx_io import import_pptx

from .image_edit import edit_text, to_png
from .pptx_core import read_media


def _data_bytes(src: str) -> bytes:
    if not src.startswith("data:image/") or ";base64," not in src:
        return b""
    return base64.b64decode(src.split(",", 1)[1], validate=True)


def _clean_image(raw: bytes, words: list[dict]) -> bytes:
    current, _ = to_png(raw)
    # Bottom-up avoids a repaired area affecting the background estimate of a box above it.
    for word in sorted(words, key=lambda item: int(item.get("top", 0)), reverse=True):
        try:
            left, top = int(word["left"]), int(word["top"])
            width, height = int(word["width"]), int(word["height"])
        except (KeyError, TypeError, ValueError):
            continue
        if width > 0 and height > 0:
            current = edit_text(current, box=(left, top, left + width, top + height), new_text="")
    return current


def build_editable_deck(pptx_bytes: bytes, analyses: list[dict], edits: list[dict]) -> dict:
    """Convert image text into cleaned picture backgrounds plus native text boxes."""
    deck = import_pptx(pptx_bytes)
    edit_map = {(int(e.get("image_index", -1)), int(e.get("word_index", -1))): e for e in edits}
    by_digest: dict[str, dict] = {}
    for analysis in analyses:
        media_path = analysis.get("media_path")
        words = analysis.get("words") or []
        if not media_path or not analysis.get("width") or not analysis.get("height"):
            continue
        original = read_media(pptx_bytes, media_path)
        cleaned = _clean_image(original, words)
        by_digest[hashlib.sha256(original).hexdigest()] = {**analysis, "cleaned": cleaned}

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
            for wi, word in enumerate(analysis["words"]):
                edit = edit_map.get((int(analysis["index"]), wi), {})
                text = str(edit.get("new_text", word.get("text", "")))
                if not text:
                    continue
                x = image["x"] + float(word["left"]) / pw * image["width"]
                y = image["y"] + float(word["top"]) / ph * image["height"]
                width = max(.08, float(word["width"]) / pw * image["width"])
                height = max(.08, float(word["height"]) / ph * image["height"])
                overlays.append({
                    "id": f"ocr-{analysis['index']}-{wi}-{len(overlays)}", "type": "text",
                    "x": round(x, 4), "y": round(y, 4), "width": round(width, 4), "height": round(height, 4),
                    "text": text, "fontSize": int(edit.get("font_size") or max(7, min(54, height * 72 * .82))),
                    "fontFamily": edit.get("font_family") or "Microsoft JhengHei",
                    "color": edit.get("text_color") or "#111827", "bold": bool(edit.get("bold", False)),
                    "align": "center", "source": "ocr",
                })
        slide["elements"].extend(overlays)
    deck["title"] = "OCR editable presentation"
    return deck
