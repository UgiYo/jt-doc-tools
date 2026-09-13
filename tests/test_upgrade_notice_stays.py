"""改寫歷史之後的升級注意事項**要一直留著**（使用者 2026-09-13 指示）。

## 為什麼要有這條守門

2026-09-13 改寫過 git 歷史（移除一筆誤入版控的資料），所有標籤都指向新的
commit。**2026-09-13 之前用 git 安裝的機器，第一次升級前要手動跑一次**：

    git -C <安裝目錄> fetch --tags --force origin

不跑的話，舊版的 `jtdt update` 會在 `git fetch --tags` 以離開碼 1 失敗
（`would clobber existing tag`），訊息只說 `git fetch failed`。

**這段說明不可以在下一次改版時被順手拿掉** —— 客戶可能半年後才升級，
那時候他仍然會踩到。使用者原話：「這個要持續放著，不要下次更版就拿掉」。

判準是**那行指令真的還在**（不是找標題或年份 —— 那些會被改寫）：
README 的**開頭**要有，介紹站的升級段也要有。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.repo_paths import public_root  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PUB = public_root(ROOT)

#: 客戶要跑的那一行 —— 判準就是它
_CMD = "fetch --tags --force origin"


def test_the_readme_carries_the_recovery_command_near_the_top():
    text = (PUB / "README.md").read_text(encoding="utf-8")
    assert _CMD in text, (
        "README 少了改寫歷史後的升級指令 —— 2026-09-13 之前安裝的客戶"
        "會在 `jtdt update` 卡住而且看不出原因（使用者指示這段要持續放著）")
    # **要在開頭**：擺到最下面等於沒有人看得到
    head = "\n".join(text.splitlines()[:40])
    assert _CMD in head, "那段說明被移到很後面了 —— 要放在標題正下方"


def test_the_intro_site_upgrade_section_carries_it_too():
    html = (PUB / "docs" / "index.html").read_text(encoding="utf-8")
    assert _CMD in html, "介紹站的升級段少了那行指令"
    i = html.index(_CMD)
    around = html[max(0, i - 1500):i]
    assert "升級" in around, "那行指令沒有放在升級那一段裡"


def test_ops_guide_explains_it_as_well():
    text = (PUB / "OPS.md").read_text(encoding="utf-8")
    assert _CMD in text, "OPS.md 的升級流程少了那行指令"
