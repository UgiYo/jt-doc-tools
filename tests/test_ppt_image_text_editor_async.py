from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = (ROOT / "app/tools/ppt_image_text_editor/router.py").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "app/tools/ppt_image_text_editor/templates/ppt_image_text_editor.html").read_text(encoding="utf-8")

def test_ocr_runs_outside_fastapi_event_loop():
    assert "job_manager.submit" in ROUTER
    assert "_PPT_HEAVY_LIMIT=threading.Semaphore(1)" in ROUTER
    assert "_oe.recognize_image" in ROUTER
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
    assert "job_manager.cancel(jid)" in ROUTER
    assert "if job.cancelled:return" in ROUTER
    assert "localStorage.setItem(JOB_KEY" in TEMPLATE
    assert "resumeSavedAnalysis();" in TEMPLATE
    assert "fileFingerprint(file)" in TEMPLATE
    assert "/cancel" in TEMPLATE

def test_queued_cancel_removes_job_immediately_from_queue():
    assert "job_manager.cancel(jid)" in ROUTER
    assert '"pending":"queued"' in ROUTER
    assert "已立即取消排隊中的辨識" in TEMPLATE

def test_image_output_is_persisted_and_resumable():
    assert '"output_job"' in ROUTER
    assert '"operation":"image-pptx"' in ROUTER
    assert "job.result_path=_output_path(uid)" in ROUTER
    assert "_apply_edits(read_media(raw,path)" in ROUTER
    assert "editableJobPanel" in TEMPLATE
    assert "pptImageTextEditor.outputJob.v2" in TEMPLATE
    assert "已送出背景處理，可離開此頁" in TEMPLATE
    assert "輸出文字不是 PowerPoint 文字方塊" in TEMPLATE
    assert "/ppt-image-text-editor/output/" in TEMPLATE


def test_jobs_are_visible_in_my_jobs_and_link_back_to_the_editor():
    my_jobs = (ROOT / "app/web/templates/my_jobs.html").read_text(encoding="utf-8")
    assert 'job_manager.submit("ppt-image-text-editor"' in ROUTER
    assert '"view_url":f"/tools/ppt-image-text-editor/?upload={uid}"' in ROUTER
    assert "new URLSearchParams(location.search).get('upload')" in TEMPLATE
    assert "j.status === 'done' && !j.view_url" in my_jobs


def test_offline_easyocr_docker_build_preloads_models():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    override = (ROOT / "docker-compose.easyocr-offline.yml").read_text(encoding="utf-8")
    assert "ARG PRELOAD_EASYOCR_MODELS=0" in dockerfile
    assert "easyocr.Reader(['ch_tra','en']" in dockerfile
    assert "download_enabled=False" in dockerfile
    assert 'WITH_EASYOCR: "1"' in override
    assert 'PRELOAD_EASYOCR_MODELS: "1"' in override


def test_editable_job_record_can_be_cleared_in_browser():
    assert 'id="clearEditableJob"' in TEMPLATE
    assert "localStorage.removeItem(CONVERT_KEY)" in TEMPLATE
    assert "++editablePollToken" in TEMPLATE
    assert "panel.hidden=true" in TEMPLATE
    assert "download.removeAttribute('href')" in TEMPLATE
