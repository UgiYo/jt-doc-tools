"""隱藏內容掃描的核心 —— **只 import `fitz`**。

## 為什麼要單獨一支

這段會在**獨立子行程**裡跑（`core.pdf_isolate`，外部稽核 F04）。
子行程的啟動成本落在每一次請求上，所以它 import 什麼很要緊 —— 實測：

| import | 時間 |
|---|---:|
| 空的 python | 90 ms |
| `fitz` | 303 ms |
| **這支工具的 `router`（FastAPI ＋ 設定鏈）** | **1375 ms** |

原本子行程 import 的是 `router`，於是每次隔離呼叫多付 **1.6 秒** ——
使用者盯著看的畫面上那是很久。把掃描本體抽出來之後只剩約 0.4 秒。

**規劃時量的是「spawn ＋ import PyMuPDF ＋ 開檔 = 385 ms」，
沒有把「我們自己的 import 鏈」算進去** —— 實際做才看得到差在哪裡。
"""
from __future__ import annotations

import fitz


def _scan(doc: "fitz.Document") -> dict:
    """Walk the document and collect every class of hidden / risky
    content we support removing. Returns {category: [findings]}."""
    js_events: list[dict] = []
    embeds: list[dict] = []
    uri_links: list[dict] = []
    launch_actions: list[dict] = []
    hidden_text: list[dict] = []
    annot_details: list[dict] = []
    threed_multi: list[dict] = []

    # 1) Document-level JS (/OpenAction, /AA, /Names/JavaScript)
    try:
        cat = doc.pdf_catalog()
        cat_obj = doc.xref_object(cat, compressed=False) if cat else ""
        if "/JavaScript" in cat_obj or "/JS" in cat_obj:
            js_events.append({"scope": "document", "kind": "catalog-js",
                              "detail": "Catalog 內含 JavaScript 或 Names tree /JavaScript"})
        if "/OpenAction" in cat_obj:
            js_events.append({"scope": "document", "kind": "open-action",
                              "detail": "/OpenAction（開檔即執行動作）"})
    except Exception:
        pass

    # 2) Embedded files
    try:
        for name in doc.embfile_names():
            try:
                meta = doc.embfile_info(name) or {}
                embeds.append({
                    "name": name,
                    "size": meta.get("size"),
                    "subtype": meta.get("subject") or meta.get("description") or "",
                })
            except Exception:
                embeds.append({"name": name})
    except Exception:
        pass

    for pno in range(doc.page_count):
        page = doc[pno]
        # 3) Link actions — URI or Launch
        try:
            for link in page.get_links() or []:
                kind = link.get("kind")
                # PyMuPDF: link["kind"] — 1=GOTO, 2=GOTOR, 3=LAUNCH, 4=URI, ...
                if kind == fitz.LINK_LAUNCH:
                    launch_actions.append({"page": pno + 1,
                                           "target": link.get("file", "")})
                elif kind == fitz.LINK_URI:
                    uri_links.append({"page": pno + 1,
                                      "uri": link.get("uri", "")})
        except Exception:
            pass

        # 4) Annotations with triggers
        try:
            for annot in (page.annots() or []):
                t = annot.type
                info = annot.info or {}
                annot_details.append({
                    "page": pno + 1,
                    "type": t[1] if isinstance(t, (list, tuple)) else str(t),
                    "author": info.get("title", ""),
                    "content": (info.get("content") or "")[:80],
                })
        except Exception:
            pass

        # 5) White-on-white / outside-page text
        try:
            prect = page.rect
            td = page.get_text("dict")
            for block in td.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for sp in line.get("spans", []):
                        txt = (sp.get("text") or "").strip()
                        if not txt:
                            continue
                        col = int(sp.get("color", 0) or 0)
                        # White text (0xFFFFFF)
                        if col == 0xFFFFFF:
                            hidden_text.append({
                                "page": pno + 1, "reason": "white",
                                "text": txt[:60]
                            })
                            continue
                        bbox = sp.get("bbox", [0, 0, 0, 0])
                        bx0, by0, bx1, by1 = bbox
                        # Entirely outside the page (common smuggling trick)
                        if bx1 < 0 or by1 < 0 or bx0 > prect.width or by0 > prect.height:
                            hidden_text.append({
                                "page": pno + 1, "reason": "outside-page",
                                "text": txt[:60]
                            })
                            continue
                        # Font size zero or near-zero
                        if float(sp.get("size", 0) or 0) < 0.5:
                            hidden_text.append({
                                "page": pno + 1, "reason": "zero-size",
                                "text": txt[:60]
                            })
        except Exception:
            pass

    # 6) 3D / RichMedia — look for /Type /3D or /RichMedia in page contents
    try:
        for pno in range(doc.page_count):
            try:
                page_xref = doc.page_xref(pno)
                obj = doc.xref_object(page_xref, compressed=False) or ""
                if "/3D" in obj or "/RichMedia" in obj or "/Movie" in obj:
                    threed_multi.append({"page": pno + 1})
            except Exception:
                continue
    except Exception:
        pass

    return {
        "js_events": js_events,
        "embeds": embeds,
        "uri_links": uri_links,
        "launch_actions": launch_actions,
        "hidden_text": hidden_text,
        "annot_details": annot_details,
        "threed_multi": threed_multi,
    }


def scan_path(src: str) -> dict:
    """開檔 ＋ 掃描 —— **隔離子行程的進入點**。

    只收路徑、只回可以 JSON 序列化的東西，因為它要跨行程傳。
    """
    with fitz.open(str(src)) as doc:
        return _scan(doc)
