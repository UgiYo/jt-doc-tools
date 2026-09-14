from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = (ROOT / "app/tools/ppt_image_text_editor/router.py").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "app/tools/ppt_image_text_editor/templates/ppt_image_text_editor.html").read_text(encoding="utf-8")

def test_ocr_runs_outside_fastapi_event_loop():
    assert "_OCR_LIMIT=asyncio.Semaphore(1)" in ROUTER
    assert "await asyncio.to_thread(_oe.recognize_image" in ROUTER
    assert '@router.post("/analysis/{uid}")' in ROUTER
    assert '@router.get("/analysis/{uid}")' in ROUTER

def test_ocr_ui_polls_progress_and_prevents_duplicate_clicks():
    assert "button.disabled=true" in TEMPLATE
    assert "job.queue_position" in TEMPLATE
    assert "job.completed" in TEMPLATE
    assert "/ppt-image-text-editor/analysis/" in TEMPLATE

def test_every_analysis_endpoint_checks_upload_owner():
    start = ROUTER.index('async def start_analysis')
    status = ROUTER.index('async def analysis_status')
    legacy = ROUTER.index('async def images')
    assert "_uo.require(uid,request)" in ROUTER[start:status]
    assert "_uo.require(uid,request)" in ROUTER[status:legacy]

def test_ocr_job_can_resume_and_cancel_safely():
    assert '@router.post("/analysis/{uid}/cancel")' in ROUTER
    assert 'job.get("cancel_requested")' in ROUTER
    assert "localStorage.setItem(JOB_KEY" in TEMPLATE
    assert "resumeSavedAnalysis();" in TEMPLATE
    assert "fileFingerprint(file)" in TEMPLATE
    assert "/cancel" in TEMPLATE
