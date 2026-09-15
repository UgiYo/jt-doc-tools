"""這個服務只能用**單一 Web 行程**跑，被開成多 worker 時要講出來（稽核 F11）。

`OPS.md` 早就寫著「不要開成多 worker」，但**沒有任何東西擋著** ——
而症狀（同一件作業被派好幾次、正在跑的作業莫名其妙變成「已中斷」）
看起來完全不像設定問題，管理員只會覺得服務怪怪的。

## 判準怎麼來的

uvicorn 的 worker 是用 `multiprocessing.get_context("spawn").Process` 起的
—— 這是**讀 `uvicorn/_subprocess.py` 確認的**，不是猜的：

    spawn = multiprocessing.get_context("spawn")
    return spawn.Process(target=subprocess_started, kwargs=kwargs)

所以在 worker 裡 `multiprocessing.parent_process()` 不是 `None`。
`WEB_CONCURRENCY` 則是 uvicorn / gunicorn 都認的環境變數。

**只記錄、不阻止**：我們不知道使用者是不是有別的理由這樣跑，
在啟動時直接拒絕服務比問題本身更糟。
"""
from __future__ import annotations

import logging
import multiprocessing
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import single_process as sp   # noqa: E402


def test_a_normal_single_process_is_not_flagged():
    """**先證明它不會亂叫** —— 誤報一次就沒有人會再看這行記錄。"""
    assert multiprocessing.parent_process() is None, "測試自己就跑在主行程"
    assert sp.detect_multi_worker() is None


def test_a_spawned_worker_is_flagged(monkeypatch):
    class _Fake:
        pass
    monkeypatch.setattr(sp.multiprocessing, "parent_process", lambda: _Fake())
    how = sp.detect_multi_worker()
    assert how and "multiprocessing" in how


def test_web_concurrency_is_flagged(monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    how = sp.detect_multi_worker()
    assert how and "WEB_CONCURRENCY" in how


def test_web_concurrency_of_one_is_fine(monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "1")
    assert sp.detect_multi_worker() is None


def test_a_garbage_web_concurrency_does_not_blow_up(monkeypatch):
    """設定寫錯不該讓服務起不來。"""
    monkeypatch.setenv("WEB_CONCURRENCY", "很多")
    assert sp.detect_multi_worker() is None


def test_the_message_says_what_will_go_wrong(caplog):
    """**訊息要說得出後果** —— 只說「不支援」的話，管理員無法把手上的症狀
    跟這件事連起來（本專案「訊息要分得出三種結局」那條的同一個道理）。
    """
    why = sp.why_multi_worker_is_unsupported()
    for word in ("作業", "併行", "已中斷", "OPS.md"):
        assert word in why, f"訊息裡少了「{word}」"


def test_it_logs_at_error_level(monkeypatch, caplog):
    class _Fake:
        pass
    monkeypatch.setattr(sp.multiprocessing, "parent_process", lambda: _Fake())
    with caplog.at_level(logging.ERROR, logger="app.single_process"):
        sp.warn_if_multi_worker()
    assert any(r.levelno >= logging.ERROR for r in caplog.records), \
        "這種事要用 ERROR，INFO 沒有人會看到"
