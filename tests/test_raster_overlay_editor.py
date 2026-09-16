import base64
import io
import json

from PIL import Image

from app.tools.ppt_image_text_editor.image_edit import apply_overlays, edit_text


def _png(size=(320, 180), color="white"):
    im = Image.new("RGB", size, color)
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue()


def _pixel(raw, xy):
    with Image.open(io.BytesIO(raw)) as im:
        return im.convert("RGB").getpixel(xy)


def test_overlay_shapes_and_text_render():
    raw = _png()
    out = apply_overlays(raw, [
        {"overlay_type": "whiteout", "left": 10, "top": 10, "width": 50, "height": 30, "z": 0},
        {"overlay_type": "rect", "left": 70, "top": 20, "width": 80, "height": 50, "color": "#ff0000", "stroke_width": 4, "z": 1},
        {"overlay_type": "ellipse", "left": 170, "top": 20, "width": 70, "height": 50, "color": "#0000ff", "stroke_width": 4, "z": 2},
        {"overlay_type": "line", "left": 20, "top": 100, "width": 80, "height": 40, "color": "#00aa00", "stroke_width": 5, "z": 3},
        {"overlay_type": "arrow", "left": 120, "top": 100, "width": 80, "height": 40, "color": "#111111", "stroke_width": 5, "z": 4},
        {"overlay_type": "text", "left": 220, "top": 100, "width": 90, "height": 50, "text": "ABC", "font_size": 24, "color": "#111111", "z": 5},
    ])
    assert out.startswith(b"\x89PNG")
    assert _pixel(out, (70, 20))[0] > 200
    assert _pixel(out, (20, 100))[1] > 80


def test_inserted_image_renders():
    icon = _png((12, 12), "red")
    data_url = "data:image/png;base64," + base64.b64encode(icon).decode("ascii")
    out = apply_overlays(_png(), [{"overlay_type": "image", "left": 30, "top": 30, "width": 40, "height": 40, "data_url": data_url}])
    r, g, b = _pixel(out, (45, 45))
    assert r > 200 and g < 80 and b < 80


def test_image_resize_rotation_and_opacity_render():
    icon = _png((20, 10), "red")
    data_url = "data:image/png;base64," + base64.b64encode(icon).decode("ascii")
    out = apply_overlays(_png(), [{
        "overlay_type": "image",
        "left": 80,
        "top": 40,
        "width": 100,
        "height": 50,
        "data_url": data_url,
        "opacity": 0.5,
        "rotation": 30,
    }])
    # The transformed image must affect the expected center while remaining blended.
    r, g, b = _pixel(out, (130, 65))
    assert r > 200 and 70 < g < 220 and 70 < b < 220


def test_rotated_shape_renders_away_from_unrotated_corner():
    out = apply_overlays(_png(), [{
        "overlay_type": "rect",
        "left": 100,
        "top": 50,
        "width": 80,
        "height": 40,
        "color": "#000000",
        "stroke_width": 6,
        "rotation": 45,
    }])
    # Rotation expands around the same center; a pixel outside the original box is touched.
    with Image.open(io.BytesIO(out)) as im:
        pixels = im.convert("RGB")
        changed = 0
        for y in range(35, 105):
            for x in range(85, 195):
                if pixels.getpixel((x, y)) != (255, 255, 255):
                    changed += 1
        assert changed > 100


def test_ppt_overlay_sentinel_uses_existing_edit_pipeline():
    obj = {"overlay_type": "rect", "left": 40, "top": 40, "width": 80, "height": 40, "color": "#ff0000", "stroke_width": 5, "z": 1}
    sentinel = "__JT_OVERLAY__" + json.dumps(obj)
    out = edit_text(_png(), box=(0, 0, 1, 1), new_text=sentinel, output_format="PNG")
    assert _pixel(out, (40, 40))[0] > 200


def test_ppt_sentinel_preserves_transform_properties():
    obj = {
        "overlay_type": "ellipse",
        "left": 60,
        "top": 40,
        "width": 90,
        "height": 50,
        "color": "#0000ff",
        "stroke_width": 5,
        "opacity": 0.6,
        "rotation": -25,
        "z": 2,
    }
    sentinel = "__JT_OVERLAY__" + json.dumps(obj)
    out = edit_text(_png(), box=(0, 0, 1, 1), new_text=sentinel, output_format="PNG")
    assert out.startswith(b"\x89PNG")
    assert any(_pixel(out, (x, 65)) != (255, 255, 255) for x in range(50, 165))


def test_jpeg_output_supported():
    out = apply_overlays(_png(), [{"overlay_type": "text", "left": 10, "top": 10, "width": 100, "height": 40, "text": "test"}], "JPEG")
    assert out.startswith(b"\xff\xd8")
