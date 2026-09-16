"""`pdf_isolate` 的子行程端：讀 stdin 的 JSON、跑指定的函式、把結果寫 stdout。

**白名單由父行程把關，這裡只跑它指定的東西。**
不要在這裡再讀一份 `ALLOWED` —— 那會變成兩份清單（一定會漂），
而且父行程在測試裡換掉白名單時子行程看不到。
子行程的 stdin 本來就只有我們寫得進去，所以這不是多開一個縫。

**這支要盡量少 import** —— 它的啟動成本會落在每一次隔離呼叫上。
目標模組是**照檔案路徑**載入的：用 `import app.tools.…` 會觸發工具套件的
`__init__.py`（它 `from .router import router`），把整個 FastAPI 拉進來，
實測多付 **1.6 秒**。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _load(rel: str, fn_name: str):
    path = (_ROOT / rel).resolve()
    # 只准載專案樹底下的檔案 —— 父行程已經把過關，這裡是第二道。
    if not str(path).startswith(str(_ROOT)) or not path.is_file():
        raise ImportError(f"refusing to load {rel}")
    spec = importlib.util.spec_from_file_location("_jtdt_isolated", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {rel}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, fn_name)


def main() -> int:
    try:
        req = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        print(json.dumps({"ok": False, "msg": "bad request"}))
        return 0
    rel, fn_name = req.get("target") or (None, None)
    if not rel or not fn_name:
        print(json.dumps({"ok": False, "msg": "no target"}))
        return 0
    try:
        fn = _load(rel, fn_name)
        result = fn(**(req.get("payload") or {}))
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        kind = "error"
        try:
            import fitz
            if isinstance(exc, fitz.FileDataError):
                kind = "filedata"
        except Exception:  # noqa: BLE001
            pass
        print(json.dumps({"ok": False, "kind": kind,
                          "msg": f"{type(exc).__name__}: {exc}"[:400]},
                         ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
