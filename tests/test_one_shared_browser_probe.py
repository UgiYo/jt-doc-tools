"""無頭瀏覽器的設定只能有**一份**。

## 由來

「找瀏覽器」與「挑一個瀏覽器讀得到的素材目錄」這兩件事原本在五支 e2e 測試
裡各寫一份。2026-09-16 加第五份時，那一份只比對**路徑字串**、沒有讀檔案
內容 —— 於是判斷不出 snap（Ubuntu 的 `/usr/bin/chromium-browser` 是一支
**shell 包裝腳本**，路徑上看不出任何 snap 痕跡）。

後果：素材被放到 `/tmp`（snap 看到的是它自己的那一個），
`DOM.setFileInputFiles` 照樣「成功」、畫面上的檔名也顯示得出來，只有真的
送出時才失敗 —— 測試看到「結果沒出來」然後 **skip**，**整支等於沒跑，
而 pytest 輸出裡看起來一切正常**。

所以這條擋的是「又有人自己寫一份」。
"""
from __future__ import annotations

import ast
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: 這兩個名字只能來自 `tools/browser_probe.py`。
OWNED = {"_uploadable_dir", "uploadable_dir", "_browser", "browser", "is_snap"}
SHARED = ROOT / "tools" / "browser_probe.py"


def _e2e_files() -> list[pathlib.Path]:
    out = []
    for p in sorted((ROOT / "tests").glob("*.py")):
        t = p.read_text(encoding="utf-8")
        if "remote-debugging-port" in t or "setFileInputFiles" in t:
            out.append(p)
    return out


def test_the_scan_actually_finds_the_e2e_tests():
    """**「掃 0 個檔」跟「掃過都乾淨」在 pytest 輸出裡長得一模一樣。**"""
    files = _e2e_files()
    assert len(files) >= 4, f"只收到 {len(files)} 支 e2e 測試，掃描條件壞了"


def test_the_shared_helper_reads_the_file_to_detect_snap():
    """共用的那一份必須**讀檔案內容**才判斷得出 snap。"""
    src = SHARED.read_text(encoding="utf-8")
    assert "open(b" in src and "snap" in src, (
        "共用的 snap 判斷沒有讀檔案內容 —— 只看路徑是判斷不出來的")
    from tools.browser_probe import is_snap
    assert is_snap("/usr/bin/does-not-exist") is False


@pytest.mark.parametrize("path", _e2e_files(), ids=lambda p: p.name)
def test_no_e2e_test_defines_its_own_browser_setup(path: pathlib.Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    dupes = [n.name for n in tree.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
             and n.name in OWNED]
    assert not dupes, (
        f"{path.name} 自己又寫了一份 {dupes} —— 請改用 "
        "`from tools.browser_probe import browser, uploadable_dir`。"
        "自己寫的那份漏掉 snap 判斷的話，整支測試會安靜地 skip 掉。")
