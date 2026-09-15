"""記憶體准入：**已派送但還沒反映在 RSS 上的量要先記帳**（稽核 F06）。

`_dispatch()` 在同一輪迴圈裡可能連派好幾件。每一件都讀**當下**的可用記憶體，
而前一件此時**還沒配到記憶體** —— 於是第二件看到的是過時的數字，兩件都被
放行。預設併行 2 時最多多算一件（800 MB）；管理員調到 4~6 就是 2.4~4 GB，
正好是 OOM 的量。

## 不動的部分

「**沒有任何工作在跑時不做記憶體判斷**」是刻意的取捨（不然記憶體一直不足時
佇列永遠解不開），程式裡本來就有註解。稽核把它判成 P1，這裡維持原樣，
只補上它真正缺的那一半 —— 預留帳。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import concurrency_settings as cs        # noqa: E402
from app.core import job_manager as jm                 # noqa: E402


@pytest.fixture
def mem(monkeypatch):
    """把可用記憶體換成我們說了算的數字。"""
    box = {"avail": 4000}
    monkeypatch.setattr(cs, "available_mb", lambda: box["avail"])
    monkeypatch.setattr(cs, "reserve_mb", lambda: 768)
    return box


def test_a_second_office_job_waits_when_the_first_one_has_not_settled(mem):
    """**這條就是 F06。**

    數字是**推出來的**，不是挑出來的：office 一件估 800、系統保留 768。

    * 沒有預留帳：`可用 - 800 >= 768` → 可用 ≥ 1568 就放行。
    * 有預留帳：  `可用 - 800 - 800 >= 768` → 要 ≥ 2368 才放行。

    取 **2000** 落在中間 —— 舊做法放行（就是那個 bug），新做法排隊。
    """
    mem["avail"] = 2000
    m = jm.JobManager(workers=4)
    with m._lock:
        m._reserve("a", "office-to-pdf")
        reserved = m._reserved_mb()
    assert reserved == cs.estimated_job_mb("office-to-pdf")
    assert jm._ram_allows_start("office-to-pdf", 0) is True, "沒記帳時本來就會放行"
    assert jm._ram_allows_start("office-to-pdf", reserved) is False, \
        "記了帳之後第二件必須排隊"


def test_the_reservation_expires_so_it_is_not_counted_twice(mem, monkeypatch):
    """過了沉澱時間就不算 —— 不然會跟真實的 RSS **重複計算**，永遠偏保守。"""
    m = jm.JobManager(workers=4)
    with m._lock:
        m._reserve("a", "office-to-pdf")
        assert m._reserved_mb() > 0
    later = time.time() + m._RESERVE_SETTLE_S + 1
    monkeypatch.setattr(jm.time, "time", lambda: later)
    with m._lock:
        assert m._reserved_mb() == 0, "沉澱時間過了還壓著，就是重複計算"


def test_finishing_a_job_releases_its_reservation(mem):
    m = jm.JobManager(workers=4)
    with m._lock:
        m._reserve("a", "office-to-pdf")
    m._finish_slot("a")
    with m._lock:
        assert m._reserved_mb() == 0


def test_forgetting_a_job_releases_its_reservation(mem):
    """取消 / 清理那幾條路 —— **一個地方負責忘掉**（v1.15.28 的 `_forget`）。"""
    m = jm.JobManager(workers=4)
    with m._lock:
        m._reserve("a", "office-to-pdf")
        m._forget("a")
        assert m._reserved_mb() == 0


def test_plenty_of_memory_still_dispatches(mem):
    """不可以把原本的行為弄壞：記憶體夠的時候照樣派得出去。"""
    mem["avail"] = 8000
    m = jm.JobManager(workers=4)
    with m._lock:
        m._reserve("a", "office-to-pdf")
        reserved = m._reserved_mb()
    assert jm._ram_allows_start("office-to-pdf", reserved) is True


def test_unknown_memory_always_allows(mem, monkeypatch):
    """讀不到記憶體資訊時一律放行 —— **這是現況，不要改**。

    寧可讓它跑，也不要因為讀不到數字就整個服務停擺。
    """
    monkeypatch.setattr(cs, "available_mb", lambda: None)
    assert jm._ram_allows_start("office-to-pdf", 99999) is True


def test_dispatch_itself_books_the_reservation(mem):
    """**端到端**：真的送兩件進去，只有一件會開始跑。

    上面那幾條直接呼叫 `_reserve()` —— 那證明得了「帳算得對」，
    **證明不了 `_dispatch()` 真的有記帳**（變異驗證：把派送裡那一行拿掉，
    上面全部照樣綠）。這條才是把線接起來的那一條。
    """
    import threading
    import time as _t

    mem["avail"] = 2000          # 理由見上一條
    m = jm.JobManager(workers=4)
    started = threading.Event()
    release = threading.Event()

    def _slow(_job):
        started.set()
        release.wait(10)

    a = m.submit("office-to-pdf", _slow)
    for _ in range(100):
        if started.is_set():
            break
        _t.sleep(0.05)
    assert started.is_set(), "第一件應該要開始跑"

    b = m.submit("office-to-pdf", lambda _j: None)
    _t.sleep(0.3)
    assert b.status == "pending", (
        f"第二件應該留在佇列裡（記憶體不夠），實際是 {b.status} —— 派送時沒有記帳")

    release.set()
    for _ in range(100):
        if a.status in ("done", "failed", "cancelled"):
            break
        _t.sleep(0.05)
