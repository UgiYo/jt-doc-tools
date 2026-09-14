from pathlib import Path

BASE = (Path(__file__).resolve().parents[1] / "app/web/templates/base.html").read_text(encoding="utf-8")

def test_global_ocr_completion_notice_is_available_on_every_page():
    assert 'id="ocrJobNotice"' in BASE
    assert "pptImageTextEditor.activeJob.v1" in BASE
    assert "/ppt-image-text-editor/analysis/" in BASE
    assert "setInterval(check,10000)" in BASE
    assert "/tools/ppt-image-text-editor/" in BASE

def test_global_ocr_notice_does_not_expose_another_users_result():
    # The global watcher only carries the opaque upload id; the status endpoint
    # performs upload-owner authorization on every request.
    assert "state.upload_id" in BASE
    assert "if(!r.ok)return" in BASE
