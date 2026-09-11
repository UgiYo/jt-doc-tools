from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response

from ...config import settings
from ...core import upload_owner as _uo
from ...core import ocr_engine as _oe
from .image_edit import edit_text, to_png
from .pptx_core import list_slide_images, read_media, replace_media

router = APIRouter()
_ID_RE = re.compile(r"^[a-f0-9]{32}$")


def _work_dir() -> Path:
    p = settings.temp_dir / "ppt_image_text_editor"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _src(uid: str) -> Path:
    return _work_dir() / f"{uid}.pptx"


def _manifest(uid: str) -> Path:
    return _work_dir() / f"{uid}.json"


def _safe_id(uid: str) -> str:
    if not _ID_RE.fullmatch(uid or ""):
        raise HTTPException(400, "invalid upload id")
    return uid


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return request.app.state.templates.TemplateResponse(request, "ppt_image_text_editor.html", {"request": request})


@router.post("/upload")
async def upload(request: Request, file: UploadFile = File(...)):
    name = file.filename or "input.pptx"
    if not name.lower().endswith(".pptx"):
        raise HTTPException(400, "目前僅支援 .pptx")
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "空檔案")
    if len(raw) > 200 * 1024 * 1024:
        raise HTTPException(413, "PPTX 超過 200 MB 上限")
    try:
        refs = list_slide_images(raw)
    except Exception as exc:
        raise HTTPException(400, f"PPTX 解析失敗：{exc}") from exc
    uid = uuid.uuid4().hex
    _src(uid).write_bytes(raw)
    _manifest(uid).write_text(json.dumps({"filename": name}, ensure_ascii=False), encoding="utf-8")
    _uo.record(uid, request)
    unique_media = sorted({r.media_path for r in refs})
    return {"upload_id": uid, "filename": name, "slides_with_images": len({r.slide for r in refs}),
            "image_refs": len(refs), "unique_images": len(unique_media)}


@router.get("/images/{uid}")
async def images(uid: str, request: Request, langs: str = "chi_tra+eng"):
    uid = _safe_id(uid); _uo.require(uid, request)
    raw = _src(uid).read_bytes()
    refs = list_slide_images(raw)
    grouped: dict[str, dict] = {}
    for ref in refs:
        item = grouped.setdefault(ref.media_path, {"media_path": ref.media_path, "slides": [], "rel_ids": []})
        item["slides"].append(ref.slide); item["rel_ids"].append(ref.rel_id)
    result = []
    for idx, (media_path, item) in enumerate(grouped.items()):
        media = read_media(raw, media_path)
        try:
            png, (w, h) = to_png(media)
            words, engine = _oe.recognize_image(png, langs, preprocess=True,
                                                allow_local_easyocr=_oe.local_easyocr_safe())
        except Exception as exc:
            result.append({**item, "index": idx, "width": 0, "height": 0, "words": [], "error": str(exc)})
            continue
        result.append({**item, "index": idx, "width": w, "height": h, "engine": engine,
                       "preview_url": f"/tools/ppt-image-text-editor/preview/{uid}/{idx}", "words": words})
    cache = {str(i): x[0] for i, x in enumerate(grouped.items())}
    data = json.loads(_manifest(uid).read_text(encoding="utf-8"))
    data["media_map"] = cache
    _manifest(uid).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return {"upload_id": uid, "images": result}


@router.get("/preview/{uid}/{index}")
async def preview(uid: str, index: int, request: Request):
    uid = _safe_id(uid); _uo.require(uid, request)
    manifest = json.loads(_manifest(uid).read_text(encoding="utf-8"))
    media_path = (manifest.get("media_map") or {}).get(str(index))
    if not media_path:
        raise HTTPException(404, "image not analyzed")
    png, _ = to_png(read_media(_src(uid).read_bytes(), media_path))
    return Response(png, media_type="image/png")


@router.post("/export/{uid}")
async def export(uid: str, request: Request, edits_json: str = Form(...)):
    uid = _safe_id(uid); _uo.require(uid, request)
    try:
        edits = json.loads(edits_json)
        if not isinstance(edits, list):
            raise ValueError
    except Exception:
        raise HTTPException(400, "edits_json 格式錯誤")
    manifest = json.loads(_manifest(uid).read_text(encoding="utf-8"))
    media_map = manifest.get("media_map") or {}
    raw = _src(uid).read_bytes()
    by_media: dict[str, list[dict]] = {}
    for e in edits:
        media_path = media_map.get(str(e.get("image_index")))
        if not media_path:
            raise HTTPException(400, "找不到指定圖片；請先執行 OCR 分析")
        by_media.setdefault(media_path, []).append(e)
    replacements = {}
    for media_path, media_edits in by_media.items():
        img_bytes, _ = to_png(read_media(raw, media_path))
        for e in sorted(media_edits, key=lambda x: int(x.get("top", 0)), reverse=True):
            left, top = int(e["left"]), int(e["top"])
            width, height = int(e["width"]), int(e["height"])
            img_bytes = edit_text(img_bytes, box=(left, top, left + width, top + height),
                                  new_text=str(e.get("new_text", "")))
        replacements[media_path] = img_bytes
    out = replace_media(raw, replacements)
    out_path = _work_dir() / f"{uid}_edited.pptx"
    out_path.write_bytes(out)
    base = Path(manifest.get("filename") or "edited.pptx").stem
    return FileResponse(str(out_path), media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        filename=f"{base}_edited.pptx")
