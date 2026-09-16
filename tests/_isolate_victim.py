"""**故意崩潰 / 卡死**的受試模組 —— 只給 `test_pdf_isolate.py` 用。

真的去弄一份會讓 MuPDF 在 C 層 segfault 的 PDF 既不可靠也不好維護
（不同版本的 MuPDF 會修掉），所以改成**直接送自己一個 SIGSEGV** ——
要驗的是「子行程被訊號砍掉時主行程活不活得下來」，崩潰怎麼來的不重要。
"""
from __future__ import annotations

import os
import signal
import time


def crash() -> None:
    os.kill(os.getpid(), signal.SIGSEGV)


def sleep_forever() -> None:
    while True:
        time.sleep(1)
