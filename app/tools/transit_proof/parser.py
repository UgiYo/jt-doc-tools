"""解析台鐵 / 高鐵 / Uber 的乘車證明 PDF → 結構化 dict。

支援兩種官方憑證：
  - 台灣高鐵「電子車票證明」（THSRC）：label ：value 版面，好抓。
    乘車日期 / 起程站 / 到達站 / 票價 / 銷售額 / 營業稅額 / 卡號票號 / 統一編號。
  - 台鐵「購票證明」（TRA）：表格版面，PyMuPDF 抽出的文字順序會打散，
    因此一律用「特徵正則」直接抓值（不依賴行順序）：
    票號 / 乘車日 / 乘車區間（含起訖時間與站名）/ 車種車次 / 票種 / 票價。

回傳 dict 欄位（缺的給 None / ""）：
  transport      "高鐵" | "台鐵"
  date           ISO "YYYY-MM-DD"
  depart_time    "HH:MM"（發車）
  arrive_time    "HH:MM"（到達；高鐵證明無到達時間 → ""）
  origin         起站（簡化站名）
  destination    到站（簡化站名）
  fare           票價（int）
  amount_untaxed 銷售額（int，高鐵有）
  tax            營業稅額（int，高鐵有）
  train          車種 / 車次（台鐵有）
  ticket_type    票種（台鐵有）
  ticket_no      票號 / 卡號
  buyer_tax_id   統一編號（高鐵有）
"""
from __future__ import annotations

import re
from typing import Optional


class ParseError(Exception):
    pass


