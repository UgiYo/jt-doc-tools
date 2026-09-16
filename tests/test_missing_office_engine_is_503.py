"""缺 Office 引擎要回 **503**，不可以回 500。

500 的意思是「伺服器壞了」—— 使用者會一直重試，監控端也全是假警報。
缺 soffice 是**部署問題**：那台機器少裝東西，訊息要說得出要裝什麼。

本專案早就為此做了 `OfficeUnavailableError` ＋ **一個全域處理器**
（`app/main.py`），但 `doc-diff` 自己 `except Exception` 把它吃掉再包成
`HTTPException(500)` —— **全域處理器根本看不到那個例外**（`markdown-to-doc`
在 v1.14.x 踩過一模一樣的形狀）。

判準是「**真的送一份 Office 檔進去，而且讓 soffice 找不到**，看回傳碼」——
不是掃原始碼有沒有寫 503。
"""
from __future__ import annotations

import io

import pytest


def _docx_bytes() -> bytes:
    """最小的 .docx（真的 zip，才過得了副檔名以外的檢查）。"""
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"><Override PartName="/word/document.xml" '
                   'ContentType="application/vnd.openxmlformats-officedocument.'
                   'wordprocessingml.document.main+xml"/></Types>')
        z.writestr("word/document.xml",
                   '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats'
                   '.org/wordprocessingml/2006/main"><w:body/></w:document>')
    return buf.getvalue()


@pytest.mark.parametrize("endpoint", ["/tools/doc-diff/compare"])
def test_missing_office_engine_returns_503(client, monkeypatch, endpoint):
    from app.core import office_convert

    def _no_soffice() -> None:
        return None

    monkeypatch.setattr(office_convert, "find_soffice", _no_soffice)
    doc = _docx_bytes()
    r = client.post(endpoint, files={
        "file_a": ("a.docx", doc, "application/vnd.openxmlformats-officedocument."
                                  "wordprocessingml.document"),
        "file_b": ("b.docx", doc, "application/vnd.openxmlformats-officedocument."
                                  "wordprocessingml.document"),
    })
    assert r.status_code == 503, (
        f"缺 Office 引擎時回了 {r.status_code}，應該是 503（部署問題不是伺服器壞掉）"
        f"：{r.text[:200]}")
    body = r.text
    assert ("OxOffice" in body or "LibreOffice" in body or "soffice" in body), (
        "503 的訊息要說得出缺什麼、怎麼裝 —— 只說『服務不可用』等於沒說："
        f"{body[:200]}")
