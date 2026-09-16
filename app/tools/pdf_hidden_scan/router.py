"""Endpoints for PDF 隱藏內容掃描."""
from __future__ import annotations

import uuid
from pathlib import Path

import fitz
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from ...config import settings
from .scan_core import _scan, scan_path


router = APIRouter()



@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "pdf_hidden_scan.html", {"request": request})


@router.post("/scan")
async def scan(request: Request, file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "只支援 PDF")
    data = await file.read()
    if not data:
        raise HTTPException(400, "空的檔案")
    # 副檔名只是**名字**，不代表內容。少了這行，內容不是 PDF 時 PyMuPDF 會在
    # 底下丟例外 → 500 Internal Server Error，使用者看到一句看不懂的英文。
    # 同一支工具的 `/api/*` 入口本來就有這個檢查，網頁介面漏了（v1.14.6 補齊）。
    if data[:4] != b"%PDF":
        raise HTTPException(400, "不是有效的 PDF（缺少 %PDF 標頭）")
    uid = uuid.uuid4().hex
    from ...core import upload_owner as _uo
    _uo.record(uid, request)
    src = settings.temp_dir / f"hid_{uid}_in.pdf"
    src.write_bytes(data)
    try:
        (settings.temp_dir / f"hid_{uid}_name.txt").write_text(
            file.filename or "document.pdf", encoding="utf-8")
    except Exception:
        pass
    import asyncio as _asyncio
    findings = await _asyncio.to_thread(_scan_isolated_or_inline, src)
    totals = {k: len(v) for k, v in findings.items()}
    return {"upload_id": uid, "filename": file.filename,
            "findings": findings, "totals": totals}


def _scan_isolated_or_inline(src) -> dict:
    """優先在**獨立行程**裡掃，跑不起來就退回同一個行程。

    這支工具的用途就是「這份檔案可能有問題，幫我看一下」——**輸入最不可信**。
    MuPDF 在 C 層 segfault 會把**整個 uvicorn 行程**帶走（所有進行中的作業與
    網頁一起沒了）；隔離之後只有這一次請求失敗。

    **隔離是防護不是功能** —— 子行程起不來時要能照舊做完，不可以因為它壞掉
    就整支工具不能用。
    """
    from ...core import pdf_isolate
    if not pdf_isolate.available():
        return scan_path(str(src))
    try:
        return pdf_isolate.run_isolated("hidden_scan", {"src": str(src)},
                                        timeout=120.0)
    except pdf_isolate.IsolatedError:
        raise
    except Exception:                       # 隔離機制本身出問題 → 照舊做
        import logging as _lg
        _lg.getLogger(__name__).warning("隔離掃描起不來，退回同一個行程",
                                        exc_info=True)
        return scan_path(str(src))


def _clean_sync(src, out, strip):
    """Heavy hidden-content cleanup (PyMuPDF), called via asyncio.to_thread."""
    doc = fitz.open(str(src))
    removed = {"js": 0, "embeds": 0, "uri": 0, "launch": 0,
               "hidden_text": 0, "annots": 0, "3d": 0}
    try:
        # Document-level JavaScript: clear Names /JavaScript tree +
        # /OpenAction + each page /AA entries.
        if "js" in strip:
            try:
                cat = doc.pdf_catalog()
                if cat:
                    obj = doc.xref_object(cat, compressed=False) or ""
                    new_obj = obj
                    for key in ("/OpenAction", "/AA", "/JavaScript", "/JS"):
                        while key in new_obj:
                            # naive strip — remove the key/value pair line
                            idx = new_obj.find(key)
                            # find the end of this entry (next newline or >>)
                            end_idx = new_obj.find("\n", idx)
                            if end_idx < 0:
                                end_idx = idx + len(key)
                            new_obj = new_obj[:idx] + new_obj[end_idx:]
                            removed["js"] += 1
                    if new_obj != obj:
                        doc.update_object(cat, new_obj)
            except Exception:
                pass

        if "embeds" in strip:
            try:
                for name in list(doc.embfile_names()):
                    try:
                        doc.embfile_del(name)
                        removed["embeds"] += 1
                    except Exception:
                        pass
            except Exception:
                pass

        # Per-page cleanup for links + annotations
        if any(k in strip for k in ("uri", "launch", "annots", "hidden_text")):
            for pno in range(doc.page_count):
                page = doc[pno]
                # Links: rebuild without URI/Launch ones
                if "uri" in strip or "launch" in strip:
                    try:
                        for link in list(page.get_links() or []):
                            k = link.get("kind")
                            if "uri" in strip and k == fitz.LINK_URI:
                                try: page.delete_link(link); removed["uri"] += 1
                                except Exception: pass
                            elif "launch" in strip and k == fitz.LINK_LAUNCH:
                                try: page.delete_link(link); removed["launch"] += 1
                                except Exception: pass
                    except Exception:
                        pass
                if "annots" in strip:
                    try:
                        for a in list(page.annots() or []):
                            try: page.delete_annot(a); removed["annots"] += 1
                            except Exception: pass
                    except Exception:
                        pass
                if "hidden_text" in strip:
                    # Re-scan and redact each hidden-text bbox
                    try:
                        prect = page.rect
                        td = page.get_text("dict")
                        any_redact = False
                        for block in td.get("blocks", []):
                            if block.get("type") != 0:
                                continue
                            for line in block.get("lines", []):
                                for sp in line.get("spans", []):
                                    if not (sp.get("text") or "").strip():
                                        continue
                                    col = int(sp.get("color", 0) or 0)
                                    bbox = sp.get("bbox", [0, 0, 0, 0])
                                    bx0, by0, bx1, by1 = bbox
                                    bad = False
                                    if col == 0xFFFFFF: bad = True
                                    elif bx1 < 0 or by1 < 0 or bx0 > prect.width or by0 > prect.height: bad = True
                                    elif float(sp.get("size", 0) or 0) < 0.5: bad = True
                                    if bad:
                                        try:
                                            page.add_redact_annot(fitz.Rect(*bbox))
                                            any_redact = True
                                            removed["hidden_text"] += 1
                                        except Exception:
                                            pass
                        if any_redact:
                            try:
                                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
                            except Exception:
                                page.apply_redactions()
                    except Exception:
                        pass
        doc.save(str(out), garbage=4, deflate=True, clean=True)
    finally:
        doc.close()
    return removed


