r"""原始碼裡不可以有無效的跳脫序列（`\-`、`` \` `` 這種）。

Python 3.12 對 `"\-"` 只發 `SyntaxWarning`，**3.14 起是 `SyntaxError`** ——
到那時候整個套件會在**收集階段**就掛掉，而不是某一支測試變紅。

實際踩到的兩處都在**說明文字**裡：docstring 引用 `\xa0` 旁邊順手寫了
`\-`，或是引用 markdown 的反引號寫成 `` \` ``。程式碼本身完全正常，
`pytest` 也照樣綠 —— 只有把警告開成錯誤才看得到。

修法是把那段 docstring 改成 raw string（`r\"\"\"…\"\"\"`），不要去改
說明的內容 —— 那些字正是在解釋規則。
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: 掃這幾個目錄。`github/` 是同步產物（內容相同），掃了只會重複報。
_DIRS = ("app", "tests", "tools", "scripts")


def _sources() -> list[Path]:
    out: list[Path] = []
    for d in _DIRS:
        p = ROOT / d
        if p.is_dir():
            out += [f for f in p.rglob("*.py") if "__pycache__" not in f.parts]
    return sorted(out)


def test_the_scan_reaches_the_source_tree():
    """**先證明掃得到東西** —— 目錄改名時這條會先紅。"""
    files = _sources()
    assert len(files) > 300, f"只掃到 {len(files)} 支 .py，掃描範圍大概錯了"


def test_no_source_file_has_an_invalid_escape_sequence():
    bad: list[str] = []
    for p in _sources():
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", SyntaxWarning)
                compile(p.read_text(encoding="utf-8"), str(p), "exec")
        except SyntaxWarning as e:
            bad.append(f"{p.relative_to(ROOT).as_posix()}: {e}")
        except SyntaxError as e:          # noqa: PERF203
            bad.append(f"{p.relative_to(ROOT).as_posix()}: {e.msg}（第 {e.lineno} 行）")
    assert not bad, (
        "這幾支有無效的跳脫序列（Python 3.14 起會是 SyntaxError）：\n"
        + "\n".join(bad)
        + "\n把那段字串改成 raw string（前面加 r），不要改說明的內容。")
