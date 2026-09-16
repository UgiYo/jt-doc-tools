"""頁面模式：差異的框要**真的壓在改掉的那幾個字上**。

## 判準是「框裡有沒有墨水」，不是「有沒有畫出框」

`/Rotate` 的頁面上，`get_text` 的座標跟算出來的圖**對不上**。實測同一頁設
不同旋轉角，把行的 bbox 換算成畫素之後量框內的墨水覆蓋率：

| 旋轉 | 直接用 bbox | 乘上 `page.rotation_matrix` |
|---:|---:|---:|
| 0 | 22.7% | 22.7% |
| 90 | **0.0%** | 22.7% |
| 180 | **0.0%** | 22.6% |
| 270 | 4.6% | 22.6% |

**不乘的話框會落在完全空白的地方，而頁面圖看起來完全正常** —— 只驗「有沒有
畫出框」的話這個 bug 會全綠。所以這裡一律量墨水。

## 中文要單獨驗

`get_text("words")` 對中文會把**整行當成一個詞**回傳（沒有空格）。用詞級座標
的話「改一個字」會把整行框起來 —— 所以另外釘住「框的寬度要接近一個字，
不可以是整行」。
"""
from __future__ import annotations

import io

import fitz
import numpy as np
import pytest

from app.core.font_catalog import best_cjk_path
import importlib

#: **不可以寫 `from app.tools.pdf_diff import router as R`** —— 那個套件的
#: `__init__.py` 把 `router` 這個名字綁成了 `APIRouter` 物件（不是模組），
#: 於是拿到的是路由器、`R._diff_pages` 直接 AttributeError。
R = importlib.import_module("app.tools.pdf_diff.router")


def _fontbuf() -> bytes:
    import fontTools.ttLib as ttlib
    picked = best_cjk_path("sans", "traditional")
    if not picked:
        pytest.skip("這台機器沒有中文字型，無法合成中文 PDF")
    path, idx = picked
    face = (ttlib.TTCollection(str(path))[idx]
            if str(path).lower().endswith(".ttc") else ttlib.TTFont(str(path)))
    buf = io.BytesIO()
    face.save(buf)
    return buf.getvalue()


def _doc(lines: list[str], rotation: int = 0) -> "fitz.Document":
    d = fitz.open()
    page = d.new_page()
    page.insert_font(fontname="cjk", fontbuffer=_fontbuf())
    for i, line in enumerate(lines):
        page.insert_text((60, 90 + 30 * i), line, fontname="cjk", fontsize=14)
    if rotation:
        page.set_rotation(rotation)
    return d


def _marks(a_lines, b_lines, rot_a=0, rot_b=0):
    da, db = _doc(a_lines, rot_a), _doc(b_lines, rot_b)
    pa, pb = R._page_lines(da), R._page_lines(db)
    ba, bb = R._page_boxes(da, pa), R._page_boxes(db, pb)
    d = R._diff_pages(pa[0], pb[0])
    ma = R._page_marks(d["a"], ba[0], da[0].rect)
    mb = R._page_marks(d["b"], bb[0], db[0].rect)
    return da, db, d, ma, mb


def _ink_in(page, rect_norm, dpi=150) -> float:
    """框裡有多少比例是墨水（`rect_norm` 是 0~1 的 x,y,w,h）。"""
    pm = page.get_pixmap(dpi=dpi)
    img = np.frombuffer(pm.samples, np.uint8).reshape(pm.height, pm.width, pm.n)
    x = int(rect_norm[0] * pm.width); y = int(rect_norm[1] * pm.height)
    w = max(1, int(rect_norm[2] * pm.width)); h = max(1, int(rect_norm[3] * pm.height))
    sub = img[max(0, y):y + h, max(0, x):x + w]
    if sub.size == 0:
        return -1.0
    return 100.0 * (sub.mean(axis=2) < 200).mean()


@pytest.mark.parametrize("rot", [0, 90, 180, 270])
def test_the_mark_really_sits_on_the_changed_characters(rot):
    """四種 `/Rotate` 都要把框畫在字上。"""
    a = ["合約金額為新臺幣壹佰萬元整", "其餘條款不變"]
    b = ["合約金額為新臺幣貳佰萬元整", "其餘條款不變"]
    da, db, d, ma, mb = _marks(a, b, rot_a=rot, rot_b=rot)
    assert ma and mb, f"rotation={rot} 一個框都沒有"
    inks = [_ink_in(da[0], r) for m in ma for r in m["rects"]]
    assert max(inks) > 8.0, (
        f"rotation={rot}：框裡幾乎沒有墨水（最高 {max(inks):.1f}%）—— "
        "座標大概沒有乘上 page.rotation_matrix，框落在空白處了")
    da.close(); db.close()


