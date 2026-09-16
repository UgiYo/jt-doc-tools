"""去識別化支援**日文文件**（使用者 2026-09-14 交代、09-15 指示動工）。

照 v1.15.32「支援英文」那一輪的規矩做，**不是只加式子**：

* 日文專屬的樣態一律標 `locales=("ja",)` —— 台灣 / 英美的式子套在日文文件上是
  **抓錯**不是抓不到，而畫面會顯示「已處理」（誤判比漏抓更危險）。
* **有檢查碼的一律驗**（マイナンバー / 法人番号）—— 不驗的話任何 12 / 13 碼
  數字都會中，型號與注文番号會被大量誤判。
* **誤判語料是必要的驗收**：只驗「抓得到」的話，把式子放寬到抓一切也會過。
* 替換模式的假值要用**日文的**，而且號碼要**過不了檢查碼** ——
  驗得過的假號碼可能真的屬於某個人。
* **台灣與英文那兩組零退步**。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tools.doc_deident.fake_values import Replacer
from app.tools.doc_deident.patterns import (
    DOC_LANGS, _jp_corp_no_valid, _jp_mynumber_valid, catalog_for,
)

#: 日文的個資素材。**全部虛構**（マイナンバー 用檢查碼算得出來的測試號）。
GOOD = """従業員記録（サンプル。すべて架空の値です）

氏名：山田　太郎
マイナンバー：1234 5678 9018
法人番号：5835678256246
電話番号：090-1234-5678
固定電話：03-1234-5678
郵便番号：〒100-0001
住所：東京都千代田区千代田1-1-1
運転免許証番号：123456789012
健康保険証　記号 12345678 番号 90
メール：taro.yamada@example.co.jp
"""

#: **誤判語料**：滿是型號 / 注文番号 / ISBN / 版本號的日文文件。
#: 敏感類別的命中必須是 0。
BAD = """製品カタログ（機微情報は含みません）