@router.post("/clean")
async def clean(request: Request):
    body = await request.json()
    uid = (body.get("upload_id") or "").strip()
    # 歸屬驗證：沒有這道檢查，B 可以改寫 A 的輸出檔 —— 對去識別化 / 隱藏內容
    # 清除這類工具，「被別人改掉輸出」本身就是要害（A 可能拿著被還原的檔案送出）。
    from ...core import safe_paths as _sp, upload_owner as _uo
    _sp.require_uuid_hex(uid, "upload_id")
    _uo.require(uid, request)
    if not uid:
        raise HTTPException(400, "upload_id required")
    src = settings.temp_dir / f"hid_{uid}_in.pdf"
    if not src.exists():
        raise HTTPException(404, "upload expired")
    strip = set(body.get("strip") or [])
    # Supported keys: js, embeds, uri, launch, hidden_text, annots, 3d
    out = settings.temp_dir / f"hid_{uid}_out.pdf"
    import asyncio as _asyncio
    removed = await _asyncio.to_thread(_clean_sync, src, out, strip)
    return {
        "ok": True, "removed": removed,
        "download_url": f"/tools/pdf-hidden-scan/download/{uid}",
    }


@router.get("/download/{uid}")
async def download(uid: str, request: Request):
    from app.core.safe_paths import require_uuid_hex
    from ...core import upload_owner
    require_uuid_hex(uid, "uid")
    upload_owner.require(uid, request)
    out = settings.temp_dir / f"hid_{uid}_out.pdf"
    if not out.exists():
        raise HTTPException(404, "未產生或已過期")
    stem = "document"
    try:
        n = (settings.temp_dir / f"hid_{uid}_name.txt").read_text(encoding="utf-8").strip()
        if n: stem = Path(n).stem
    except Exception:
        pass
    return FileResponse(str(out), media_type="application/pdf",
                        filename=f"{stem}_cleaned.pdf")


# ---- 對外 API：單次 upload + JSON 回傳掃描結果 ----
@router.post("/api/pdf-hidden-scan", include_in_schema=True)
async def api_pdf_hidden_scan(request: Request, file: UploadFile = File(...)):
    """單次上傳 PDF，回 JSON 包含所有偵測到的隱藏 / 風險內容。"""
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "只支援 PDF")
    data = await file.read()
    if not data or data[:4] != b"%PDF":
        raise HTTPException(400, "不是有效的 PDF")
    uid = uuid.uuid4().hex
    from ...core import upload_owner as _uo
    _uo.record(uid, request)
    src = settings.temp_dir / f"hid_{uid}_in.pdf"
    src.write_bytes(data)
    import asyncio as _asyncio
    # 對外 API 走同一條隔離路徑 —— **兩個入口要一致**，
    # 不然「網頁安全、API 不安全」這種差別不會有人發現。
    findings = await _asyncio.to_thread(_scan_isolated_or_inline, src)
    totals = {k: len(v) for k, v in findings.items()}
    return {"filename": file.filename, "findings": findings, "totals": totals}
