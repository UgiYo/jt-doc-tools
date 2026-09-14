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

def test_queued_cancel_removes_job_immediately_from_queue():
    assert 'job["status"]=="queued"' in ROUTER
    assert 'status="cancelled"' in ROUTER
    assert "task.cancel()" in ROUTER
    assert "_analysis_tasks" in ROUTER
    assert 'not j.get("cancel_requested")' in ROUTER
    assert "已立即取消排隊中的辨識" in TEMPLATE

def test_editable_conversion_is_persisted_and_resumable():
    assert '"editable_job"' in ROUTER
    assert "_persist_convert_job" in ROUTER
    assert "_restore_convert_job" in ROUTER
    assert "editableJobPanel" in TEMPLATE
    assert "pptImageTextEditor.editableJob.v1" in TEMPLATE
    assert "已送出背景處理，可離開此頁" in TEMPLATE


def test_offline_easyocr_docker_build_preloads_models():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    override = (ROOT / "docker-compose.easyocr-offline.yml").read_text(encoding="utf-8")
    assert "ARG PRELOAD_EASYOCR_MODELS=0" in dockerfile
    assert "easyocr.Reader(['ch_tra','en']" in dockerfile
    assert "download_enabled=False" in dockerfile
    assert 'WITH_EASYOCR: "1"' in override
    assert 'PRELOAD_EASYOCR_MODELS: "1"' in override