型番：ABC-123456789012
免許のない社用車：3 台
記号：A のみ（番号なし）
注文番号：2026091500123
ISBN：978-4-7741-9876-5
バージョン：1.15.48
数量：1234 5678 9012 個
寸法：100-0001 mm
社内コード：03-1234-5678-X-99
"""

_JP_IDS = {"jp_mynumber", "jp_corp_no", "jp_phone", "jp_postcode",
           "jp_addr", "jp_name", "jp_driver_license", "jp_health_insurance"}


def _scan(locale: str, text: str) -> list[tuple[str, str]]:
    out = []
    for p in catalog_for(locale):
        for m in p.regex.finditer(text):
            v = m.group(p.value_group) if p.value_group else m.group(0)
            if p.validate(v):
                out.append((p.id, v.strip()))
    return out


def test_japanese_is_a_document_language():
    assert "ja" in dict(DOC_LANGS), "文件語言下拉少了日文"


def test_every_japanese_category_is_detected():
    found = {pid for pid, _v in _scan("ja", GOOD)}
    missing = _JP_IDS - found
    assert not missing, f"這幾類日文個資沒抓到：{sorted(missing)}"


def test_a_catalogue_of_part_numbers_produces_no_sensitive_hits():
    """**只驗「抓得到」的話，把式子放寬到抓一切也會過。**"""
    hits = [(pid, v) for pid, v in _scan("ja", BAD) if pid in _JP_IDS]
    assert hits == [], f"誤判語料出現敏感命中：{hits}"


@pytest.mark.parametrize("value,ok", [
    ("123456789018", True),
    ("1234 5678 9018", True),
    ("987654321093", True),
    ("123456789012", False),       # 檢查碼不對
    ("000000000000", False),       # 全同一個數字不是真的號碼
    ("12345678901", False),        # 位數不對
])
def test_my_number_checksum(value: str, ok: bool):
    assert _jp_mynumber_valid(value) is ok


@pytest.mark.parametrize("value,ok", [
    ("5835678256246", True),
    ("5835678256247", False),
    ("1111111111111", False),
])
def test_corporate_number_checksum(value: str, ok: bool):
    assert _jp_corp_no_valid(value) is ok


def test_taiwan_patterns_are_not_offered_for_japanese_documents():
    """台灣專屬的式子**不可以**套在日文文件上 —— 那是抓錯不是抓不到。"""
    ids = {p.id for p in catalog_for("ja")}
    for pid in ("tw_id", "tw_biz", "landline", "addr", "mobile", "plate"):
        assert pid not in ids, f"日文文件不該啟用台灣的 {pid}"
    for pid in ("us_ssn", "us_addr", "uk_ni", "nanp_phone"):
        assert pid not in ids, f"日文文件不該啟用英美的 {pid}"


def test_the_fake_values_are_japanese_and_never_valid():
    """假值要用日文的，而且號碼**過不了檢查碼**。

    驗得過的假號碼可能真的屬於某個人 —— 同 SSN 用 9xx、IBAN 刻意不通過
    mod-97 的原則。
    """
    r = Replacer()
    name = r.for_value("jp_name", "山田　太郎")
    assert name != "山田　太郎", "假名跟原值一樣，等於沒換"
    assert any("一" <= c <= "鿿" for c in name), f"日文文件換出非日文的名字：{name}"

    addr = r.for_value("jp_addr", "東京都千代田区千代田1-1-1")
    assert "市" in addr or "区" in addr, f"日文地址換成了別的形狀：{addr}"

    for i in range(6):
        mn = r.for_value("jp_mynumber", f"1234 5678 90{i}8")
        cn = r.for_value("jp_corp_no", f"583567825624{i}")
        assert not _jp_mynumber_valid(mn), f"假マイナンバー 竟然合法：{mn}"
        assert not _jp_corp_no_valid(cn), f"假法人番号 竟然合法：{cn}"


def test_a_japanese_interface_defaults_to_japanese_documents():
    from app.tools.doc_deident.patterns import default_doc_lang

    class _Req:
        def __init__(self, loc):
            self.cookies = {"jtdt_locale": loc}
            self.headers: dict = {}
            self.scope: dict = {}

    assert default_doc_lang(_Req("ja")) == "ja"
    assert default_doc_lang(_Req("en")) == "en"
    assert default_doc_lang(_Req("zh-Hant")) == "zh-Hant"


@pytest.mark.parametrize("locale,text,keep", [
    ("zh-Hant", "統一編號：12345675", "tw_biz"),
    ("zh-Hant", "行動電話：0912-345-678", "mobile"),
    ("en", "SSN: 123-45-6789", "us_ssn"),   # 9xx 是規定不指派的號段（假值才用）
    ("en", "Address: 1842 Maple Street, Springfield, IL 62704", "us_addr"),
])
def test_the_existing_locales_did_not_regress(locale: str, text: str, keep: str):
    """**台灣與英文那兩組零退步** —— 加語言不可以動到既有的偵測。"""
    assert keep in {pid for pid, _v in _scan(locale, text)}


def test_it_works_on_text_extracted_from_a_real_pdf():
    r"""**PDF 抽出來的分隔符不是你打的那一個。**

    實測 PyMuPDF 對同一份 PDF 給的是不斷行空白 `\xa0` 與**不斷行連字號**
    `\u2011`（不是 `-`）—— 用 `[ \-]` 去配的話 7 類只抓得到 3 類，
    而畫面會顯示「已處理」。本專案在中文地址上記過同一條
    （「PDF 抽出來的空白不是半形空白」），這是它的連字號版。
    """
    import fitz

    # 直接用 PDF 實際會給的那些字元，不要用自己打的
    text = ("氏名：山田\u3000太郎\n"
            "マイナンバー：1234\xa05678\xa09018\n"
            "法人番号：5835678256246\n"
            "電話番号：090\u20111234\u20115678\n"
            "郵便番号：〒100\u20110001\n"
            "住所：東京都千代田区千代田1\u20111\u20111\n"
            "運転免許証番号：1234\xa05678\xa09012\n"
            "健康保険証\u3000記号\xa0ABC\u2011123\xa0番号\xa090\n")
    found = {pid for pid, _v in _scan("ja", text)}
    missing = _JP_IDS - found
    assert not missing, f"PDF 的分隔符讓這幾類漏掉了：{sorted(missing)}"


def test_a_part_number_with_a_trailing_dash_is_not_a_phone_number():
    """`社内コード：03-1234-5678-X-99` 不是電話。

    前後**不可以緊接連字號** —— 少了那一半，誤判語料就會多一筆
    （放寬分隔符時實際踩到）。
    """
    hits = [v for pid, v in _scan("ja", "社内コード：03-1234-5678-X-99")
            if pid == "jp_phone"]
    assert hits == [], f"型號被當成電話：{hits}"


# --------------------------------------------------------------------------
# 只靠標籤定位的兩類（v1.15.57）
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text,expect", [
    ("運転免許証番号：123456789012", "123456789012"),
    ("免許番号 987654321098", "987654321098"),
    ("運転免許証番号 1234 5678 9012", "1234 5678 9012"),
    # **沒有標籤就不可以抓** —— 12 碼跟マイナンバー一樣長，
    # 裸數字抓了必然在兩類之間誤判，而畫面會顯示「已處理」。
    ("型番 123456789012", None),
    ("123456789012", None),
])
def test_the_driver_licence_needs_its_label(text: str, expect):
    got = [v for pid, v in _scan("ja", text) if pid == "jp_driver_license"]
    assert (got[0] if got else None) == (expect.strip() if expect else None)


@pytest.mark.parametrize("text,expect", [
    ("健康保険証　記号 12345678 番号 90", "12345678"),
    ("記号：ABC-123 番号：45", "ABC-123"),
    # 只有「記号」沒有「番号」時不算 —— 一般文件裡的「記号：A」會誤判
    ("記号：A のところ", None),
    ("番号：90", None),
])
def test_the_health_insurance_needs_both_labels(text: str, expect):
    got = [v for pid, v in _scan("ja", text) if pid == "jp_health_insurance"]
    assert (got[0] if got else None) == expect


def test_these_two_do_not_fire_on_other_locales():
    """**日文專屬的式子不可以在中文 / 英文文件上出現。**"""
    for loc in ("zh-Hant", "en"):
        ids = {p.id for p in catalog_for(loc)}
        assert "jp_driver_license" not in ids
        assert "jp_health_insurance" not in ids
