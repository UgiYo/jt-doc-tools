from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response

from .pptx_io import export_pptx, import_pptx
from .schema import DEFAULT_DECK, normalize_deck

router = APIRouter(); MAX_PPTX = 80 * 1024 * 1024

@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return request.app.state.templates.TemplateResponse(request, "editable_slides.html", {"request": request})

@router.get("/default")
async def default_deck(): return DEFAULT_DECK

@router.post("/import")
async def import_file(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".pptx"): raise HTTPException(400, "目前僅支援 .pptx")
    raw = await file.read()
    if not raw or len(raw) > MAX_PPTX: raise HTTPException(413, "檔案為空或超過 80 MB")
    try: return import_pptx(raw)
    except Exception as exc: raise HTTPException(400, f"PPTX 解析失敗：{exc}") from exc

@router.post("/export")
async def export(deck: dict):
    try: raw = export_pptx(normalize_deck(deck))
    except Exception as exc: raise HTTPException(400, f"簡報匯出失敗：{exc}") from exc
    return Response(raw, media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    headers={"Content-Disposition": 'attachment; filename="editable-presentation.pptx"'})