def _int(s) -> Optional[int]:
    if s is None:
        return None
    m = re.search(r"-?\d[\d,]*", str(s))
    if not m:
        return None
    try:
        return int(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _simplify_station(name: str) -> str:
    """高鐵站名精簡：去「高鐵」前綴 + 「車站」/「站」後綴 → 只留地名。
    台鐵站名（臺北 / 臺中 …）本就簡潔，原樣返回。"""
    s = (name or "").strip()
    s = re.sub(r"^高鐵", "", s)
    s = re.sub(r"車站$", "", s)
    s = re.sub(r"站$", "", s)
    return s.strip()


def detect_kind(text: str) -> Optional[str]:
    """判斷憑證類型：'thsrc'（高鐵）/ 'tra'（台鐵）/
    'uber_trip'（Uber 行程收據）/ 'uber_invoice'（Uber 處理費電子發票）/ None。

    **Uber 要先判**：它的收據裡有「車行／車隊」「車牌號碼」這些字，
    而台鐵那條是用「車次」之類的特徵字比對的，順序反過來會誤判。
    """
    # Uber 處理費的電子發票（計程車行程本身不開發票，只有處理費開）
    if "電子發票證明聯" in text and ("優步" in text or "Uber" in text):
        return "uber_invoice"
    if ("Uber" in text or "優步" in text) and (
            "行程詳細資訊" in text or "行程費用" in text
            or "感謝您的搭乘" in text or "車行／車隊" in text):
        return "uber_trip"
    if "高鐵" in text or "THSRC" in text or "thsrc" in text.lower():
        return "thsrc"
    if "購票證明" in text or "車次" in text or "臺鐵" in text or "台鐵" in text:
        return "tra"
    return None


#: 「上午/下午 H:MM」→ 24 小時制。
_AMPM = re.compile(r"(上午|下午)\s*(\d{1,2}):(\d{2})")


def _to_24h(ampm: str, hh: int, mm: str) -> str:
    if ampm == "下午" and hh != 12:
        hh += 12
    elif ampm == "上午" and hh == 12:
        hh = 0
    return f"{hh:02d}:{mm}"


def _clean_address(s: str) -> str:
    """把 Uber 地址前面的雜訊清掉，只留真正的地址。

    實際看到的前綴有好幾種（使用者 2026-09-13 截圖回報「有的有 TW 有的有
    Taiwan」）：`TWN`、`TW`、`Taiwan`、`台灣`，而且**郵遞區號可能在國名前面
    也可能在後面**，城市名還會重複一次。所以要**反覆剝**，不是剝一次。

    形狀（**杜撰的示意，不是真實地址**）：
        `TWN某某市某某市甲區一路1號`
        `00000台灣某某市乙區二街2號`
        `Taiwan某某市甲區一路1號`

    **只清掉確定是雜訊的部分** —— 里名、巷弄、樓層對報帳的人可能有用，
    不要自作主張刪掉。
    """
    s = (s or "").strip()
    # 反覆剝：國名 / 國碼 / 郵遞區號可能交錯出現，剝一次不夠
    for _ in range(4):
        before = s
        # **不可以用 `\b`**：中文字在 Python 眼裡也是 word 字元，
        # 所以「TWN台中市」的 N 與 台 之間**沒有邊界**，整條規則會一次都不生效
        # （實測：TWN / TW / Taiwan 三種前綴全都沒剝掉）。
        # 長的要排在短的前面，否則 `TW` 會先吃掉 `Taiwan` 的前兩個字母。
        s = re.sub(r"^(?:Taiwan|TWN|TW|R\.?O\.?C\.?|台灣|臺灣)[,，\s]*", "", s,
                   flags=re.IGNORECASE)
        s = re.sub(r"^\d{3,6}[-\s]*", "", s)        # 郵遞區號（3 / 5 / 6 碼）
        s = s.lstrip(",， \t")
        if s == before:
            break
    # 重複的城市名：「台中市台中市」「臺中市台中市」——
    # **台 / 臺 要視為同一個字**，不然只有寫法一致時才清得掉。
    m = re.match(r"^([台臺])([一-鿿]{1,2}[市縣])(.*)$", s)
    if m:
        rest = m.group(3)
        m2 = re.match(r"^[台臺]" + re.escape(m.group(2)), rest)
        if m2:
            s = m.group(1) + m.group(2) + rest[m2.end():]
    else:
        m3 = re.match(r"^([一-鿿]{2,3}[市縣])\1(.*)$", s)
        if m3:
            s = m3.group(1) + m3.group(2)
    return s.strip()


#: 行程明細裡，時間下一行**不會是**這些（它們是金額、標籤或另一個時間）
_NOT_A_PLACE = re.compile(
    r"^\s*(?:\$|NT\$|總計|款項|行程費用|車牌號碼|車行|Uber|由.+提供|"
    r"[0-9.]+\s*公里|上午|下午|\d{1,2}:\d{2}|$)")


def _looks_like_place(line: str) -> bool:
    """這一行看起來是「地點」嗎？

    ⚠ **不可以要求它長得像地址。** Uber 的上下車地點有時候是**地標名稱**
    （例如車站、賣場、大樓名），沒有路名也沒有門牌 —— 用地址的樣子去比對，
    那一站就會被丟掉，表格上只出現一個地點
    （2026-09-13 使用者截圖回報，同一批裡有好幾列是這樣）。

    判準反過來寫：**排除**明顯不是地點的那幾種（金額、標籤、里程、另一個時間）。
    """
    s = (line or "").strip()
    if not s or len(s) < 3:
        return False
    return not _NOT_A_PLACE.match(s)


def parse_uber_trip(text: str) -> dict:
    """Uber 行程收據（兩頁：第一頁金額與付款，第二頁行程明細）。

    ⚠ **時間要取行程明細那一組**。第一頁還有「叫車時間」與「付款時間」
    （實測是 16:58 與 17:28），直接抓第一個時間會把叫車時間當成上車時間。
    判準是「**時間的下一行是地址**」—— 只有上下車那兩個是這個形狀。
    """
    date = ""
    m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
    if not m:
        m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", text)
    if m:
        date = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    lines = [ln.strip() for ln in (text or "").splitlines()]
    # **只看「行程詳細資訊」之後那一段**。第一頁還有叫車時間與付款時間
    # （實測 16:58 與 17:28），從整份找的話第一個時間就是叫車時間 ——
    # 差三分鐘、看起來完全合理，不會有人發現。
    start = 0
    for i, ln in enumerate(lines):
        if "行程詳細資訊" in ln or "Trip details" in ln:
            start = i + 1
            break
    stops: list[tuple[str, str]] = []           # (時間, 地點)
    for i in range(start, len(lines) - 1):
        ln = lines[i]
        tm = _AMPM.fullmatch(ln.replace(" ", "")) or _AMPM.fullmatch(ln)
        if not tm:
            continue
        nxt = lines[i + 1]
        if _looks_like_place(nxt):
            stops.append((_to_24h(tm.group(1), int(tm.group(2)), tm.group(3)),
                          _clean_address(nxt)))
    depart = stops[0] if stops else ("", "")
    arrive = stops[-1] if len(stops) > 1 else ("", "")

    # 「總計」那一行底下的金額才是實付（行程費用 / 處理費 / 點數折抵是明細）
    fare = None
    for i, ln in enumerate(lines[:-1]):
        if ln.strip() in ("總計", "Total"):
            fare = _int(lines[i + 1])
            break
    if fare is None:
        fare = _int(re.search(r"\$\s*([\d,]+(?:\.\d+)?)", text).group(1)
                    if re.search(r"\$\s*([\d,]+(?:\.\d+)?)", text) else None)

    plate = ""
    pm = re.search(r"車牌號碼[：:]\s*\n?\s*([A-Z0-9-]{5,10})", text)
    if pm:
        plate = pm.group(1).strip()
    dist = ""
    dm = re.search(r"([\d.]+)\s*公里", text)
    if dm:
        dist = dm.group(1)
    fleet = ""
    fm = re.search(r"車行／車隊[：:]?\s*\n?\s*(.+)", text)
    if fm:
        fleet = fm.group(1).strip()

    # 行程編號（去重用）—— 在連結裡，不在文字層
    trip_id = ""
    tm = re.search(r"riders\.uber\.com/trips/([0-9a-fA-F-]{16,40})", text)
    if tm:
        trip_id = tm.group(1)

    return {
        "transport": "Uber",
        "trip_id": trip_id,
        "date": date,
        "depart_time": depart[0],
        "arrive_time": arrive[0],
        "origin": depart[1],
        "destination": arrive[1],
        "fare": fare,
        "amount_untaxed": None,
        "tax": None,
        "train": "",
        "ticket_type": "",
        "ticket_no": "",          # 行程收據沒有票號；發票號碼由電子發票那份補
        "buyer_tax_id": "",
        "vehicle": plate,
        "distance": dist,
        "note": fleet,
    }


def parse_uber_invoice(text: str) -> dict:
    """Uber **處理費**的電子發票證明聯。

    ⚠ **這不是一趟行程** —— 行程收據的「總計」已經含了這筆處理費
    （實測：行程費用 ＋ 處理費 − 點數折抵 ＝ 總計）。把它當成獨立一列
    會讓報帳金額重複計算。所以它的 `fare` 記在 `fee_amount`，
    併進同一天那趟 Uber 時只補發票號碼與統編（見 `buffer.add_entries`）。
    """
    inv = ""
    m = re.search(r"發票號碼[：:]\s*([A-Z]{2}-?\d{8})", text)
    if not m:
        m = re.search(r"\b([A-Z]{2}-\d{8})\b", text)
    if m:
        inv = m.group(1).replace("-", "")
    date = ""
    dm = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if dm:
        date = f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)}"
    amt = None
    am = re.search(r"總計\s*[:：]\s*(\d[\d,]*)", text)
    if am:
        amt = _int(am.group(1))
    buyer = ""
    bm = re.search(r"買方\s*[:：]\s*(\d{8})", text)
    if bm:
        buyer = bm.group(1)
    seller = ""
    sm = re.search(r"賣方\s*[:：]\s*(\d{8})", text)
    if sm:
        seller = sm.group(1)
    return {
        "kind": "uber_invoice",
        "transport": "Uber 處理費",
        "date": date,
        "depart_time": "",
        "arrive_time": "",
        "origin": "",
        "destination": "",
        "fare": amt,
        "fee_amount": amt,
        "amount_untaxed": None,
        "tax": None,
        "train": "",
        "ticket_type": "",
        "ticket_no": inv,
        "buyer_tax_id": buyer,
        "seller_tax_id": seller,
        "note": "Uber 處理費電子發票",
    }


