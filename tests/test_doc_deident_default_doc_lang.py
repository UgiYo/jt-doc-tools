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
