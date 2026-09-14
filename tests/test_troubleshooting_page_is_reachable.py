"""安裝 / 升級失敗時，要給得出「接下來怎麼辦」。

使用者 2026-09-14：「整理一個安裝跟升級失敗 Q&A 放在 pages 獨立一頁，
然後我們的 install.sh 或 jtdt update 之類當發生失敗時都要提供這個 url
讓使用者知道怎麼辦。」

**只印一行錯誤等於把人丟在原地** —— 這個專案的失敗多半有明確解法
（缺 git、企業 TLS、磁碟不足、標籤衝突、服務佔住檔案），但使用者看不到。

判準有三段，缺一段這條規則就名存實亡：
  ① 那一頁**存在**，而且真的寫了那幾個已知狀況（不是空殼）。
  ② 介紹站**連得到**它（沒有入口的頁面等於不存在）。
  ③ **失敗路徑真的會印出網址** —— 安裝腳本與 `jtdt update` 都要。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.repo_paths import public_root  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PUB = public_root(ROOT)
URL = "https://jasoncheng7115.github.io/jt-doc-tools/troubleshooting.html"
URL_EN = "https://jasoncheng7115.github.io/jt-doc-tools/troubleshooting-en.html"
PAGE = PUB / "docs" / "troubleshooting.html"


def test_the_page_exists_and_covers_the_known_failures():
    assert PAGE.exists(), "缺 docs/troubleshooting.html"
    html = PAGE.read_text(encoding="utf-8")
    # 每一則都是真的發生過的 —— 空殼頁面等於沒有
    for marker in ("would clobber existing tag", "Health check timed out",
                   "CERTIFICATE_VERIFY_FAILED", "readonly database",
                   "uv venv failed", "CSRF"):
        assert marker in html, f"疑難排解頁少了「{marker}」那一則"
    assert "fetch --tags --force origin" in html, "少了升級卡住的那行修復指令"


def test_the_link_lives_in_the_generator_not_the_generated_page():
    """`api.html` 是 `build-api-page.py` 產生的 —— 直接改它會被下一次生成蓋掉。

    2026-09-14 實際踩到：導覽的「疑難排解」我改在 `docs/api.html`，
    重跑生成器之後就不見了（跟 `.gitignore` 被同步腳本重寫是同一個病）。
    判準落在**唯一來源**上。
    """
    gen = (PUB / "build-api-page.py").read_text(encoding="utf-8")
    assert "troubleshooting.html" in gen, (
        "api.html 的疑難排解連結要寫在 build-api-page.py 裡 —— "
        "改產出沒有用，下一次生成就沒了")


def test_the_site_links_to_it():
    for name in ("index.html", "api.html"):
        t = (PUB / "docs" / name).read_text(encoding="utf-8")
        assert 'troubleshooting.html' in t, f"{name} 沒有連到疑難排解頁"


def _locales() -> list[str]:
    """中文以外的語言 —— **唯一來源是 `ui_locale.SUPPORTED`**。

    寫死 `en` 的話，加了日文之後這條會**安靜地只驗英文**。
    """
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app.core.ui_locale import DEFAULT_LOCALE, SUPPORTED
    return [c for c in SUPPORTED if c != DEFAULT_LOCALE]


#: 語言切換那一組。**`id` 在 `<span>` 上不是在 `<a>` 上** ——
#: 三語之後它是一組連結不是一顆切換鈕，用 `<a[^>]*id="langSwitch"` 去配
#: 會一條都配不到，於是那幾條回中文頁的連結被當成「連錯了」
#: （2026-09-14 加日文時這條就是這樣紅的）。
_LANG_GROUP = re.compile(r'<(a|span)[^>]*id="langSwitch"[^>]*>.*?</\1>', re.S)


@pytest.mark.parametrize("lang", _locales())
def test_the_translated_pages_link_to_the_same_language(lang: str):
    """某語言的頁要連同語言的頁（使用者 2026-09-14）。

    原本英文版的導覽連的是 `api.html`（中文頁）—— 讀者一點就掉回中文。
    """
    assert (PUB / "docs" / f"troubleshooting-{lang}.html").exists(), \
        f"缺 {lang} 版疑難排解頁"
    for name in (f"index-{lang}.html", f"api-{lang}.html",
                 f"troubleshooting-{lang}.html"):
        t = (PUB / "docs" / name).read_text(encoding="utf-8")
        # 語言切換那一組**本來就要**指回別的語言，把它排除再看
        without_switch = _LANG_GROUP.sub("", t)
        bad = re.findall(r'href="(?:index|api|troubleshooting)'
                         r'(?:-[a-zA-Z-]+)?\.html[^"]*"', without_switch)
        wrong = [b for b in bad if f"-{lang}.html" not in b]
        assert not wrong, f"{name} 連到別的語言：{sorted(set(wrong))}"
        assert 'id="langSwitch"' in t, f"{name} 少了語言切換連結"


def test_the_chinese_page_has_a_language_switch():
    t = (PUB / "docs" / "troubleshooting.html").read_text(encoding="utf-8")
    # 語言選單是 `<select>`（v1.15.47 起），每個語言一個 `<option value="…">`
    for lang in _locales():
        assert f'value="troubleshooting-{lang}.html"' in t, \
            f"中文頁的語言選單少了 {lang}"


def test_the_installers_print_the_url_when_they_fail():
    sh = (PUB / "install.sh").read_text(encoding="utf-8")
    assert URL in sh, "install.sh 失敗時沒有給求助網址"
    # **要在 die() 裡** —— 只定義一個常數但沒有人印，等於沒有。
    # 判準看**那一行**：`die()` 在 install.sh 是一行的 shell 函式，
    # 用 `\{[^}]*\}` 去配會停在 `${C_RED}` 的那個 `}`（我第一版就是這樣誤判的）。
    die_line = [ln for ln in sh.splitlines() if ln.strip().startswith("die()")]
    assert die_line, "install.sh 找不到 die()"
    assert "TROUBLESHOOT_URL" in die_line[0], (
        "install.sh 的 die() 沒有印出求助網址（只定義常數不算）")

    ps1 = (PUB / "install.ps1").read_text(encoding="utf-8")
    assert URL in ps1, "install.ps1 失敗時沒有給求助網址"

    nsi = (PUB / "packaging" / "windows" / "installer.nsi").read_text(encoding="utf-8")
    # **中文那條給中文頁、英文那條給英文頁**
    assert URL in nsi and URL_EN in nsi, (
        "安裝程式的失敗訊息要依語言給對應的網址（繁中 → 中文頁、英文 → 英文頁）")


def test_the_updater_prints_the_url_on_every_failure_path():
    src = (ROOT / "app" / "cli.py").read_text(encoding="utf-8")
    assert URL in src and URL_EN in src, (
        "cli.py 要有中英兩個網址 —— 依作業系統語言挑（中文系統給中文頁）")
    # 幾條真的會失敗的路徑都要印
    for marker in ("git fetch failed", "git reset --hard origin/main failed",
                   "uv sync failed.", "Full log: jtdt logs"):
        i = src.index(marker)
        after = src[i:i + 400]
        assert "_print_help_url()" in after, (
            f"「{marker}」這條失敗路徑沒有印出求助網址")