def _thsrc_field(text: str, label: str) -> str:
    """抓高鐵『label ： value』一行的 value（到行尾）。"""
    m = re.search(rf"{re.escape(label)}\s*[:：]\s*(.*)", text)
    return m.group(1).strip() if m else ""


def parse_thsrc(text: str) -> dict:
    ride = _thsrc_field(text, "乘車日期")   # 2026-06-09 07:20:00
    date, dtime = "", ""
    m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?", ride)
    if m:
        date = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        if m.group(4):
            dtime = f"{int(m.group(4)):02d}:{m.group(5)}"
    origin = _simplify_station(_thsrc_field(text, "起程站"))
    dest = _simplify_station(_thsrc_field(text, "到達站"))
    return {
        "transport": "高鐵",
        "date": date,
        "depart_time": dtime,
        "arrive_time": "",
        "origin": origin,
        "destination": dest,
        "fare": _int(_thsrc_field(text, "票價")),
        "amount_untaxed": _int(_thsrc_field(text, "銷售額")),
        "tax": _int(_thsrc_field(text, "營業稅額")),
        "train": "",
        "ticket_type": "",
        "ticket_no": _thsrc_field(text, "卡號/票號") or _thsrc_field(text, "票號"),
        "buyer_tax_id": _thsrc_field(text, "統一編號"),
    }


