from __future__ import annotations

from copy import deepcopy

DEFAULT_DECK = {
    "version": 1,
    "title": "Editable Presentation",
    "size": {"width": 13.333, "height": 7.5},
    "slides": [{"id": "slide-1", "background": "#F7F8FC", "elements": [
        {"id": "title-1", "type": "text", "x": .8, "y": .6, "width": 11.7,
         "height": .7, "text": "可編輯簡報", "fontSize": 30, "bold": True, "color": "#17233D"},
        {"id": "box-1", "type": "shape", "x": .8, "y": 1.8, "width": 3.3,
         "height": 1.4, "text": "Slide JSON", "fontSize": 21, "fill": "#DDE7FF", "color": "#1E3A8A"},
        {"id": "box-2", "type": "shape", "x": 5, "y": 1.8, "width": 3.3,
         "height": 1.4, "text": "HTML Editor", "fontSize": 21, "fill": "#DCFCE7", "color": "#166534"},
        {"id": "box-3", "type": "shape", "x": 9.2, "y": 1.8, "width": 3.3,
         "height": 1.4, "text": "Editable PPTX", "fontSize": 21, "fill": "#FCE7F3", "color": "#9D174D"},
    ]}],
}

def normalize_deck(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("deck 必須是 JSON object")
    deck = deepcopy(value)
    deck.setdefault("version", 1); deck.setdefault("title", "Untitled")
    size = deck.setdefault("size", {"width": 13.333, "height": 7.5})
    size["width"] = min(30, max(1, float(size.get("width", 13.333))))
    size["height"] = min(30, max(1, float(size.get("height", 7.5))))
    slides = deck.setdefault("slides", [])
    if not isinstance(slides, list) or len(slides) > 200:
        raise ValueError("slides 必須是陣列，最多 200 頁")
    for si, slide in enumerate(slides):
        slide.setdefault("id", f"slide-{si + 1}"); slide.setdefault("background", "#FFFFFF")
        elements = slide.setdefault("elements", [])
        if not isinstance(elements, list) or len(elements) > 1000:
            raise ValueError("elements 必須是陣列，每頁最多 1000 個")
        for ei, el in enumerate(elements):
            if el.get("type") not in {"text", "shape", "image"}:
                raise ValueError(f"不支援的元素類型: {el.get('type')}")
            el.setdefault("id", f"el-{si + 1}-{ei + 1}")
            for key, default in (("x", 0), ("y", 0), ("width", 1), ("height", 1)):
                el[key] = max(0, float(el.get(key, default)))
            if not el["width"] or not el["height"]:
                raise ValueError("元素寬高必須大於 0")
    return deck
