"""`pdf2docx` 那條路要回報**逐頁**進度。

這支工具動輒數分鐘，而 `Converter.convert()` 是一個從頭跑到尾的呼叫 ——
中間什麼都看不到，使用者只會看到進度條不動（以為當掉了）。

做法是把 `convert()` 拆成它自己的四步（`load_pages` / `parse_document` /
`parse_pages` / `make_docx`，就是 `convert()` 裡那一行在做的事），
再從 pdf2docx **自己記的逐頁 log** 取顆粒度 —— 不碰它的內部結構。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _sample_pdf(dst: Path, pages: int = 4) -> Path:
    import fitz

    d = fitz.open()
    for i in range(pages):
        pg = d.new_page(width=595, height=842)
        pg.insert_text((72, 100 + i * 20), f"Progress test page {i + 1}", fontsize=14)
    d.save(str(dst))
    d.close()
    return dst


def test_the_upstream_page_log_format_has_not_drifted():
    """我們靠 pdf2docx 的那一行 log 取逐頁顆粒度 —— **字串就是身分**。

    上游改掉的話我們只會**安靜地退回階段進度**（少掉逐頁），不會壞掉 ——
    正因為如此才要有這條：不然沒有人會發現進度條又變回「兩格」。
    """
    import inspect

    from pdf2docx import Converter

    from app.tools.pdf_to_office.engines.pdf2docx_engine import _PAGE_LOG_FMT

    for meth in (Converter.parse_pages, Converter.make_docx):
        src = inspect.getsource(meth)
        assert _PAGE_LOG_FMT in src, (
            f"pdf2docx 的 {meth.__name__} 不再記 {_PAGE_LOG_FMT!r} —— "
            "逐頁進度會安靜地退回階段進度，要改 `_PageProgress` 的判準")


def test_progress_is_reported_page_by_page():
    from app.tools.pdf_to_office.engines.pdf2docx_engine import convert_via_pdf2docx

    tmp = Path(tempfile.mkdtemp())
    src = _sample_pdf(tmp / "in.pdf", pages=4)
    seen: list[tuple[str, float]] = []
    r = convert_via_pdf2docx(src, tmp / "out.docx",
                             progress_cb=lambda m, f: seen.append((m, f)))
    assert r["ok"], r.get("error")
    assert (tmp / "out.docx").exists()

    # **判準是「有沒有逐頁」**，不是「有沒有回報」—— 只報開頭與結尾兩格
    # 就是原本那個「進度條不動」的樣子。
    per_page = [s for s in seen if "/4 頁" in s[0]]
    assert len(per_page) >= 6, f"逐頁回報只有 {len(per_page)} 次：{seen}"

    fracs = [f for _m, f in seen]
    assert fracs == sorted(fracs), f"進度倒退了：{fracs}"
    assert 0 < fracs[0] < 0.2 and fracs[-1] >= 0.9, fracs


def test_a_broken_progress_callback_never_breaks_the_conversion():
    """**進度壞掉不可以讓轉檔失敗** —— 那是附屬品，不是產出。"""
    from app.tools.pdf_to_office.engines.pdf2docx_engine import convert_via_pdf2docx

    tmp = Path(tempfile.mkdtemp())
    src = _sample_pdf(tmp / "in.pdf", pages=2)

    def boom(_m, _f):
        raise RuntimeError("進度回報自己炸了")

    r = convert_via_pdf2docx(src, tmp / "out.docx", progress_cb=boom)
    assert r["ok"], r.get("error")
    assert (tmp / "out.docx").exists()


def test_it_still_works_without_a_callback():
    """沒有給 `progress_cb` 時行為要跟以前完全一樣。"""
    from app.tools.pdf_to_office.engines.pdf2docx_engine import convert_via_pdf2docx

    tmp = Path(tempfile.mkdtemp())
    src = _sample_pdf(tmp / "in.pdf", pages=2)
    r = convert_via_pdf2docx(src, tmp / "out.docx")
    assert r["ok"] and r["pages_converted"] == 2
