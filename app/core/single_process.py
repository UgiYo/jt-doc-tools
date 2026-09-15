"""這個服務**只能用單一 Web 行程跑**（稽核 F11）。

作業佇列、併行號誌、記憶體准入全部活在**行程的記憶體裡**，而
`job_store.init()` 啟動時會把資料庫裡狀態還是 running 的作業標成 interrupted。
所以開成多 worker 時：

* 每個 worker 各有一份佇列 —— 同一件事會被派好幾次。
* 併行上限與記憶體准入各算各的 —— 設 2 實際上是 `2 × worker 數`。
* **後起來的 worker 會把前一個正在跑的作業標成「已中斷」**。

`OPS.md` 早就寫著「不要開成多 worker」，但**沒有任何東西擋著**，
而症狀（作業重複、莫名其妙變成已中斷）看起來完全不像設定問題。

## 怎麼認出來

uvicorn 的 worker 是用 `multiprocessing.get_context("spawn").Process` 起的
（讀 `uvicorn/_subprocess.py` 確認過，不是猜的），所以在 worker 裡
`multiprocessing.parent_process()` 不是 `None`；正常的單一行程是 `None`。

`WEB_CONCURRENCY` 是 uvicorn / gunicorn 都認的環境變數，順便一起看。

**只記錄、不阻止**：我們不知道使用者是不是有別的理由這樣跑，而在啟動時
直接拒絕服務比問題本身更糟。
"""
from __future__ import annotations

import logging
import multiprocessing
import os

logger = logging.getLogger("app.single_process")

#: 講清楚「會發生什麼事」，不要只說「不支援」——
#: 管理員要據此判斷手上的症狀是不是這個造成的。
_WHY = ("作業佇列與記憶體准入都在行程的記憶體裡：多 worker 會讓同一件作業"
        "被派好幾次、併行上限變成設定值的好幾倍，而且後起來的 worker 會把"
        "前一個正在跑的作業標成「已中斷」。請改成單一行程（服務預設就是），"
        "詳見 OPS.md 的「部署邊界」。")


def why_multi_worker_is_unsupported() -> str:
    return _WHY


def detect_multi_worker() -> str | None:
    """回傳「怎麼看出來的」，沒問題時回 None。"""
    if multiprocessing.parent_process() is not None:
        return "這個行程是 multiprocessing 的子行程（uvicorn --workers 會這樣起）"
    n = os.environ.get("WEB_CONCURRENCY")
    try:
        if n is not None and int(n) > 1:
            return f"環境變數 WEB_CONCURRENCY={n}"
    except ValueError:
        pass
    return None


def warn_if_multi_worker() -> str | None:
    how = detect_multi_worker()
    if how:
        logger.error("這個服務只支援單一 Web 行程 —— %s。%s", how, _WHY)
    return how
