"""解析器的行程隔離（外部稽核 F04）。

## 要防的是什麼

不是「thread safety」—— 我們**沒有共用 `Document` 物件**，稽核報告自己也說
沒有重現崩潰。要防的是**爆炸半徑**：MuPDF 在 C 層 segfault 會把**整個
uvicorn 行程**帶走（所有進行中的作業與網頁一起沒了）。隔離之後只有那一次
請求失敗。

## 判準：兩個方向都要跑

**只驗「隔離之後還是活的」證明不了任何事** —— 說不定那個崩潰根本沒發生。
所以下面那條**同一段程式碼跑兩次**：不隔離的那次主行程必須死，
隔離的那次必須活著而且拿得到錯誤訊息。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import pdf_isolate  # noqa: E402


def _sample() -> Path:
    import fitz
    p = ROOT / "temp" / "isolate_sample.pdf"
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        d = fitz.open()
        d.new_page().insert_text((60, 90), "isolate", fontsize=12, fontname="helv")
        d.save(str(p)); d.close()
    return p


def test_the_isolated_result_is_identical_to_running_inline():
    """**正常路徑的產出要跟沒隔離時一樣** —— 不然這就不是隔離，是換一支程式。"""
    from app.tools.pdf_hidden_scan.scan_core import scan_path
    src = str(_sample())
    assert pdf_isolate.run_isolated("hidden_scan", {"src": src}) == scan_path(src)


def test_only_whitelisted_targets_run():
    """`name` 走白名單，**不接受任意的 `模組:函式`**。"""
    with pytest.raises(KeyError):
        pdf_isolate.run_isolated("os:system", {"src": "x"})
    for rel, _fn in pdf_isolate.ALLOWED.values():
        assert (ROOT / rel).exists(), f"白名單指到不存在的檔案：{rel}"


def test_a_broken_file_still_comes_back_as_filedata_error():
    """**例外型別要留住** —— 毀損檔案在全域處理器裡是 400。

    包成別的型別的話使用者會看到 500（「伺服器壞了」），
    然後一直重試一個永遠不會成功的上傳。
    """
    import fitz
    bad = ROOT / "temp" / "isolate_broken.pdf"
    bad.write_bytes(b"%PDF-1.4\nthis is not a pdf at all\n")
    with pytest.raises(fitz.FileDataError):
        pdf_isolate.run_isolated("hidden_scan", {"src": str(bad)})


def test_a_hang_is_killed_and_reported_as_a_timeout():
    script = f'''
import sys, json
sys.path.insert(0, {str(ROOT)!r})
from app.core import pdf_isolate
pdf_isolate.ALLOWED["_sleep"] = ("tests/_isolate_victim.py", "sleep_forever")
try:
    pdf_isolate.run_isolated("_sleep", {{}}, timeout=2.0)
    print("NO_TIMEOUT")
except pdf_isolate.IsolatedTimeout:
    print("TIMEOUT_OK")
'''
    r = subprocess.run([sys.executable, "-c", script], capture_output=True,
                       text=True, timeout=90, cwd=str(ROOT))
    assert "TIMEOUT_OK" in r.stdout, (r.stdout, r.stderr[-400:])


def test_a_crashing_parser_kills_only_the_child():
    """**兩個方向都跑**：不隔離時主行程必須死，隔離時必須活著。

    沒有「不隔離那一半」的話，這條證明不了隔離真的有用 ——
    說不定那個崩潰根本沒發生。
    """
    victim = ROOT / "tests" / "_isolate_victim.py"
    assert victim.exists()

    # ① 不隔離：同一個行程裡直接呼叫 → 主行程被訊號帶走
    inline = f'''
import sys
sys.path.insert(0, {str(ROOT)!r})
import importlib.util
spec = importlib.util.spec_from_file_location("v", {str(victim)!r})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.crash()
print("SURVIVED")
'''
    a = subprocess.run([sys.executable, "-c", inline], capture_output=True,
                       text=True, timeout=90, cwd=str(ROOT))
    assert a.returncode < 0, (
        f"不隔離的那次竟然沒死（returncode={a.returncode}）—— "
        "這個測試的前提不成立，換一種讓解析器崩潰的方式")
    assert "SURVIVED" not in a.stdout

    # ② 隔離：主行程活著，而且拿得到「子行程被訊號砍掉」的訊息
    isolated = f'''
import sys
sys.path.insert(0, {str(ROOT)!r})
from app.core import pdf_isolate
pdf_isolate.ALLOWED["_crash"] = ("tests/_isolate_victim.py", "crash")
try:
    pdf_isolate.run_isolated("_crash", {{}}, timeout=30.0)
    print("NO_CRASH_REPORTED")
except pdf_isolate.IsolatedCrash as e:
    print("CRASH_CONTAINED:" + str(e)[:80])
print("PARENT_ALIVE")
'''
    b = subprocess.run([sys.executable, "-c", isolated], capture_output=True,
                       text=True, timeout=90, cwd=str(ROOT))
    assert b.returncode == 0, f"隔離之後主行程還是死了：{b.returncode} {b.stderr[-300:]}"
    assert "CRASH_CONTAINED" in b.stdout and "PARENT_ALIVE" in b.stdout, b.stdout


def test_the_tool_falls_back_when_isolation_cannot_run(monkeypatch):
    """**隔離是防護不是功能** —— 子行程起不來時要照舊做得完。"""
    import importlib
    # **不可以 `import app.tools.pdf_hidden_scan.router as R`** ——
    # 那個套件的 `__init__.py` 把 `router` 綁成 `APIRouter` 物件。
    R = importlib.import_module("app.tools.pdf_hidden_scan.router")
    monkeypatch.setattr(pdf_isolate, "available", lambda: False)
    got = R._scan_isolated_or_inline(str(_sample()))
    assert isinstance(got, dict) and got, "退回同一個行程時掃不出東西"


def test_the_worker_does_not_import_the_whole_app():
    """子行程的 import 成本落在**每一次請求**上。

    原本子行程 `import app.tools.…`，那會觸發工具套件的 `__init__.py`
    （它 `from .router import router`），把整個 FastAPI 與設定鏈拉進來 ——
    實測固定成本 **1.6 秒**。改成照檔案路徑載入之後是 **0.5 秒**。

    判準放在**掃描核心那個檔案的 import 上**：它只能 import 標準函式庫
    與 `fitz`，不可以有相對匯入（那會需要套件，等於又把 `__init__` 拉進來）。
    """
    import ast
    for rel, _fn in pdf_isolate.ALLOWED.values():
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.level == 0, (
                    f"{rel} 有相對匯入（`from . import …`）—— 照檔案路徑載入時"
                    "會失敗，而且會把整個套件拉進子行程")
                assert (node.module or "").split(".")[0] != "app", (
                    f"{rel} import 了 `{node.module}` —— 子行程會因此拉進整個 app")
            if isinstance(node, ast.Import):
                for a in node.names:
                    assert a.name.split(".")[0] != "app", (
                        f"{rel} import 了 `{a.name}` —— 子行程會因此拉進整個 app")


def test_isolation_is_not_slower_than_a_second():
    """固定成本要量出來，不要憑感覺。

    **這條不是效能測試**（機器忙的時候本來就會慢）——
    它擋的是「有人在掃描核心裡加了一個很重的 import」那種退步。
    門檻取實測值（約 0.5 秒）的四倍。
    """
    import statistics
    import time
    from app.tools.pdf_hidden_scan.scan_core import scan_path
    src = str(_sample())
    scan_path(src)
    pdf_isolate.run_isolated("hidden_scan", {"src": src})   # 暖機
    inline, iso = [], []
    for _ in range(3):
        t0 = time.perf_counter(); scan_path(src); inline.append(time.perf_counter() - t0)
        t0 = time.perf_counter()
        pdf_isolate.run_isolated("hidden_scan", {"src": src})
        iso.append(time.perf_counter() - t0)
    overhead = statistics.median(iso) - statistics.median(inline)
    assert overhead < 2.0, (
        f"隔離的固定成本變成 {overhead*1000:.0f} ms（實測基準約 500 ms）—— "
        "多半是掃描核心那支多 import 了什麼重的東西")


def test_the_scan_endpoints_really_go_through_isolation(monkeypatch):
    """**上面那些只證明得了「機制對」，證明不了「端點真的用了它」。**

    實測過：把端點改回直接呼叫 `scan_path`，前面八條全綠 ——
    那正是外部稽核 F06 記過的同一個洞（測試直接呼叫內部函式）。
    所以這條**真的送一次請求進去**，看隔離那支有沒有被呼叫。

    兩個入口都要驗 —— 不然會出現「網頁走隔離、API 沒走」這種差別，
    而且不會有人發現。
    """
    from fastapi.testclient import TestClient

    from app.main import app

    calls: list[str] = []
    real = pdf_isolate.run_isolated

    def spy(name, payload, **kw):
        calls.append(name)
        return real(name, payload, **kw)

    monkeypatch.setattr(pdf_isolate, "run_isolated", spy)
    data = _sample().read_bytes()
    client = TestClient(app)
    for url in ("/tools/pdf-hidden-scan/scan",
                "/tools/pdf-hidden-scan/api/pdf-hidden-scan"):
        calls.clear()
        r = client.post(url, files={"file": ("a.pdf", data, "application/pdf")})
        assert r.status_code == 200, (url, r.text[:200])
        assert calls == ["hidden_scan"], (
            f"{url} 沒有走隔離子行程（呼叫記錄：{calls}）")
