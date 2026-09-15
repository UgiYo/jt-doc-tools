"""去識別化的**預設文件語言**不可以因為介面語言而抓錯。

`Pattern.locales` 是依**文件語言**選式子，而「文件語言」的下拉清單
（`DOC_LANGS`）跟介面語言是**兩份清單**。介面加了新語言時，
`_default_doc_lang()` 原本是「開頭不是 `en` 就回 `zh-Hant`」——
日文介面的使用者會拿到**台灣那組式子**。

**台灣的市話 / 地址 / 統編式子套在別的語言的文件上是「抓錯」不是「抓不到」**
（實測把護照號、IBAN 片段、信用卡片段都當成電話）。畫面會顯示「已處理」，
使用者以為遮乾淨了 —— 那比漏抓更危險。

所以判準是：**介面語言不在 `DOC_LANGS` 裡時，退回語言中立那一組**（`en`），
不要退回 `zh-Hant`。
"""
from __future__ import annotations

import pytest

from app.core.ui_locale import COOKIE_NAME, DEFAULT_LOCALE, SUPPORTED
from app.tools.doc_deident import patterns as P
from app.tools.doc_deident.router import _default_doc_lang


class _Req:
    def __init__(self, locale: str | None):
        self.cookies = {COOKIE_NAME: locale} if locale else {}


@pytest.mark.parametrize("ui", SUPPORTED)
def test_the_default_document_language_is_one_we_actually_have_patterns_for(ui: str):
    got = _default_doc_lang(_Req(ui))
    codes = {c for c, _name in P.DOC_LANGS}
    assert got in codes, f"介面 {ui} 的預設文件語言 {got!r} 不在 DOC_LANGS 裡"


def test_a_ui_language_without_patterns_does_not_fall_back_to_taiwan():
    """**這條是重點。** 沒有對應式子的介面語言，不可以拿到台灣那一組。"""
    codes = {c for c, _name in P.DOC_LANGS}
    extra = [c for c in SUPPORTED if c not in codes and c != DEFAULT_LOCALE]
    if not extra:
        pytest.skip("目前每個介面語言都有對應的式子集")
    for ui in extra:
        got = _default_doc_lang(_Req(ui))
        assert got != "zh-Hant", (
            f"介面 {ui} 沒有對應的式子集，卻退回台灣那一組 —— "
            "台灣的市話 / 地址 / 統編式子套上去是**抓錯**，畫面還會顯示「已處理」")


def test_chinese_and_english_are_unchanged():
    """既有行為一個位元都不可以動。"""
    assert _default_doc_lang(_Req("zh-Hant")) == "zh-Hant"
    assert _default_doc_lang(_Req("en")) == "en"
    assert _default_doc_lang(_Req(None)) == "zh-Hant"


def test_both_deident_tools_share_one_default():
    """**兩支工具要用同一支判斷。**

    2026-09-14 加日文時，我只修了文件去識別化那一支 —— 文字去識別化照樣把
    「不是 en」當成台灣，於是日文介面下**信用卡號被認成台灣市話**
    （截圖裡當場看到）。同一個家族要一次掃完。

    判準走 AST：兩支 router 的預設值都必須**呼叫 `patterns` 那一支**，
    不可以自己再寫一份 if/else。
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for rel in ("app/tools/doc_deident/router.py", "app/tools/text_deident/router.py"):
        src = (root / rel).read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef)
                   and n.name in ("_default_doc_lang", "_doc_lang")), None)
        assert fn is not None, f"{rel} 找不到預設文件語言的函式"
        calls = {ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call)}
        assert "P.default_doc_lang" in calls, (
            f"{rel} 沒有委派給 patterns.default_doc_lang —— 自己抄一份"
            "就會像 2026-09-14 那樣只修好一支")


def test_the_shared_default_never_falls_back_to_taiwan_for_an_unknown_ui():
    """介面語言的預設**不可以退回台灣那組**。

    台灣的市話 / 地址 / 統編式子套在別的語言的文件上是**抓錯**不是抓不到，
    而畫面會顯示「已處理」—— 誤判比漏抓更危險。

    **有那個語言的式子就用它**（v1.15.49 起日文有了 → `ja` 回 `ja`）；
    沒有的話退到語言中立 ＋ 英美那一組（`en`）。判準寫成「不是 zh-Hant」
    而不是寫死某個值 —— 加語言時這條不該跟著紅。
    """
    from app.tools.doc_deident import patterns as P

    class _Req:
        def __init__(self, loc):
            self.cookies = {"jtdt_locale": loc} if loc else {}
            self.headers: dict = {}
            self.scope: dict = {}

    assert P.default_doc_lang(_Req("en")) == "en"
    assert P.default_doc_lang(_Req("zh-Hant")) == "zh-Hant"
    # 有日文式子了 → 用日文那一組
    assert P.default_doc_lang(_Req("ja")) == "ja"

    # **每一個支援的介面語言都要驗一次**，而且非中文的介面絕不可以落到
    # `zh-Hant`。不要拿沒支援的語言（例如 `ko`）當輸入 —— `ui_locale.resolve()`
    # 會先把它正規化成預設語言，於是這裡看到的是 `zh-Hant`，
    # 那是**正規化的結果不是退回台灣**，用它當判準會誤報（我第一版就是這樣）。
    from app.core.ui_locale import SUPPORTED

    for loc in SUPPORTED:
        got = P.default_doc_lang(_Req(loc))
        if loc.startswith("zh"):
            assert got == "zh-Hant", (loc, got)
        else:
            assert got != "zh-Hant", (
                f"{loc} 介面的預設文件語言落到台灣那一組 —— "
                "台灣的式子套在別的語言上是抓錯不是抓不到")


def test_a_non_chinese_address_is_not_masked_into_a_taiwanese_one():
    """遮罩要**保留格式**，不可以換成另一個國家的地址。

    原本一律回 `OO市OO區OO路OOO號` —— 於是
    `1842 Maple Street, Springfield, IL 62704` 被遮成一個台灣地址，
    讀的人會以為那份文件本來就是台灣的（2026-09-14 日文截圖看到）。
    """
    from app.tools.doc_deident.patterns import _mask_addr

    out = _mask_addr("1842 Maple Street, Springfield, IL 62704")
    assert "市" not in out and "號" not in out, f"英文地址被遮成台灣地址：{out}"
    assert "Maple" not in out and "62704" not in out, f"內容沒有遮掉：{out}"
    # 形狀要留著：逗號與空白的位置不變、長度一樣
    src = "1842 Maple Street, Springfield, IL 62704"
    assert len(out) == len(src)
    assert [i for i, c in enumerate(src) if c == ","] == \
           [i for i, c in enumerate(out) if c == ","]
    # 中文地址維持原本的樣子
    assert _mask_addr("臺北市中正區範例路 100 號") == "OO市OO區OO路OOO號"
