"""乘車證明解析器單元測試（合成 fixture，不含真實票號 / 統編 / 站名資料）。

用符合台鐵 / 高鐵官方版面的假資料驗證抽取邏輯，不放真實憑證內容進版控。
真實樣本的驗收走部署 / 手動（TEST_PLAN）。
"""
from __future__ import annotations

import pytest

from app.tools.transit_proof import parser


# 高鐵電子車票證明版面：label ：value。假統編 / 假票號 / 任意站名。
_HSR = """統一編號 : 00000000
台灣高鐵電子車票證明
列印日期：2026-07-14
營利事業名稱 : ********
卡號/票號 : 0000000000000
乘車日期 : 2026-06-09 07:20:00
票證類別 : 手機電子票證
起程站 : 高鐵AAA車站
到達站 : 高鐵BBB車站
銷售額 : 700
營業稅額 : 35
票價 : 735
控管編號 : 000000000000000000
"""

# 台鐵購票證明版面：PyMuPDF 打散後的順序（label 群組 + value 群組交錯）。
_TRA = """購票證明
X00000000000000
票號
印製日期
2026/07/14
乘車日
列車資訊
票種
票價
乘車區間
2026/05/19
莒光(700)
123 車次
08:00 CCC > 10:30 DDD
全票
(自由座)
420 元
※ 辦理乘車變更或退票，須併同原票及購票證明辦理。
"""


def test_detect_kind():
    assert parser.detect_kind(_HSR) == "thsrc"
    assert parser.detect_kind(_TRA) == "tra"
    assert parser.detect_kind("隨便的內容") is None


def test_parse_hsr():
    d = parser.parse_text(_HSR)
    assert d["transport"] == "高鐵"
    assert d["date"] == "2026-06-09"
    assert d["depart_time"] == "07:20"
    assert d["arrive_time"] == ""
    assert d["origin"] == "AAA"        # 去「高鐵」前綴 + 「車站」後綴
    assert d["destination"] == "BBB"
    assert d["fare"] == 735
    assert d["amount_untaxed"] == 700
    assert d["tax"] == 35
    assert d["ticket_no"] == "0000000000000"
    assert d["buyer_tax_id"] == "00000000"
    assert d["train"] == ""


def test_parse_tra():
    d = parser.parse_text(_TRA)
    assert d["transport"] == "台鐵"
    assert d["date"] == "2026-05-19"          # 排除印製日期 2026/07/14
    assert d["depart_time"] == "08:00"
    assert d["arrive_time"] == "10:30"
    assert d["origin"] == "CCC"
    assert d["destination"] == "DDD"
    assert d["fare"] == 420
    assert d["ticket_type"] == "全票(自由座)"
    assert d["ticket_no"] == "X00000000000000"
    assert "莒光" in d["train"]
    assert "123車次" in d["train"]
    assert d["amount_untaxed"] is None
    assert d["tax"] is None


def test_tra_excludes_chengche_qujian_from_train():
    """回歸：'乘車區間' label 的「區間」不可被當成車種。"""
    d = parser.parse_text(_TRA)
    assert not d["train"].startswith("區間")


def test_unknown_raises():
    with pytest.raises(parser.ParseError):
        parser.parse_text("這不是乘車證明，只是一段普通文字。")


def test_empty_fields_raises():
    with pytest.raises(parser.ParseError):
        parser.parse_text("台灣高鐵電子車票證明\n（版面全空，無欄位）")


def test_roc_date_edge():
    """民國年換算：西元 2026 → 民國 115（parser 只出 ISO，格式化在 settings）。"""
    d = parser.parse_text(_HSR)
    from app.tools.transit_proof import settings as s
    assert s.apply_format("date", d["date"], {"date": "roc"}) == "115/06/09"


