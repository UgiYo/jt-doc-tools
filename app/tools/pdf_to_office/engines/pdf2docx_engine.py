"""pdf2docx engine wrapper — 鎖死 0.5.13。

pdf2docx 上游 (Artifex) 2026 已停止維護，授權轉 MIT。我們鎖版 + 必要時 fork。
此模組職責純粹：餵 PDF → 吐 docx，過程中的 log 收進來，不做後處理（那是 postprocess
的事）。
"""
from __future__ import annotations

import contextlib
import logging
from pathlib import Path

from pdf2docx import Converter

log = logging.getLogger(__name__)


#: pdf2docx 在逐頁迴圈裡記的那一行（`parse_pages` 與 `make_docx` 都是這一句）。
#: 它用的是**根 logger**，所以掛一個暫時的 handler 就收得到 —— 不必碰它的內部。
#: **這個字串就是身分**：上游改掉的話我們只會少掉逐頁的顆粒度（退回階段進度），
#: 不會壞掉；`tests/test_pdf_to_office_progress.py` 會在它漂掉時先紅。
_PAGE_LOG_FMT = "(%d/%d) Page %d"


class _PageProgress(logging.Handler):
    """把 pdf2docx 的逐頁 log 轉成我們的進度回報。"""

    def __init__(self, cb, lo: float, hi: float, label: str):
        super().__init__(level=logging.INFO)
        self._cb, self._lo, self._hi, self._label = cb, lo, hi, label

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
        if record.msg != _PAGE_LOG_FMT:
            return
        try:
            i, n, _pid = record.args           # type: ignore[misc]
            frac = self._lo + (self._hi - self._lo) * (int(i) / max(1, int(n)))
        except Exception:                      # noqa: BLE001
            return                             # log 的格式變了就不報，不要炸
        _say(self._cb, f"{self._label} {i}/{n} 頁", round(frac, 3))


def _say(cb, msg: str, frac: float) -> None:
    """回報一次進度。**進度壞掉不可以讓轉檔失敗** —— 它是附屬品，不是產出。"""
    if cb is None:
        return
    try:
        cb(msg, frac)
    except Exception:                          # noqa: BLE001
        log.debug("progress callback raised", exc_info=True)


@contextlib.contextmanager
def _page_progress(cb, lo: float, hi: float, label: str):
    if cb is None:
        yield
        return
    h = _PageProgress(cb, lo, hi, label)
    root = logging.getLogger()
    root.addHandler(h)
    # pdf2docx 用 `logging.info(...)`（根 logger）—— 根的層級若高於 INFO 就收不到。
    prev = root.level
    if prev > logging.INFO:
        root.setLevel(logging.INFO)
    try:
        yield
    finally:
        root.removeHandler(h)
        if prev > logging.INFO:
            root.setLevel(prev)


def convert_via_pdf2docx(
    pdf_path: Path,
    docx_path: Path,
    start: int = 0,
    end: int | None = None,
    pages: list[int] | None = None,
    progress_cb=None,
) -> dict:
    """轉 PDF → docx。

    Args:
        pdf_path: 來源 PDF
        docx_path: 目標 docx 路徑
        start: 起始頁 (0-based, inclusive)
        end: 結束頁 (0-based, exclusive)，None = 到最後
        pages: 指定頁清單（與 start/end 互斥）

    Returns:
        {"ok": bool, "pages_converted": int, "error": str}

    Raises:
        FileNotFoundError: pdf_path 不存在
    """
    pdf_path = Path(pdf_path)
    docx_path = Path(docx_path)
    if not pdf_path.exists():
        raise FileNotFoundError(str(pdf_path))
    docx_path.parent.mkdir(parents=True, exist_ok=True)

    cv = Converter(str(pdf_path))
    try:
        kwargs: dict = {}
        if pages is not None:
            kwargs["pages"] = pages
        else:
            kwargs["start"] = start
            if end is not None:
                kwargs["end"] = end
        # **把 `convert()` 拆成它自己的四步**，才報得出真的進度 ——
        # `convert()` 是一個從頭跑到尾的呼叫，中間什麼都看不到，而這支工具
        # 動輒數分鐘（使用者只會看到進度條不動）。四步是 pdf2docx 自己的
        # 公開方法，等價於 `convert()` 裡那一行
        # `self.parse(...).make_docx(...)`。
        # **設定要照 `convert()` 的做法補齊**：它是
        # `settings = self.default_settings; settings.update(kwargs)`，
        # 再把 `**settings` 傳給每一步。只傳 start/end/pages 的話，
        # 後面那幾步會缺鍵（實測 `KeyError: 'ocr'`）。
        settings = dict(cv.default_settings)
        _say(progress_cb, "讀取 PDF…", 0.05)
        cv.load_pages(start=kwargs.get("start", 0), end=kwargs.get("end"),
                      pages=kwargs.get("pages"))
        _say(progress_cb, "分析整份版面…", 0.12)
        cv.parse_document(**settings)
        with _page_progress(progress_cb, 0.15, 0.70, "分析版面"):
            cv.parse_pages(**settings)
        with _page_progress(progress_cb, 0.70, 0.98, "產生文件"):
            cv.make_docx(str(docx_path), **settings)
        # 估算實際轉換頁數（pdf2docx 沒提供 attr 直接拿，從 fitz doc 拿）
        if pages is not None:
            pages_done = len(pages)
        else:
            try:
                total = cv.fitz_doc.page_count
            except Exception:
                total = 0
            pages_done = max(0, (end or total) - start)
        return {"ok": True, "pages_converted": pages_done, "error": ""}
    except Exception as e:
        log.exception("pdf2docx convert failed")
        return {"ok": False, "pages_converted": 0, "error": str(e)}
    finally:
        try:
            cv.close()
        except Exception:
            pass
