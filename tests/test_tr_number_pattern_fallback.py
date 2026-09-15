"""`tr()` 查不到時，把數字換成 `{0}` 再查一次（v1.15.51）。

## 為什麼需要這一層

**伺服器送來的作業訊息是先內插好的** —— `job.message = f"完成（{n} 份）"`
在背景執行緒裡產生，那時候沒有 request、不知道使用者的語言，所以只能送中文
由前端翻。但 `完成（3 份）` 這種內插過的整句**永遠查不到字典**，於是英文 /
日文介面上一直看得到中文（2026-09-16 用截圖工具順便掃「送出後的結果區」
才發現 —— 逐頁掃描器只看頁面剛載入的狀態，看不到這一格）。

## 判準

* 查得到原句 → 照舊（**不可以改變既有行為**）。
* 查不到、但把數字換成 `{0}` 之後查得到 → 用那條並把數字填回去。
* 兩個都查不到 → **原樣回傳**，跟現在一模一樣（最壞情況不變差）。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
I18N_JS = ROOT / "static" / "js" / "i18n.js"


def _node() -> str:
    exe = shutil.which("node")
    if not exe:
        pytest.skip("沒有 node")
    return exe


def _run(catalog: dict, cases: list[str]) -> list[str]:
    script = textwrap.dedent(f"""
        global.window = {{}};
        require({json.dumps(str(I18N_JS))});
        window.__I18N__ = {json.dumps(catalog, ensure_ascii=False)};
        const out = {json.dumps(cases, ensure_ascii=False)}.map((s) => window.tr(s));
        console.log(JSON.stringify(out));
    """)
    r = subprocess.run([_node(), "-e", script], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


_CAT = {
    "完成（{0} 份）": "Done ({0} file(s))",
    "第 {0} 頁，共 {1} 頁": "Page {0} of {1}",
    "下載 PDF": "Download PDF",
}


def test_an_exact_hit_is_unchanged():
    assert _run(_CAT, ["下載 PDF"]) == ["Download PDF"]


def test_an_interpolated_message_finds_the_parameterised_key():
    assert _run(_CAT, ["完成（3 份）", "完成（12 份）"]) == \
        ["Done (3 file(s))", "Done (12 file(s))"]


def test_several_numbers_are_matched_in_order():
    assert _run(_CAT, ["第 3 頁，共 12 頁"]) == ["Page 3 of 12"]


def test_a_non_numeric_variable_is_out_of_scope():
    """**這一層只處理「變數全部是數字」的句子。**

    `已上傳 a.pdf（6379.1 KB）` 的第一個變數是檔名不是數字，換不出
    `已上傳 {0}（{1} KB）` 這把鍵 —— 這種要在**產生那句話的地方**自己包
    `tr('已上傳 {0}（{1} KB）').replace(...)`，不要指望這個退路。
    把界線寫成測試，免得下一個人以為它什麼都接得住。
    """
    cat = {"已上傳 {0}（{1} KB）": "Uploaded {0} ({1} KB)"}
    assert _run(cat, ["已上傳 a.pdf（6379.1 KB）"]) == ["已上傳 a.pdf（6379.1 KB）"]


def test_an_unknown_string_comes_back_unchanged():
    """**最壞情況不可以變差** —— 查不到就原樣回傳，跟加這一層之前一樣。"""
    assert _run(_CAT, ["沒有這一條"]) == ["沒有這一條"]


def test_a_near_miss_does_not_get_rewritten():
    """數字換掉之後仍然查不到的，也要原樣回傳 ——
    **不可以自己拼一句出來**。"""
    assert _run(_CAT, ["完成（3 份）並且多了一段"]) == ["完成（3 份）並且多了一段"]


def test_a_string_with_no_digits_skips_the_second_lookup():
    """沒有數字就沒有第二次查的必要 —— 這條同時擋住「把整句當 pattern」那種寫法。"""
    assert _run({"{0}": "X"}, ["完全沒有數字"]) == ["完全沒有數字"]