# ---------------------------------------------------------------------------
# Uber（2026-09-13 使用者提供兩份真實檔案後新增）
#
# 版面照真實收據，**資料全部是杜撰的**（地址 / 車牌 / 金額 / 統編 / 發票號碼）。
# 真實樣本留在 temp_pdfs/（不進版控），驗收走部署。
#
# 兩份檔案是**同一筆行程**：
#   * 行程收據 —— 有里程、上下車時間與地址、車牌、總計。
#   * 電子發票證明聯 —— **只開「Uber 處理費」那 10 元**（計程車行程本身不開）。
#     行程收據的「總計」已經含了這 10 元，所以發票**不可以自成一列**。
# ---------------------------------------------------------------------------

_UBER_TRIP = """2026 年 8 月 18 日
下午 4:58
測試，感謝您的搭乘
希望您對今晚的搭乘體驗感到滿意。
總計
$410.00
$33.00
已賺取 Uber One 點數
Uber處理費 
$10.00
行程費用
$413.00
Uber One 點數
-$13.00
款項
Visa ••••0000 (測試卡)
2026/8/18 下午 5:28
請造訪行程頁面, 瞭解詳細資訊，包括電子發票 (計程車行程不適用於電子發票)。
車行／車隊：
測試車隊 甲-１
行程詳細資訊
Electric
10.79 公里, 26 minutes
車牌號碼：
AAA000
下午 5:01
TWN測試市測試市甲區一路1號
下午 5:27
40000台灣測試市乙區二街2號
由測試 王提供的行程
"""

_UBER_INVOICE = """　
優步福爾摩沙股份有限公司
電子發票證明聯
115年07-08月
  AA-00000000
2026-08-18 17:28:11 格式:25
隨機碼:0000
總計:10
賣方:00000000
買方:11111111
交易明細資料
發票號碼:AA00000000
Uber 處理費
     10*1
10TX
總計:
10
銷售額(應稅):10
稅額:0
交易日期: 18 Aug 2026
"""


def test_uber_trip_is_detected_and_parsed():
    assert parser.detect_kind(_UBER_TRIP) == "uber_trip"
    d = parser.parse_text(_UBER_TRIP)
    assert d["transport"] == "Uber"
    assert d["date"] == "2026-08-18"
    # **實付金額是「總計」那一筆** —— 行程費用 413 與處理費 10 都是明細
    assert d["fare"] == 410
    assert d["vehicle"] == "AAA000"
    assert d["distance"] == "10.79"


def test_uber_takes_the_pickup_and_dropoff_times_not_the_other_two():
    """收據上有**四個時間**：叫車 16:58、上車 17:01、下車 17:27、付款 17:28。

    直接抓第一個時間會把**叫車時間**當成上車時間（差三分鐘，看起來很合理，
    所以不會有人發現）。判準是「時間的下一行是地址」——只有上下車是這個形狀。
    """
    d = parser.parse_text(_UBER_TRIP)
    assert d["depart_time"] == "17:01", "抓到的可能是叫車時間"
    assert d["arrive_time"] == "17:27", "抓到的可能是付款時間"


def test_uber_addresses_drop_the_noise_but_keep_the_address():
    d = parser.parse_text(_UBER_TRIP)
    # 國碼 / 郵遞區號 / 重複的城市名要清掉
    assert d["origin"] == "測試市甲區一路1號", d["origin"]
    assert d["destination"] == "測試市乙區二街2號", d["destination"]


def test_uber_fee_invoice_is_detected_separately():
    assert parser.detect_kind(_UBER_INVOICE) == "uber_invoice"
    d = parser.parse_text(_UBER_INVOICE)
    assert d["kind"] == "uber_invoice"
    assert d["ticket_no"] == "AA00000000"
    assert d["buyer_tax_id"] == "11111111"
    assert d["fee_amount"] == 10
    assert d["date"] == "2026-08-18"


def test_the_invoice_is_not_mistaken_for_a_rail_ticket():
    """發票裡有「總計」「銷售額」這些字 —— 不可以被判成高鐵證明。"""
    assert parser.detect_kind(_UBER_INVOICE) != "thsrc"
    assert parser.detect_kind(_UBER_TRIP) not in ("thsrc", "tra")