def test_one_changed_chinese_character_is_not_a_whole_line_box():
    """中文改一個字，框就該是一個字寬 —— 用詞級座標的話會框整行。"""
    a = ["合約金額為新臺幣壹佰萬元整"]
    b = ["合約金額為新臺幣貳佰萬元整"]
    da, db, d, ma, mb = _marks(a, b)
    widths = [r[2] for m in ma for r in m["rects"]]
    assert widths, "沒有框"
    line_w = max(fitz.Rect(x).width for x in [da[0].rect])
    # 那一行 13 個字；一個字大約是行寬的 1/13。給寬一點的上限（3 個字）。
    assert max(widths) < 0.25, (
        f"框佔了頁寬的 {max(widths)*100:.0f}% —— 像是整行被框起來了（中文要走字元級）")
    da.close(); db.close()


def test_identical_documents_produce_no_marks():
    """反向對照：兩份一樣的檔案必須一個框都沒有。

    沒有這一條的話，把判準放寬到「每一行都畫框」也會過。
    """
    lines = ["第一行內容", "第二行內容", "第三行內容"]
    da, db, d, ma, mb = _marks(lines, lines)
    assert ma == [] and mb == [], f"相同的檔案卻畫了框：{ma} / {mb}"
    da.close(); db.close()


def test_a_deleted_line_is_marked_on_the_old_side_only():
    a = ["保留這一行", "這一行會被刪掉", "也保留"]
    b = ["保留這一行", "也保留"]
    da, db, d, ma, mb = _marks(a, b)
    tags_a = {m["tag"] for m in ma}
    assert "delete" in tags_a, f"舊版那側沒有標出被刪掉的行：{ma}"
    ink = max(_ink_in(da[0], r) for m in ma for r in m["rects"])
    assert ink > 8.0, f"框內墨水只有 {ink:.1f}%"
    da.close(); db.close()


def test_a_page_without_a_text_layer_yields_no_marks_instead_of_wrong_ones():
    """抽不到文字時要**沒有框**，不是畫在猜的位置上。

    畫面那邊會顯示「抽不到文字座標」的提示 —— 「沒有框」跟「這頁沒改」
    長得一模一樣，所以提示不可以省。
    """
    d = fitz.open()
    page = d.new_page()
    page.draw_rect(fitz.Rect(60, 60, 400, 300), color=None, fill=(0.4, 0.4, 0.4))
    pages = R._page_lines(d)
    boxes = R._page_boxes(d, pages)
    marks = R._page_marks([{"text": "x", "tag": "delete", "i": 0}],
                          boxes[0], d[0].rect)
    assert marks == [], "沒有文字層卻畫出了框"
    d.close()


def test_the_text_diff_itself_is_unchanged_by_the_coordinate_work():
    """零退步：加了座標之後，文字比對的輸出（文字與 tag）必須一模一樣。"""
    a = ["第一行", "第二行舊", "第三行"]
    b = ["第一行", "第二行新", "第三行"]
    d = R._diff_pages(a, b)
    assert [r["text"] for r in d["a"]] == a
    assert [r["text"] for r in d["b"]] == b
    assert [r["tag"] for r in d["a"]] == ["equal", "replace", "equal"]
    assert d["changed"] == 1 and d["added"] == 0 and d["removed"] == 0


# --------------------------------------------------------------------------
# 頁面配對（v1.15.58）：插一頁不可以讓後面每一頁都變成「整頁不同」
# --------------------------------------------------------------------------

def _pages(lines_per_page: list[list[str]]) -> list[list[str]]:
    return lines_per_page


def test_inserting_a_page_only_reports_that_page():
    """**依索引配對時實測 20 頁的文件插一頁 → 19 頁被判成整頁不同。**

    使用者看到的是「整份都改了」，而實際上只多了一頁。
    """
    a = [["第 %d 頁的內容" % i, "同樣的第二行"] for i in range(1, 9)]
    b = a[:2] + [["插進來的新頁"]] + a[2:]
    pairs = R._pair_pages(a, b)
    paired = [(x, y) for x, y in pairs if x is not None and y is not None]
    assert len(paired) == len(a), f"只配對到 {len(paired)} 頁，應該是 {len(a)} 頁"
    added = [y for x, y in pairs if x is None]
    assert added == [2], f"新增的應該只有第 3 頁（索引 2），實際 {added}"


def test_deleting_a_page_only_reports_that_page():
    a = [["第 %d 頁" % i] for i in range(1, 7)]
    b = a[:3] + a[4:]
    pairs = R._pair_pages(a, b)
    removed = [x for x, y in pairs if y is None]
    assert removed == [3], f"刪掉的應該只有索引 3，實際 {removed}"


def test_a_changed_page_still_pairs_up():
    """改過的頁面夾在沒改的頁面之間 —— 靠錨點就對得上，不需要模糊相似度。"""
    a = [["第一頁"], ["原本的第二頁"], ["第三頁"]]
    b = [["第一頁"], ["改過的第二頁"], ["第三頁"]]
    assert R._pair_pages(a, b) == [(0, 0), (1, 1), (2, 2)]


def test_identical_documents_pair_one_to_one():
    a = [["a"], ["b"], ["c"]]
    assert R._pair_pages(a, list(a)) == [(0, 0), (1, 1), (2, 2)]