def parse_tra(text: str) -> dict:
    # 票號：一個英文字母 + 一長串數字（例：N 開頭 + 14 碼）
    m = re.search(r"\b([A-Z]\d{10,})\b", text)
    ticket_no = m.group(1) if m else ""

    # 乘車日：所有 yyyy/mm/dd 中，排除「印製日期」的那個。
    printed = ""
    mp = re.search(r"印製日期\s*\n?\s*(\d{4}/\d{1,2}/\d{1,2})", text)
    if mp:
        printed = mp.group(1)
    date = ""
    for md in re.finditer(r"(\d{4})/(\d{1,2})/(\d{1,2})", text):
        raw = md.group(0)
        if raw == printed:
            continue
        date = f"{int(md.group(1)):04d}-{int(md.group(2)):02d}-{int(md.group(3)):02d}"
        break
    # 若只有一個日期（沒印製日期標籤），退而取第一個
    if not date and printed:
        md = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})", printed)
        if md:
            date = f"{int(md.group(1)):04d}-{int(md.group(2)):02d}-{int(md.group(3)):02d}"

    # 乘車區間：18:41 臺北 > 20:50 臺中（> 可能是全形＞）
    origin = dest = dtime = atime = ""
    mr = re.search(
        r"(\d{1,2}:\d{2})\s*([^\s>＞]+)\s*[>＞]\s*(\d{1,2}:\d{2})\s*([^\s\n]+)", text)
    if mr:
        dtime, origin, atime, dest = (mr.group(1), mr.group(2).strip(),
                                      mr.group(3), mr.group(4).strip())

    # 車種 + 車次：自強(3000) … 477 車次
    # (?<!乘車) 排除「乘車區間」label 裡的「區間」被誤當車種（它排在真正車種之前）。
    train = ""
    mt = re.search(r"(?<!乘車)(自強|莒光|復興|普悠瑪|太魯閣|新自強|PP自強|EMU\d*|區間快|區間)"
                   r"\s*(\([^)]*\))?", text)
    car = re.search(r"(\d+)\s*車次", text)
    if mt:
        train = mt.group(1) + (mt.group(2) or "")
    if car:
        train = (train + f" {car.group(1)}車次").strip()

    # 票種：全票 / 孩童 / 敬老 …（可能後面接 (商務) / (自由座)）
    ticket_type = ""
    mk = re.search(r"(全票|孩童|敬老|愛心|優待|團體|軍警)\s*(\([^)]*\))?", text)
    if mk:
        ticket_type = mk.group(1) + (mk.group(2) or "")

    # 票價：950 元
    fare = None
    mf = re.search(r"(\d[\d,]*)\s*元", text)
    if mf:
        fare = _int(mf.group(1))

    return {
        "transport": "台鐵",
        "date": date,
        "depart_time": dtime,
        "arrive_time": atime,
        "origin": origin,
        "destination": dest,
        "fare": fare,
        "amount_untaxed": None,
        "tax": None,
        "train": train,
        "ticket_type": ticket_type,
        "ticket_no": ticket_no,
        "buyer_tax_id": "",
    }


def parse_text(text: str) -> dict:
    """依偵測到的類型解析。抓不到任何有效欄位 → ParseError。"""
    kind = detect_kind(text or "")
    if kind == "thsrc":
        d = parse_thsrc(text)
    elif kind == "tra":
        d = parse_tra(text)
    elif kind == "uber_trip":
        d = parse_uber_trip(text)
    elif kind == "uber_invoice":
        d = parse_uber_invoice(text)
    else:
        raise ParseError("無法辨識為台鐵 / 高鐵 / Uber 乘車證明")
    # 至少要有日期或起訖或票價，否則視為解析失敗
    if not (d.get("date") or d.get("origin") or d.get("fare")):
        raise ParseError("辨識到憑證類型，但抽不到有效欄位（版面可能不同）")
    # 會計科目預設「旅費」（交通票券報帳慣例）；可在表格內編輯調整。
    d.setdefault("subject", "旅費")
    return d
