"""把「解析不信任的 PDF」放到**獨立行程**裡跑（外部稽核 F04）。

## 先把問題講準

稽核說的是「PyMuPDF 上游明文不支援多執行緒」。但我們**沒有共用 `Document`
物件**（每件工作自己開自己關），報告自己也說沒有重現崩潰。照字面去「加 lock」
是解錯問題 —— 散在各工具加 lock 既無法確認每個入口都遵守，也**隔離不了
解析器當機**。

真正值得做的是**爆炸半徑**：

| | 現在 | 隔離之後 |
|---|---|---|
| MuPDF 在 C 層 segfault | **整個 uvicorn 行程死掉** —— 所有進行中的作業與網頁一起沒了 | 只有那一次請求失敗 |
| 解析吃掉幾 GB 記憶體 | 被 OOM killer 挑中的可能是整個服務 | 子行程被殺，主行程活著 |
| 解析卡死 | 佔著執行緒直到逾時（如果有的話） | 逾時就砍掉 |

## ⚠ 為什麼用 `subprocess` 不用 `multiprocessing`

`multiprocessing` 的 spawn 會讓子行程**重新 import 父行程的 `__main__`**。
我們是 `python -m app.main` 起服務，那等於**每一次隔離呼叫都把整個 FastAPI
app 重建一次**（註冊 48 支工具、開資料庫…）。

`subprocess` 跑一支只 import 需要的東西的小 worker，完全繞開這件事，
而且逾時與「被訊號砍掉」的判讀都直接（`subprocess.run(timeout=…)` 與
負的 `returncode`）。

## 只收白名單

`name` 走一份固定的對照表，**不接受任意的 `module:func`** —— 這支的輸入
本來就是「不信任的檔案」，多開一個能指定 import 目標的縫沒有道理。
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]

#: `name` → `模組:函式`。**只有這裡列的才跑得起來。**
#: **先只收一支。** 計畫寫的是「不要一次全改」——判準是「輸入最不可信 ＋
#: 一垮就影響最多人」，`pdf-hidden-scan` 的用途就是「這份檔案可能有問題，
#: 幫我看一下」，輸入最惡意。其餘工具照舊，等這條路在正式機跑過一段時間
#: 再擴大。**不要先掛上還不存在的目標** —— 那比沒有更糟（呼叫時才爆）。
#: `name` → `(相對於專案根的檔案路徑, 函式名)`。
#:
#: **用檔案路徑載入，不要用 `import app.tools.x.scan_core`** ——
#: 那會觸發工具套件的 `__init__.py`（它 `from .router import router`），
#: 把整個 FastAPI 與設定鏈拉進子行程。實測差 **1.6 秒 → 0.4 秒**。
#: `scan_core.py` 只 import `fitz`、沒有相對匯入，所以照路徑載得起來。
ALLOWED: dict[str, tuple[str, str]] = {
    "hidden_scan": ("app/tools/pdf_hidden_scan/scan_core.py", "scan_path"),
}


class IsolatedError(RuntimeError):
    """子行程沒有給出可用的結果。"""


class IsolatedTimeout(IsolatedError):
    """超過時間還沒回來（已經把子行程砍掉了）。"""


class IsolatedCrash(IsolatedError):
    """子行程被訊號砍掉 —— 通常是解析器在 C 層炸了，或被 OOM killer 挑中。"""


def available() -> bool:
    """這台機器跑不跑得起隔離子行程。

    跑不起來時呼叫端要能**退回同一個行程**做 —— 隔離是防護，
    不是功能本身，不可以因為它壞掉就整支工具不能用。
    """
    return bool(sys.executable) and (_ROOT / "app" / "core" / "pdf_isolate_worker.py").exists()


def run_isolated(name: str, payload: dict[str, Any], *,
                 timeout: float = 120.0) -> Any:
    """在獨立行程裡跑 `ALLOWED[name]`，回它的結果（要可以 JSON 序列化）。

    **只傳路徑與可序列化的參數**，不傳 `Document` / `Page` 物件。
    """
    if name not in ALLOWED:
        raise KeyError(f"未登記的隔離函式：{name}")
    env = {**os.environ, "PYTHONPATH": str(_ROOT), "JTDT_ISOLATED": "1"}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "app.core.pdf_isolate_worker"],
            input=json.dumps({"target": list(ALLOWED[name]), "payload": payload}),
            capture_output=True, text=True, timeout=timeout,
            cwd=str(_ROOT), env=env)
    except subprocess.TimeoutExpired as e:
        raise IsolatedTimeout(
            f"解析超過 {timeout:.0f} 秒還沒完成，已中止。"
            "這份檔案可能異常龐大或結構有問題。") from e
    if proc.returncode < 0:
        try:
            sig = signal.Signals(-proc.returncode).name
        except ValueError:
            sig = str(-proc.returncode)
        raise IsolatedCrash(
            f"解析這份檔案時解析器異常結束（{sig}）—— 檔案可能毀損或結構異常。"
            "服務本身不受影響。")
    out = (proc.stdout or "").strip()
    if not out:
        raise IsolatedError(
            "解析子行程沒有回傳結果"
            + (f"：{proc.stderr.strip()[:200]}" if proc.stderr else "。"))
    try:
        msg = json.loads(out.splitlines()[-1])
    except ValueError as e:
        raise IsolatedError("解析子行程的回傳不是預期的格式。") from e
    if msg.get("ok"):
        return msg.get("result")
    # **例外型別要留住** —— 毀損檔案在全域處理器裡是 400，
    # 包成別的型別的話使用者會看到 500（「伺服器壞了」）。
    if msg.get("kind") == "filedata":
        import fitz
        raise fitz.FileDataError(msg.get("msg") or "cannot open broken document")
    raise IsolatedError(msg.get("msg") or "解析失敗")
