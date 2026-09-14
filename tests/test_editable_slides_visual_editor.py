from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "app/tools/editable_slides/templates/editable_slides.html").read_text(encoding="utf-8")
PPTX_IO = (ROOT / "app/tools/editable_slides/pptx_io.py").read_text(encoding="utf-8")

def test_visual_editor_has_powerpoint_style_controls():
    for marker in ("esFont", "esFontSize", "esBold", "esItalic", "esUnderline",
                   "data-align", "esColor", "esFill", "esZoomIn", "esDuplicate"):
        assert marker in TEMPLATE

def test_double_click_uses_visual_text_modal():
    assert 'id="esTextModal"' in TEMPLATE
    assert "n.ondblclick" in TEMPLATE
    assert "openTextModal(x)" in TEMPLATE
    assert 'id="esModalPreview"' in TEMPLATE

def test_visual_editor_can_insert_images_and_preserves_ocr_import():
    assert 'id="esImageFile"' in TEMPLATE
    assert "reader.readAsDataURL" in TEMPLATE
    assert "editableSlidesImport" in TEMPLATE

def test_pptx_export_preserves_extended_text_formatting():
    assert "run.font.name" in PPTX_IO
    assert "run.font.italic" in PPTX_IO
    assert "run.font.underline" in PPTX_IO
    assert "fontFamily=(run.font.name" in PPTX_IO
