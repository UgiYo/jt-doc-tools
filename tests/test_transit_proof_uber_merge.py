"""Uber 的處理費發票要**併進同一趟行程**，不可以自成一列。

## 由來

使用者 2026-09-13 提供兩份真實檔案（同一筆行程）要求支援 Uber：

* **行程收據** —— 里程、上下車時間與地址、車牌、總計。
* **電子發票證明聯** —— 只開「Uber 處理費」那 10 元
  （計程車行程本身不開電子發票，收據上就這樣寫著）。

關鍵事實：**行程收據的「總計」已經含了那 10 元**
（行程費用 413 ＋ 處理費 10 − 點數折抵 13 ＝ 總計 410）。

所以那張發票若變成清單上的第二列，報帳金額就會**重複計算 10 元** ——
而且畫面上看起來完全合理（兩份檔案、兩列），沒有人會發現。
它要做的事是把**發票號碼與買方統編**補到那趟行程上（報帳要的就是這兩個）。

找不到對應行程時**才**留成獨立一列 —— 不然使用者會以為檔案傳丟了。
"""
from __future__ import annotations

import pytest

from app.tools.transit_proof import buffer


def _trip(date: str = "2026-08-18"):
    return {"transport": "Uber", "date": date, "depart_time": "17:01",
            "arrive_time": "17:27", "origin": "測試市甲區一路1號",
            "destination": "測試市乙區二街2號", "fare": 410,
            "vehicle": "AAA000", "distance": "10.79", "ticket_no": ""}


def _invoice(date: str = "2026-08-18"):
    return {"kind": "uber_invoice", "transport": "Uber 處理費", "date": date,
            "fare": 10, "fee_amount": 10, "ticket_no": "AA00000000",
            "buyer_tax_id": "11111111", "note": "Uber 處理費電子發票"}


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(buffer, "_files_dir", lambda u: tmp_path / "files")
    monkeypatch.setattr(buffer, "_buffer_path", lambda u: tmp_path / "buf.json")


def test_uploading_both_files_gives_one_row_not_two():
    r = buffer.add_entries("alice", [_trip(), _invoice()])
    rows = buffer.list_entries("alice")
    assert len(rows) == 1, f"變成 {len(rows)} 列 —— 報帳金額會重複計算"
    assert rows[0]["fare"] == 410
    assert r["merged_invoices"] == 1


def test_the_invoice_number_and_tax_id_land_on_the_trip():
    buffer.add_entries("alice", [_trip(), _invoice()])
    row = buffer.list_entries("alice")[0]
    assert row["ticket_no"] == "AA00000000", "發票號碼沒補上去，報帳時就找不到"
    assert row["buyer_tax_id"] == "11111111"
    assert "處理費發票" in (row.get("note") or "")


def test_the_invoice_merges_even_when_uploaded_later():
    """**分兩次上傳也要併**。

    使用者很可能先傳收據、之後才收到發票 —— 只處理「同一批」的話，
    第二次上傳就會多出一列，而那正是重複計算的情形。
    """
    buffer.add_entries("alice", [_trip()])
    r = buffer.add_entries("alice", [_invoice()])
    rows = buffer.list_entries("alice")
    assert len(rows) == 1, "分兩次上傳沒有併進去"
    assert rows[0]["ticket_no"] == "AA00000000"
    assert r["merged_invoices"] == 1


def test_a_stray_invoice_is_kept_as_its_own_row():
    """對不到行程時**不可以安靜吞掉** —— 使用者會以為檔案傳丟了。"""
    buffer.add_entries("alice", [_invoice("2026-08-19")])
    rows = buffer.list_entries("alice")
    assert len(rows) == 1
    assert rows[0]["transport"] == "Uber 處理費"
    assert rows[0]["fare"] == 10


def test_a_rail_ticket_on_the_same_day_is_not_touched():
    """反向對照：同一天的台鐵票不可以被當成 Uber 行程而被併入。"""
    rail = {"transport": "台鐵", "date": "2026-08-18", "origin": "臺北",
            "destination": "臺中", "fare": 375, "ticket_no": "N123"}
    buffer.add_entries("alice", [rail, _invoice()])
    rows = buffer.list_entries("alice")
    assert len(rows) == 2, "發票被併進台鐵那一列了"
    rail_row = [r for r in rows if r["transport"] == "台鐵"][0]
    assert rail_row["ticket_no"] == "N123", "台鐵的票號被發票號碼蓋掉了"


# ---------------------------------------------------------------------------
# 去重：Uber 的收據**沒有票號**（2026-09-13 使用者說明實際用法只拉收據）
#
# 鐵路票有票號，所以去重一向走票號那條。Uber 沒有 —— 退而用
# 「交通工具＋日期＋起訖＋車資」的話，**同一天同路線同車資的第二趟會被
# 判成重複而安靜丟掉**（通勤來回、車資相同，計程車上很常見）。
#
# 收據裡其實有唯一識別：第一頁那個 `riders.uber.com/trips/<行程編號>` 連結。
# 它在文字層看不到，只在連結註解裡 —— 所以抽文字時要一併抽連結。
# ---------------------------------------------------------------------------

def test_two_different_trips_on_the_same_day_are_both_kept():
    a = dict(_trip(), trip_id="aaaaaaaa-0000-0000-0000-000000000001",
             depart_time="08:10", arrive_time="08:35")
    b = dict(_trip(), trip_id="bbbbbbbb-0000-0000-0000-000000000002",
             depart_time="18:10", arrive_time="18:35")
    buffer.add_entries("alice", [a, b])
    assert len(buffer.list_entries("alice")) == 2, "第二趟被當成重複丟掉了"


def test_the_same_receipt_twice_is_still_one_row():
    a = dict(_trip(), trip_id="aaaaaaaa-0000-0000-0000-000000000001")
    buffer.add_entries("alice", [a])
    r = buffer.add_entries("alice", [dict(a)])
    assert r["duplicates"] == 1
    assert len(buffer.list_entries("alice")) == 1


def test_without_a_trip_id_the_time_still_separates_two_rides():
    """連結掉了（例如收據被重新列印成 PDF）時的退路。"""
    a = dict(_trip(), depart_time="08:10")
    b = dict(_trip(), depart_time="18:10")
    buffer.add_entries("alice", [a, b])
    assert len(buffer.list_entries("alice")) == 2, "沒有行程編號時，時間要能分辨兩趟"
