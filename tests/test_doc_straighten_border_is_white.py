"""旋轉 / 透視補在邊緣的顏色必須是白的，不可以是紅的。

2026-09-15 使用者看到修正後的名片「四邊都有截到背景一些」。**那不是背景**
—— 是我們自己填上去的：

    cv2.warpAffine(..., borderValue=255)

OpenCV 的 `borderValue` 收的是 `Scalar`（四個數）。只寫 `255` 會被展開成
`(255, 0, 0, 0)`：

* 灰階（1 通道）—— 只用到第一個，**白色，正確**。
* 彩色（3 通道）—— `(255, 0, 0)`，**純紅**。

v1.15.47 把幾何從灰階改成「量在灰階、做在彩色」之後，這一行的意義就悄悄
變了，而**灰階的測試全部照樣綠**。實測那張名片：純紅畫素 5,628 個，
最外 2 px 的框有 43% 偏色（平均 chroma 43.8，紙面只有 4.2）。

## 判準

**看產出的畫素**，不是看參數怎麼寫 —— 寫 `(255, 255, 255)` 或
`_BORDER_WHITE` 都對，寫 `255` 不對，而字面比對分不出「這是幾通道的圖」。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

cv2 = pytest.importorskip("cv2")
from app.tools.doc_straighten import straighten_core as C  # noqa: E402


def _reddish(img: np.ndarray) -> int:
    """明顯偏紅的畫素個數（紅高、綠藍都低）。"""
    r = img[:, :, 0].astype(int)
    g = img[:, :, 1].astype(int)
    b = img[:, :, 2].astype(int)
    return int(((r > 200) & (g < 90) & (b < 90)).sum())


def _ring_chroma(img: np.ndarray, px: int = 2) -> float:
    """最外 `px` 圈的平均色度。紙與墨水都是中性色，桌面 / 填色不是。"""
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
    ch = np.hypot(lab[:, :, 1].astype(np.float32) - 128,
                  lab[:, :, 2].astype(np.float32) - 128)
    h, w = ch.shape
    m = np.zeros((h, w), bool)
    m[:px] = m[-px:] = True
    m[:, :px] = m[:, -px:] = True
    return float(ch[m].mean())


def _photo() -> np.ndarray:
    """一張合成照片：**彩色**的桌面上放一張白紙，紙上有黑字，整體歪 3°。"""
    desk = np.zeros((900, 1200, 3), np.uint8)
    desk[:, :] = (150, 80, 40)                      # 木頭色的桌面（明顯偏色）
    paper = np.full((520, 760, 3), 250, np.uint8)
    for i in range(6):
        y = 70 + i * 70
        cv2.rectangle(paper, (60, y), (700, y + 26), (30, 30, 30), -1)
    M = cv2.getRotationMatrix2D((380, 260), 3.0, 1.0)
    rot = cv2.warpAffine(paper, M, (760, 520), borderValue=(150, 80, 40))
    desk[190:710, 220:980] = rot
    return desk


def test_rotate_fills_the_edge_with_white_not_red():
    """最小重現：彩色圖轉一個角度，露出來的那一圈必須是白的。"""
    img = np.full((200, 300, 3), 240, np.uint8)
    out = C.rotate(img, 5.0)
    assert _reddish(out) == 0, (
        f"旋轉補邊補成了紅色（{_reddish(out)} 個畫素）—— "
        "`borderValue=255` 在彩色圖上是 (255, 0, 0)")
    corner = out[0, 0].tolist()
    assert min(corner) > 200, f"左上角補的不是白色：{corner}"


def test_a_grayscale_rotate_still_fills_with_white():
    """灰階那條路不可以被改壞（它本來就是對的）。"""
    out = C.rotate(np.full((200, 300), 240, np.uint8), 5.0)
    assert int(out[0, 0]) > 200, f"灰階補邊變成 {out[0, 0]}"


def test_a_straightened_colour_page_has_no_red_frame():
    """端到端：**把產出打開來看畫素**，不是看參數。"""
    rgb = _photo()
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    out, _res = C.straighten_page(gray, rgb=rgb, dpi=150, detect_quad=True)
    assert out.ndim == 3, "彩色進去應該彩色出來"
    assert _reddish(out) == 0, f"修正後有 {_reddish(out)} 個紅畫素"


def test_the_outer_ring_is_neutral_after_a_perspective_crop():
    """抓到紙張邊界時，最外一圈應該是紙不是桌面。

    **這條要跟上面那條分開**：紅色補邊是我們自己畫的，框到桌面是抓得準不準
    —— 兩件事的修法完全不同，混在一起會分不清是哪一個壞了。
    """
    rgb = _photo()
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    out, res = C.straighten_page(gray, rgb=rgb, dpi=150, detect_quad=True)
    assert res.quad_found, "這張合成照片本來就該抓得到紙"
    assert _ring_chroma(out) < 12.0, (
        f"最外一圈的平均色度 {_ring_chroma(out):.1f} —— 框到桌面了")


def test_a_quad_dragged_past_the_edge_fills_with_white():
    """使用者可以把角拉到圖外 —— 那時取樣到範圍外要補白，不要補黑。

    這是 `warp_quad` 那一半。**自動抓到的四邊形一定在圖內，所以只驗自動那條
    路的話，這裡補什麼顏色都測不出來**（實測：把 `borderValue` 拿掉，
    其餘四條照樣全綠）。
    """
    img = np.full((300, 400, 3), 240, np.uint8)
    # 左上角拉到圖外
    quad = np.float32([[-60, -60], [399, 0], [399, 299], [0, 299]])
    out = C.warp_quad(img, quad)
    dark = (out.astype(int).sum(axis=2) < 200).sum()
    assert dark == 0, f"拉到圖外的部分補成了黑色（{dark} 個畫素）"


def test_the_measurement_can_actually_see_a_red_frame():
    """**先證明這幾條量得到東西。**

    量法本身要能分辨「有紅框」與「沒有」，否則上面幾條可能只是永遠成立。
    """
    clean = np.full((100, 100, 3), 245, np.uint8)
    assert _reddish(clean) == 0
    painted = clean.copy()
    painted[:2] = painted[-2:] = (255, 0, 0)
    painted[:, :2] = painted[:, -2:] = (255, 0, 0)
    assert _reddish(painted) > 0
    assert _ring_chroma(painted) > 12.0 > _ring_chroma(clean)
