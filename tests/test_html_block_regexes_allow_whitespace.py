"""掃描器用的 `</script>` 正規式**一定要允許結束標籤裡有東西**。

`</script  >` 是合法的 HTML —— 寫死 `</script>` 的正規式會把它當成
「還沒結束」，於是**整塊被當成 script 內容吞掉**，而那支掃描器從此少檢查
一整片檔案。CodeQL 的 `py/bad-tag-filter` 報的就是這個（11 個 High），
本專案 issue #15 也踩過同一個家族（註解裡的字面 `</script>` 讓瀏覽器提早
關閉標籤，整頁 JS 變成純文字）。

判準：`tools.source_text` 的 `</tag\\b[^>]*>` ——
`</script>` / `</script >` / `</script\\n>` 都吃得到，
`</scriptfoo>` 不會誤配。

**只掃我們自己的 Python**（掃描器與工具），不掃樣板 —— 樣板裡的
`</script>` 是真的標籤，不是正規式。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: 正規式裡寫死的結束標籤（後面直接就是 `>`）。`\s*` 也不夠 ——
#: 結束標籤裡可以有屬性，剖析器會一路略過到 `>`。
_WEAK = re.compile(r"</(script|style|pre|textarea|title|iframe)(?:\\s\*)?>")

_DIRS = ("app", "tests", "tools", "scripts")


def _py_files() -> list[Path]:
    out: list[Path] = []
    for d in _DIRS:
        out += [p for p in (ROOT / d).rglob("*.py") if "__pycache__" not in p.parts]
    return sorted(out)


def test_the_scan_actually_reaches_the_files():
    """**先證明掃得到東西** —— 掃 0 個檔跟掃過都乾淨在輸出裡長得一樣。"""
    files = _py_files()
    assert len(files) > 200, f"只掃到 {len(files)} 個檔 —— 掃描器大概壞了"


def test_no_scanner_hard_codes_a_closing_tag_without_slack():
    bad: list[str] = []
    for p in _py_files():
        if p.name == Path(__file__).name:
            continue                      # 這一份自己在講那個寫法
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            # 只看**正規式**那幾行：要嘛在 `re.` 的呼叫裡，要嘛是 r-string
            if not re.search(r"re\.(sub|findall|search|match|compile|split)|r[\"']", line):
                continue
            if _WEAK.search(line):
                bad.append(f"{p.relative_to(ROOT).as_posix()}:{i}: {line.strip()[:90]}")
    assert not bad, (
        "這些正規式寫死了結束標籤，`</script  >` 會被當成沒結束：\n"
        + "\n".join(bad)
        + "\n改用 `tools.source_text` 的 `blocks()` / `strip_blocks()` / `block_re()`。")


@pytest.mark.parametrize("html,want", [
    ("<script>a</script>", ["a"]),
    ("<script >a</script  >", ["a"]),
    ("<script\n>a</script\n>", ["a"]),
    ("<scriptfoo>a</scriptfoo>", []),          # 不可以誤配
    ("<script>a</script><script>b</script>", ["a", "b"]),
])
def test_the_shared_helper_handles_the_awkward_forms(html: str, want: list):
    from tools.source_text import blocks
    assert blocks(html, "script") == want
