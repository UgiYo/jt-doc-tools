"""把「哪幾個字改了」對回**頁面上的座標**，給「頁面模式」畫框用。

文字比對本身不動（`get_text("text")` ＋ `difflib`，逐行）——
這支只負責「第 N 行的第 i~j 個字在頁面的哪裡」。

## 為什麼是**字元級**不是詞級

`get_text("words")` 對中文會把**整行當成一個「詞」**回傳（中文沒有空格，
實測一整行 34 個字是一個 word）。用它標示的話，**改一個字會把整行框起來**。
所以座標一律從 `get_text("rawdict")` 的每字 bbox 取。

## ⚠ `/Rotate` 的頁面，文字座標跟算出來的圖對不上

實測同一頁設不同旋轉角，把行的 bbox 換算成畫素之後量「框裡有多少墨水」：

| 旋轉 | 直接用 bbox | 乘上 `page.rotation_matrix` |
|---:|---:|---:|
| 0 | 22.7% | 22.7% |
| 90 | **0.0%** | 22.7% |
| 180 | **0.0%** | 22.6% |
| 270 | 4.6% | 22.6% |

不乘的話框會落在**完全空白的地方**，而頁面圖看起來完全正常 ——
沒有人會發現。所以這裡一律乘，而且驗收要用「框內墨水覆蓋率」當判準，
不是「有沒有畫出框」。

## 行的順序

`rawdict` 的**非空行**順序與內容跟 `get_text("text")` 完全相同
（5 份真實 PDF 15 頁 ＋ 4 份 Office 檔 6 頁實測，全部逐行相同）。
所以比對照舊用 `get_text("text")`（行為零改變），這裡只負責提供座標，
兩邊靠「第幾個非空行」對起來。
"""
from __future__ import annotations

from typing import Iterable

import fitz


#: 同一行裡的字要斷成不同的框：換行，或字跟字之間空得比這個還開（pt）。
_GAP_PT = 3.0
#: 同一行的 y 差超過這個就當成換行（pt）。
_LINE_PT = 2.0


def line_char_boxes(page: "fitz.Page") -> list[tuple[str, list[tuple[float, float, float, float]]]]:
    """回 `[(行文字, [每個字的 bbox])]` —— **只收非空行**，座標已套旋轉。

    行文字**不做 rstrip 以外的處理**，才對得上 `get_text("text")` 那一份。
    """
    rot = page.rotation_matrix
    out: list[tuple[str, list[tuple[float, float, float, float]]]] = []
    for blk in page.get_text("rawdict").get("blocks", []):
        for ln in blk.get("lines", []):
            text, boxes = "", []
            for sp in ln.get("spans", []):
                for ch in sp.get("chars", []):
                    text += ch["c"]
                    r = fitz.Rect(ch["bbox"]) * rot
                    boxes.append((r.x0, r.y0, r.x1, r.y1))
            if text.strip():
                # rstrip 會讓文字與 boxes 長度對不上 —— 只在**比對用的字串**上
                # rstrip，boxes 保持原樣，用索引取值時再夾住範圍。
                out.append((text.rstrip(), boxes))
    return out


def char_range_rects(boxes: Iterable[tuple[float, float, float, float]],
                     start: int, end: int) -> list[tuple[float, float, float, float]]:
    """第 `start`~`end` 個字的框；跨行或中間空太開就切成多個。

    `start == end`（純插入，原文那一側沒有字）時退回「插入點左右各半個字寬」，
    否則那一側會完全沒有框 —— 使用者看不出「這裡少了東西」。
    """
    bl = list(boxes)
    if not bl:
        return []
    start = max(0, min(start, len(bl)))
    end = max(start, min(end, len(bl)))
    sel = bl[start:end]
    if not sel:                       # 純插入：標在插入點上
        i = min(start, len(bl) - 1)
        x0, y0, x1, y1 = bl[i]
        w = max((x1 - x0) * 0.5, 1.0)
        anchor = x0 if start <= i else x1
        return [(anchor - w / 2, y0, anchor + w / 2, y1)]
    runs: list[list[tuple[float, float, float, float]]] = [[sel[0]]]
    for b in sel[1:]:
        prev = runs[-1][-1]
        if abs(b[1] - prev[1]) > _LINE_PT or b[0] - prev[2] > _GAP_PT:
            runs.append([b])
        else:
            runs[-1].append(b)
    return [(min(x[0] for x in r), min(x[1] for x in r),
             max(x[2] for x in r), max(x[3] for x in r)) for r in runs]


def normalise(rect: tuple[float, float, float, float],
              page_rect: "fitz.Rect") -> list[float]:
    """換成 0~1 的比例 —— **不要送畫素**。

    前端顯示的是縮小圖，送畫素的話換個顯示尺寸就全錯（`doc-straighten`
    的四點拖曳踩過同一條）。
    """
    w = page_rect.width or 1.0
    h = page_rect.height or 1.0
    x0, y0, x1, y1 = rect
    return [round(x0 / w, 5), round(y0 / h, 5),
            round((x1 - x0) / w, 5), round((y1 - y0) / h, 5)]
