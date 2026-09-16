"""`jtdt-reform` 引擎要**逐頁**回報進度。

## 由來

`pdf-to-office` 的三顆引擎裡，`pdf2docx-refine` 與 `jtdt-layout` 早就逐頁
回報了，**只有 `jtdt-reform` 從頭到尾只有兩個點**（開始、結束）。
大檔動輒數分鐘，中間畫面完全不動 —— 而「什麼都沒發生」正是本專案記過的
最難診斷的症狀（使用者會以為當掉）。

我自己在 CLAUDE.md 上還寫過「三條引擎都接上了」，**去查才發現只有兩顆**
（`engines/jtdt_reform/` 裡一個 `progress` 都沒有）。

## 判準

* **真的跑一次轉檔**，收到的回報要**多於頁數**（逐頁才可能這麼多），
  而且 fraction 要單調遞增、落在 0~1。
* **回報函式自己丟例外時，轉檔仍然要成功** —— 進度是附屬品不是產出
  （`pdf2docx` 那條記過同一件事）。
"""
from __future__ import annotations

import pathlib
import shutil
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "temp_pdfs" / "migrate_guide.pdf"


def _sample() -> pathlib.Path:
    if SRC.exists():
        return SRC
    import fitz
    p = ROOT / "temp" / "reform_progress.pdf"
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        d = fitz.open()
        for i in range(6):
            d.new_page(width=595, height=842).insert_text(
                (60, 90), f"page {i + 1}", fontsize=13, fontname="helv")
        d.save(str(p)); d.close()
    return p


def _convert(cb):
    from app.tools.pdf_to_office.service import convert_pdf_to_office
    work = pathlib.Path(tempfile.mkdtemp(prefix="reformprog-"))
    try:
        return convert_pdf_to_office(_sample(), work, output_format="odt",
                                     engine="jtdt-reform", progress_cb=cb)
    finally:
        shutil.rmtree(work, ignore_errors=True)


@pytest.mark.slow
def test_progress_is_reported_page_by_page():
    seen: list[tuple[str, float]] = []
    res = _convert(lambda m, f: seen.append((m, f)))
    assert res.ok, getattr(res, "error", None)
    import fitz
    with fitz.open(str(_sample())) as d:
        pages = d.page_count
    assert len(seen) > pages, (
        f"只回報了 {len(seen)} 次（{pages} 頁）—— 看起來還是只有階段進度，"
        "不是逐頁")
    fracs = [f for _m, f in seen]
    assert all(0.0 <= f <= 1.0 for f in fracs), fracs[:5]
    assert fracs == sorted(fracs), "進度往回跳了"
    assert any("頁" in m for m, _f in seen), "回報的訊息裡沒有頁碼"


@pytest.mark.slow
def test_a_failing_callback_does_not_break_the_conversion():
    """**進度壞掉不可以讓轉檔失敗** —— 它是附屬品不是產出。"""
    def boom(_m, _f):
        raise RuntimeError("進度回報自己爆了")
    res = _convert(boom)
    assert res.ok, (
        "回報函式丟例外就把轉檔弄壞了 —— 進度是附屬品，要包起來")
