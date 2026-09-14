"""文件拉正的核心：裁邊、拉正、去除不勻底色（選用：透視校正、二值化）。

**完全不用 AI、不用 GPU** —— 傳統影像處理，單執行緒 CPU 實測
200 dpi 0.83 秒/頁、300 dpi 1.4 秒/頁。

管線順序**不可以改**（規劃階段實測踩過）：

    去不勻底色 → 裁出紙張 → 估歪斜角 → 旋轉 →（選用）二值化

* **先估角再裁邊 → 角度會估成 0.00°**：四周的黑邊主導 `minAreaRect`，
  回傳的是整張圖的軸對齊矩形。
* **角度對了還可能轉錯方向**（負號加兩次），所以 `straighten_page()` 一定會
  「修正後再估一次」當自我檢查，把殘留角一起回報。

### ⚠ 「清晰化」做過頭會把文件弄壞

同一份 200 dpi 合成掃描件（歪 2.3°、黑邊、雜訊、漸層陰影），用
tesseract `chi_tra+eng` 量 OCR 相似度：

| 做法 | OCR 相似度 |
|---|---:|
| 沒修 | 0.767 |
| **只裁邊＋拉正（保持灰階）** | **0.775**（＝乾淨原稿） |
| ＋去底色 | 0.775 |
| ＋Otsu 全域二值 | 0.775 |
| ＋局部二值 blk41 | 0.600 |
| ＋局部二值 blk61 | **0.108** |

幾何修正是穩賺的；**二值化是負的**（中文細筆畫會被吃掉），而且
**看起來最乾淨的那張正是最爛的那張**。所以二值化是選項、**預設關閉**，
介面要寫明它的用途是縮檔案大小、不是提高辨識率。
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


def normalize_illum(g: np.ndarray) -> np.ndarray:
    """背景估計相除 —— 壓掉壓書造成的漸層陰影。後面每一步都依賴這個。"""
    bg = cv2.morphologyEx(g, cv2.MORPH_CLOSE,
                          cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (41, 41)))
    return cv2.divide(g, bg, scale=255)


def crop_page(g: np.ndarray, img: "np.ndarray | None" = None) -> np.ndarray:
    """裁掉掃描機蓋板的暗邊。找不到（或找到的東西太小）就整張退回，不敢裁。

    **量在 `g`（灰階）上，裁的是 `img`** —— 彩色的那一張要跟著一起裁，
    不然輸出就只剩灰階（2026-09-14 使用者回報「沒有勾轉成黑白，修正後卻
    像黑白」）。`img` 沒給就裁 `g` 自己（舊的呼叫方式照樣能用）。
    """
    src = g if img is None else img
    bw = cv2.threshold(normalize_illum(g), 200, 255, cv2.THRESH_BINARY)[1]
    bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones((15, 15), np.uint8))
    cnts, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return src
    x, y, w, h = cv2.boundingRect(max(cnts, key=cv2.contourArea))
    return src if w * h < g.size * 0.2 else src[y:y + h, x:x + w]


def deskew_angle(g: np.ndarray, limit: float = 6.0, step: float = 0.1) -> float:
    """投影剖面法：回傳「要轉多少度才會正」。

    轉到正確角度時每一列的黑點數變化最劇烈 → 相鄰列差平方和最大。
    比 minAreaRect 穩（不受黑邊與雜點影響）。
    """
    bw = cv2.threshold(normalize_illum(g), 0, 255,
                       cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    s = cv2.resize(bw, None, fx=0.35, fy=0.35, interpolation=cv2.INTER_AREA)
    h, w = s.shape
    best, best_a = -1.0, 0.0
    for a in np.arange(-limit, limit + 1e-9, step):
        M = cv2.getRotationMatrix2D((w / 2, h / 2), float(a), 1.0)
        prof = cv2.warpAffine(s, M, (w, h), flags=cv2.INTER_NEAREST,
                              borderValue=0).sum(1, dtype=np.float64)
        v = float(((prof[1:] - prof[:-1]) ** 2).sum())
        if v > best:
            best, best_a = v, float(a)
    return best_a


def rotate(img: np.ndarray, a: float) -> np.ndarray:
    h, w = img.shape[:2]
    return cv2.warpAffine(img, cv2.getRotationMatrix2D((w / 2, h / 2), a, 1.0),
                          (w, h), flags=cv2.INTER_CUBIC, borderValue=255)


def _paper_mask(g: np.ndarray, rgb=None):
    """紙張的遮罩（四分之一尺寸）。回 `(縮圖, 遮罩)`。

    **只用亮度分割會在陰影處把紙切掉一半。** 實測使用者的手機照片
    `IMG_2905`：紙有一角落在陰影裡，Otsu 把那一塊判成桌面 —— 遮罩只蓋到
    32% 的畫面，而紙實際佔 40%，**那一角上面有字**。

    所以再加一層**色度**：紙是中性色（Lab 的 a/b 接近 128），木頭桌面 /
    橘色桌墊 / 綠色滑鼠墊偏離很多，**而且影子不改變色相**（只改亮度）。
    兩張遮罩各自做完形態學再取聯集：Otsu 負責一般情況，色度負責陰影。

    實測（IMG_2905）：32% → **40%**，紙上的墨水從 0.747 變成 **1.000**。
    """
    s = cv2.resize(g, None, fx=0.25, fy=0.25)
    b = cv2.GaussianBlur(s, (9, 9), 0)
    _t, m = cv2.threshold(b, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    if rgb is not None and getattr(rgb, "ndim", 2) == 3:
        c = cv2.resize(rgb, (s.shape[1], s.shape[0]), interpolation=cv2.INTER_AREA)
        lab = cv2.cvtColor(cv2.GaussianBlur(c, (9, 9), 0), cv2.COLOR_RGB2LAB)
        L, A, B = cv2.split(lab)
        chroma = np.hypot(A.astype(np.float32) - 128.0, B.astype(np.float32) - 128.0)
        # 中性色 ＋ 夠亮。**亮度門檻要相對於「確定是紙」那一塊**
        # （Otsu 選出來的亮區），不可以用整張圖的百分位 ——
        # 陰影面積一大，百分位自己就被拉上去，陰影裡的紙反而被排除
        # （實測：陰影裡的紙 L=118，而第 25 百分位是 122，整條判準失效）。
        # 係數掃過 0.30 / 0.40 / 0.45 / 0.55 / 0.65：**0.45 以下三個樣本
        # 全部滿分，0.55 起崩**（純度掉到 0.74 / 0.88）。取 0.45 留安全邊界，
        # 對「深色但中性」的桌面仍然擋得住（它會暗於紙的 45%）。
        ref = float(np.median(L[m > 0])) if (m > 0).any() else 255.0
        mc = ((chroma < 12) & (L > 0.45 * ref)).astype(np.uint8) * 255
        mc = cv2.morphologyEx(mc, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
        mc = cv2.morphologyEx(mc, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
        m = cv2.bitwise_or(m, mc)
    return s, m


def _quad_candidates(c: np.ndarray):
    """幾個候選四邊形（四分之一尺寸的座標）。

    **不要只產生一種。** 教科書的 `approxPolyDP` 在真實照片上常常回 5、6 個
    點（角落有陰影與圓角），而最小外接矩形永遠回得出四個點卻會多框一條桌面。
    OSS 的文件掃描 app 也是這個路數：**多產幾個候選，再用一個判準挑**。
    """
    hull = cv2.convexHull(c)
    out = []
    peri = cv2.arcLength(hull, True)
    for pct in (x / 1000.0 for x in range(5, 121)):
        ap = cv2.approxPolyDP(hull, pct * peri, True)
        if len(ap) == 4:
            out.append(ap.reshape(4, 2).astype(np.float32))
            break
    out.append(cv2.boxPoints(cv2.minAreaRect(hull)).astype(np.float32))
    return out


def _quad_score(s: np.ndarray, mask: np.ndarray, quad: np.ndarray):
    """回 `(墨水涵蓋率, 純度)` —— 兩個都是 0~1，都算在四分之一尺寸上。

    * **墨水涵蓋率**：紙上的字有多少被框進去。**切到字是不可原諒的失敗**，
      所以這個是硬條件。量的時候紙要先**內縮**幾個像素 —— 不然紙緣的陰影會
      被當成字，讓「剛好切在紙邊」的候選看起來像切到內容（實測 IMG_2904
      因此被低估 7%）。
    * **純度**：框裡面有多少真的是紙。低就是框到桌面 —— 那就是使用者看到的
      黑邊（實測現行做法在 IMG_2905 只有 0.925）。
    """
    inner = cv2.erode(mask, np.ones((7, 7), np.uint8))
    paper = inner > 0
    if not paper.any():
        return 0.0, 0.0
    thr = np.percentile(s[paper], 12)      # 紙上最暗的一成二 ≈ 筆跡
    ink = paper & (s <= thr)
    poly = np.zeros(mask.shape, np.uint8)
    cv2.fillPoly(poly, [quad.astype(np.int32)], 255)
    inside = poly > 0
    full = mask > 0
    return ((ink & inside).sum() / max(1, int(ink.sum())),
            (full & inside).sum() / max(1, int(inside.sum())))


def _nothing_to_correct(q: np.ndarray, shape) -> bool:
    """這個四邊形**做透視只會裁掉東西**嗎？

    掃描件與正面拍的照片沒有透視可以校正 —— 這時候挑出來的候選就是那個
    「完美矩形」（最小外接矩形），內角極差 0°、對邊等長。如果它又佔滿大半
    畫面，代表旁邊也沒有桌面可以裁，那麼**唯一會發生的事就是把邊緣切掉**。

    這不是假設，是用 82 張真實語料量出來的（2026-09-13）：

    | | 佔畫面 | 內角極差 | 對邊差 |
    |---|---|---|---|
    | 掃描件 / 正面照（16 張，**其中兩張切掉了抬頭文字**）| 0.42~1.00 | **0.0°** | **0.000** |
    | 真的有透視的翻拍（4 張）| 0.20~0.85 | 8.4~32.8° | 0.12~0.56 |

    切掉的那兩張都是遮罩漏了頁面最上面一條（那裡有抬頭），四邊形就跟著切在
    那裡。**與其再去調遮罩，不如認清楚「這種圖本來就不需要透視」** ——
    回 None 走純拉正那條路，一個畫素都不會被裁掉。

    要精準貼齊紙緣仍然有「自己拉四個角」那條路。
    """
    h, w = shape[:2]
    area = cv2.contourArea(q.astype(np.float32)) / float(w * h)
    if area < 0.70:                     # 旁邊還有很多背景 —— 裁掉是有價值的
        return False
    if quad_angle_range(q) > 1.0:       # 真的是斜的 —— 透視校正有意義
        return False
    d = lambda a, b: float(np.hypot(*(q[a] - q[b])))
    top, bot, left, right = d(0, 1), d(3, 2), d(0, 3), d(1, 2)
    skew = max(abs(top - bot) / max(top, bot, 1e-6),
               abs(left - right) / max(left, right, 1e-6))
    return skew <= 0.02                 # 對邊等長 = 沒有透視


def find_page_quad(g: np.ndarray, rgb=None):
    """手機翻拍：找紙張的四邊形。回 None 表示沒把握 → 走純拉正那條路。

    ## 做法（v1.15.39 用真實照片重寫第二次）

    1. **遮罩**：Otsu ∪ 色度（見 `_paper_mask`）。只用 Otsu 的話，陰影裡的
       半張紙會被判成桌面。
    2. **候選**：`approxPolyDP` 掃 epsilon 找四個點，加上最小外接矩形。
    3. **評分**：先要求**墨水涵蓋率不可以比最好的那個差 1% 以上**（切到字是
       不可原諒的），在這個前提下挑**純度最高**的。

    ### 為什麼不是單一演算法

    | 做法 | IMG_2904 | IMG_2905 |
    |---|---|---|
    | 舊：Otsu ＋ 最小外接矩形 | ink 0.738 / 純度 0.909 | ink 0.747 / 純度 0.925 |
    | 新：Otsu∪色度 ＋ 評分挑選 | ink 0.737 / **純度 1.000** | **ink 1.000 / 純度 1.000** |

    純度 0.925 的意思是**框進去的東西有 7.5% 是桌面** —— 使用者截圖回報的
    就是那一圈黑邊（2026-09-13）。

    ### 踩過的兩個坑（留著，不要再走一次）

    * **先去陰影再分割是錯的**：`normalize_illum()` 會把桌面也一起提亮，
      亮區從 21% 爆到 58~83%，四個角直接跑到畫面邊界。
    * **殘留角不能當判準**：把四邊形縮進紙內會切掉內容，而**殘留角仍然是
      -0.05°**，看起來完美。殘留角量的是「裁出來那塊正不正」，
      **不是「有沒有抓對紙」**。所以這裡的判準是墨水涵蓋率與純度。
    """
    s, m = _paper_mask(g, rgb)
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    frac = cv2.contourArea(c) / float(s.shape[0] * s.shape[1])
    # 太小 = 不是紙（可能是反光）；太大 = 整張都是紙（掃描件），不需要透視校正
    if frac < 0.05 or frac > 0.95:
        return None
    # 評分只看「紙那一塊」—— 畫面上別的亮物（鍵盤、白牆）不算
    only = np.zeros_like(m)
    cv2.drawContours(only, [c], -1, 255, cv2.FILLED)
    best = None
    for q in _quad_candidates(c):
        full = (q * 4).astype(np.float32)
        if not quad_is_sane(full, g.shape):
            continue
        ink, pur = _quad_score(s, only, q)
        if best is None or ink > best[0] + 1e-9:
            best = (ink, pur, full)
    if best is None:
        return None
    top_ink = best[0]
    chosen = best
    for q in _quad_candidates(c):
        full = (q * 4).astype(np.float32)
        if not quad_is_sane(full, g.shape):
            continue
        ink, pur = _quad_score(s, only, q)
        # 墨水不可以比最好的差 1% 以上；在這個前提下挑純度最高的
        if ink >= top_ink - 0.01 and pur > chosen[1]:
            chosen = (ink, pur, full)
    # **沒有透視可以校正的就不要做** —— 做了只會把邊緣切掉（見 `_nothing_to_correct`）
    if _nothing_to_correct(chosen[2], g.shape):
        return None
    return chosen[2]


def order_quad(q: np.ndarray) -> np.ndarray:
    """把四個角排成 左上→右上→右下→左下。

    **手動模式必須在伺服器端跑這一步** —— 使用者可以把左上拖到右下去，
    順序亂掉會產生鏡像或轉 180° 的結果。
    """
    su, d = q.sum(1), np.diff(q, axis=1).ravel()
    return np.float32([q[np.argmin(su)], q[np.argmin(d)],
                       q[np.argmax(su)], q[np.argmax(d)]])


#: 四個內角的極差上限（度）。紙是矩形，拍歪之後仍然接近 90°；
#: 框到桌面的那種歪四邊形極差會衝到 40° 以上。
#: 這條判準借自 `andrewdcampbell/OpenCV-Document-Scanner`（640★）的
#: `angle_range`，並用今天的真實失敗案例驗過：抓對的 9°、框到桌面的 44°、
#: 整個畫面的 44°。
_MAX_ANGLE_RANGE = 40.0


def quad_angle_range(q: np.ndarray) -> float:
    """四個內角的極差（度）。"""
    o = order_quad(q)
    ang = []
    for i in range(4):
        a, b, c = o[(i - 1) % 4], o[i], o[(i + 1) % 4]
        v1, v2 = a - b, c - b
        n = float(np.linalg.norm(v1) * np.linalg.norm(v2))
        if n < 1e-6:
            return 360.0
        cosv = float(np.dot(v1, v2) / n)
        ang.append(np.degrees(np.arccos(max(-1.0, min(1.0, cosv)))))
    return float(max(ang) - min(ang))


def quad_is_sane(q: np.ndarray, shape) -> bool:
    """擋自交（蝴蝶結）、面積過小、角點跑到圖外 —— warpPerspective 不會報錯。"""
    h, w = shape[:2]
    if (q < -2).any() or (q[:, 0] > w + 2).any() or (q[:, 1] > h + 2).any():
        return False
    o = order_quad(q)
    if cv2.contourArea(o) < w * h * 0.05:
        return False
    # 凸性：自交的四邊形不會是凸的
    if not bool(cv2.isContourConvex(o.astype(np.int32))):
        return False
    # 形狀要像一張紙：四個內角不可以差太多
    return quad_angle_range(o) <= _MAX_ANGLE_RANGE


def warp_quad(g: np.ndarray, quad: np.ndarray) -> np.ndarray:
    o = order_quad(quad)
    W = int(max(np.linalg.norm(o[2] - o[3]), np.linalg.norm(o[1] - o[0])))
    H = int(max(np.linalg.norm(o[1] - o[2]), np.linalg.norm(o[0] - o[3])))
    dst = np.float32([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]])
    return cv2.warpPerspective(g, cv2.getPerspectiveTransform(o, dst), (W, H),
                               flags=cv2.INTER_CUBIC)


def binarize(g: np.ndarray, dpi: int = 200) -> np.ndarray:
    """**預設不要用。** 只為縮檔案大小，不是為了提高辨識率（會吃掉中文細筆畫）。"""
    blk = max(15, int(dpi / 200 * 41) | 1)
    return cv2.adaptiveThreshold(normalize_illum(g), 255,
                                 cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY, blk, 12)


def straighten(g: np.ndarray, quad=None, do_binarize: bool = False, dpi: int = 200):
    """quad 給了就走透視校正（手動模式 / 自動抓到四角），否則只裁邊 + 拉正。"""
    if quad is not None and quad_is_sane(np.float32(quad), g.shape):
        base = warp_quad(g, np.float32(quad))
    else:
        base = crop_page(g)
    out = rotate(base, deskew_angle(base))
    return binarize(out, dpi) if do_binarize else out


#: 一頁的處理結果 —— 回報給使用者的數字都在這裡。
@dataclass
class PageResult:
    page: int
    angle: float            # 轉了幾度（負 = 逆時針）
    residual: float         # **修正後再估一次**的殘留角，接近 0 才算成功
    quad_found: bool        # 有沒有抓到紙張的四個角（手機翻拍才會有）
    width: int
    height: int
    ms: int
    #: 這一頁**原樣保留**（已經是正的、而且有文字層）——
    #: 處理它只會把文字變成圖片，見 `_should_skip`。
    skipped: bool = False
    #: 使用者指定的整頁轉向（0 / 90 / 180 / 270），自動流程一律 0。
    rotate_deg: int = 0
    #: 這一頁**實際用到**的四個角，正規化 0~1、**轉向後**的座標系。
    #: 前端拿它當拖曳的起點 —— 由這裡回出去，呼叫端就不必自己換算
    #: （換算一次就是一次搞錯長寬的機會，v1.15.45 就是這樣錯的）。
    quad: "list[list[float]] | None" = None



def flatten_shading(gray: "np.ndarray", *, dpi: int = 200,
                    gain_max: float = 3.0) -> "np.ndarray":
    """清晰化：把不勻的底色與陰影壓平，紙面拉回接近白。

    **跟 `normalize_illum()` 不一樣** —— 那一支是**給判斷用的**（裁邊、估歪斜
    時把照明差異抹掉），它會連桌面一起提亮，從來不會寫進產出。這一支才是
    使用者看得到的輸出處理。

    ## 判準是文字辨識率，不是「看起來乾不乾淨」

    合成四種常見的壞照明，用 tesseract 量辨識率（乾淨原稿 0.986 是上限）：

    | 情境 | 不處理 | 清晰化 |
    |---|---:|---:|
    | 單邊硬陰影（書緣擋光） | **0.472** | **0.982** |
    | 四角暗角 | 0.884 | 0.986 |
    | 斜向重陰影 | 0.967 | 0.986 |
    | 泛黃紙 | 0.986 | 0.987 |

    **二值化不是清晰化。** 同一組素材上，局部二值化把辨識率從 0.775 打到
    **0.108** —— 中文細筆畫被吃掉，而且**看起來最乾淨的那張正是最糟的那張**。
    所以二值化維持獨立選項、預設關閉，它的用途是縮檔案大小。
    CLAHE 提對比也一律更差（0.967 → 0.963），不用。

    ## 做法：平場校正，不是 divide

    直覺的做法是 `divide(圖, 局部最大值)`，辨識率確實一樣好 ——
    但它會把**整片深色內容洗成純白**：實測一塊深灰照片區
    **平均亮度 66.3 → 254.9**，等於整塊不見了。黑底反白標題列也從 77.9
    變成 166.1（字會糊掉）。**毀掉內容比留著陰影嚴重得多**，
    跟這支工具「切到內容不可原諒、多框一條桌面只是難看」是同一條原則。

    所以改成：估一個**緩慢變化、有上下限的增益場**再相乘。

    1. 局部最大值（close）當紙面亮度 —— 硬陰影的階梯跟得上。
    2. **大片深色區域的估計值不可信**（那是內容不是陰影）→ 標成遮罩，用
       `inpaint` 從**邊界**補。用大範圍模糊補會把陰影的階梯一起抹掉
       （實測辨識率從 0.982 掉回 0.472）。
    3. 增益 = 最亮紙面 / 背景，夾在 `[1.0, gain_max]` —— **只提亮不壓暗**。

    遮罩的參考核實測過 31 / 61 / 91 / 121：**91（縮圖後）＝ 原圖約 3 吋**
    才蓋得住一塊 220pt 寬的深色區（深灰塊 66.3 → 67.2，幾乎不動），
    而硬陰影的辨識率仍是 0.982。比它更大沒有再變好，只是更慢。

    ## 對已經很平的掃描件是 **0 變動**

    白點那一步一定要夾 `>= 1.0`：不夾的話純白的掃描件會被壓成 245
    （實測 97% 的像素被改、墨點多 1.19%）。夾住之後**最大變動 0**，
    所以這個選項可以預設開著。
    """
    import cv2

    # **彩色要保住彩色。** 增益場從亮度算，再原封不動套到每一個通道 ——
    # 三個通道各自算一次會改到色相，看起來就褪色了。
    colour = gray.ndim == 3
    g = cv2.cvtColor(gray, cv2.COLOR_RGB2GRAY) if colour else gray
    k = int(max(15, round(dpi * 0.20))) | 1
    bg = cv2.morphologyEx(g, cv2.MORPH_CLOSE,
                          cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    small = cv2.resize(bg, (0, 0), fx=0.15, fy=0.15, interpolation=cv2.INTER_AREA)
    ref = cv2.morphologyEx(small, cv2.MORPH_CLOSE,
                           cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (91, 91)))
    bad = (small.astype(np.float32) < ref.astype(np.float32) * 0.72).astype(np.uint8)
    if bad.any():
        small = cv2.inpaint(small, bad, 5, cv2.INPAINT_TELEA)
    field = cv2.resize(small, (g.shape[1], g.shape[0]), interpolation=cv2.INTER_LINEAR)
    field = cv2.GaussianBlur(field.astype(np.float32), (0, 0), max(3.0, dpi * 0.02))
    target = float(np.percentile(field, 90))
    if target < 1:
        return gray
    field = np.maximum(field, target / gain_max)
    gain = np.clip(target / field, 1.0, gain_max)
    if colour:
        out = np.clip(gray.astype(np.float32) * gain[:, :, None],
                      0, 255).astype(np.uint8)
    else:
        out = np.clip(g.astype(np.float32) * gain, 0, 255).astype(np.uint8)
    return _white_point(out)


def _white_point(g: "np.ndarray", *, pct: int = 88, target: int = 245,
                 gain_max: float = 2.2) -> "np.ndarray":
    """把紙面拉到接近白。**只提亮不壓暗** —— 見 `flatten_shading` 的說明。

    彩色時**三個通道乘同一個數**（色相不變），而且百分位是從亮度取的 ——
    直接對 BGR 取百分位會被最亮的那個通道帶著跑。
    """
    lum = cv2.cvtColor(g, cv2.COLOR_RGB2GRAY) if g.ndim == 3 else g
    hi = float(np.percentile(lum, pct))
    if hi < 1:
        return g
    gain = float(np.clip(target / hi, 1.0, gain_max))
    if gain <= 1.0:
        return g
    return np.clip(g.astype(np.float32) * gain, 0, 255).astype(np.uint8)


#: 常用的紙張尺寸（mm）。`A4` 直的；橫的由呼叫端把長寬對調。
PAPER_MM: dict[str, tuple[float, float]] = {
    "a4": (210.0, 297.0),
    "a3": (297.0, 420.0),
    "b5": (176.0, 250.0),
    "letter": (215.9, 279.4),
    "legal": (215.9, 355.6),
}


def mm_to_px(mm: float, dpi: int) -> int:
    return max(1, int(round(mm / 25.4 * dpi)))


def fit_to(img: "np.ndarray", w: int, h: int) -> "np.ndarray":
    """把修正好的圖放進指定的畫布，**維持比例、留白補齊**。

    **不可以拉伸、更不可以裁切。** 這支工具從一開始就是
    「切到內容不可原諒，多留一條白邊只是難看」——
    指定的尺寸比例跟紙不一樣時，寧可上下（或左右）補白。

    留白補**白色**（紙的顏色），不是黑色：補黑的話列印會整片吃墨，
    而且看起來像掃描機蓋板沒關。
    """
    import cv2

    w = max(1, int(w))
    h = max(1, int(h))
    ih, iw = img.shape[:2]
    if (iw, ih) == (w, h):
        return img
    s = min(w / iw, h / ih)
    nw, nh = max(1, int(round(iw * s))), max(1, int(round(ih * s)))
    interp = cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC
    small = cv2.resize(img, (nw, nh), interpolation=interp)
    if img.ndim == 3:
        canvas = np.full((h, w, img.shape[2]), 255, np.uint8)
    else:
        canvas = np.full((h, w), 255, np.uint8)
    x, y = (w - nw) // 2, (h - nh) // 2
    canvas[y:y + nh, x:x + nw] = small
    return canvas


def straighten_page(gray: "np.ndarray", *, quad=None, rgb=None,
                    detect_quad: bool = False, do_binarize: bool = False,
                    dpi: int = 200, page_no: int = 1,
                    rotate_deg: int = 0,
                    enhance: bool = True) -> tuple["np.ndarray", PageResult]:
    """處理一頁。

    ## 座標系：只有一個 —— **轉向後、正規化 0~1**

    `quad` 是使用者自己拉的四個角，座標系是**他在畫面上看到的那張圖**，
    也就是**轉向之後**的。自動偵測也在轉完之後才做，所以兩者同一個框架，
    中間沒有任何換算。

    **這裡曾經有兩個疊在一起的錯**（2026-09-14 使用者回報「有拉但出來的跑掉」）：
    呼叫端用**未轉**的長寬把 0~1 換成像素，然後這支再用 `_rotate_quad`
    轉一次。轉 90° 的實測：產出 834×358（應為 471×629）、
    墨點比例 **41.2%**（框到的大半是桌面，正確值 1.9%）。
    只要座標系有兩個，遲早會有人在錯的那一邊換算 —— 所以現在只留一個。

    `rotate_deg`（0 / 90 / 180 / 270）是**使用者指定的整頁轉向**，在裁邊與
    估歪斜**之前**先轉 —— 自動估角只看 ±6°，掃反了或掃成橫的它救不了，
    那是方向問題不是歪斜問題。轉完照樣跑自動拉正，
    所以「轉 90° 再微調 1.2°」是一次做完的。

    `rgb` 是同一頁的彩色版（給 `_paper_mask` 用）—— 陰影裡的紙只有靠色度
    才救得回來。沒有就只用灰階。

    `detect_quad` **預設 False**：這支原本的語意就是「`quad=None` ＝ 不做
    透視校正」，改成預設 True 會把每一個既有呼叫的行為無聲換掉。
    要自動抓的呼叫端明確傳 `detect_quad=True`（兩支真正的呼叫端都是照使用者
    在畫面上的選擇傳進來的）。

    **一定會回報 `residual`**（修正後再估一次的殘留角）—— 轉錯方向時角度
    看起來「有動」，只有殘留角會現形。
    """
    t0 = time.time()
    rot = int(rotate_deg) % 360
    if rot:
        if rot not in (90, 180, 270):
            raise ValueError(f"rotate_deg 只接受 0 / 90 / 180 / 270（收到 {rotate_deg}）")
        code = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180,
                270: cv2.ROTATE_90_COUNTERCLOCKWISE}[rot]
        gray = cv2.rotate(gray, code)
        if rgb is not None:
            rgb = cv2.rotate(rgb, code)
    h0, w0 = gray.shape[:2]
    q = None
    if quad is not None:
        # 正規化 → 像素，用的是**轉向後**的長寬
        q = np.float32([[float(x) * w0, float(y) * h0] for x, y in quad])
    elif detect_quad:
        q = find_page_quad(gray, rgb)
    if q is not None and not quad_is_sane(q, gray.shape):
        q = None
    # **量在灰階、做在彩色。** 幾何（透視 / 裁邊 / 旋轉）一律套在彩色那一張
    # 上，灰階只拿來量角度與找紙邊 —— 以前整條管線都在 `gray` 上跑，所以
    # 「沒有勾轉成黑白」的輸出其實也是灰的（2026-09-14 使用者回報：拍的是
    # 彩色名片，修正後變黑白）。沒有彩色版時行為完全不變。
    work = rgb if rgb is not None else gray
    if q is not None:
        base = warp_quad(work, q)
        base_g = warp_quad(gray, q) if rgb is not None else base
    else:
        base = crop_page(gray, work)
        base_g = crop_page(gray) if rgb is not None else base
    ang = deskew_angle(base_g)
    out = rotate(base, ang)
    # 順序：壓平底色在二值化之前。**這一步不是為了二值化** ——
    # `binarize()` 自己就會先跑 `normalize_illum()`，對陰影本來就有抵抗力
    # （實測把兩者對調，黑像素比例不變）。壓平是為了**二值化關掉時
    # 使用者拿到的那張圖**，那才是預設的情況。
    if enhance:
        out = flatten_shading(out, dpi=dpi)
    if do_binarize:
        # 二值化本來就是「轉成黑白」—— 彩色先降成灰階再做。
        out = binarize(cv2.cvtColor(out, cv2.COLOR_RGB2GRAY)
                       if out.ndim == 3 else out, dpi)
    # 殘留角要量在灰階上
    resid = deskew_angle(cv2.cvtColor(out, cv2.COLOR_RGB2GRAY)
                         if out.ndim == 3 else out, limit=2.0, step=0.05)
    used = None
    if q is not None:
        used = [[round(float(x) / w0, 5), round(float(y) / h0, 5)] for x, y in q]
    return out, PageResult(page=page_no, angle=round(ang, 2),
                           residual=round(resid, 2), quad_found=q is not None,
                           rotate_deg=rot, quad=used,
                           width=out.shape[1], height=out.shape[0],
                           ms=int((time.time() - t0) * 1000))


#: 「已經夠正了」的門檻。
#:
#: **0.5 是量出來的，不是猜的**：完全沒歪的原生 PDF 頁面，估計器仍會回報
#: 一點角度（文字越稀疏越吵）——
#:
#:   30 行 −0.10°｜15 行 −0.10°｜5 行 −0.10°｜**只有 1 行 −0.40°**
#:
#: 門檻低於那個雜訊就會把好頁面也重新算圖（文字變圖片）。0.5° 在 A4 上
#: 是整頁約 2.5 mm 的落差，看不出來。
_SKIP_ANGLE = 0.5
#: 有多少字才算「有文字層」。掃描件的 OCR 文字層也算 —— 那種頁面**照樣要處理**
#: （歪的就是歪的），所以這個判斷要跟角度一起看，不可以只看有沒有文字。
#:
#: **30 這個數字的依據**（拿真實樣本量過）：原生 PDF 的內文頁動輒 700~3,600 字，
#: 而圖片型投影片的頁面是 0~17 字（文字本來就在圖裡）。門檻落在 30 的時候，
#: 一份 20 頁的圖片型簡報有 18 頁被處理，**總共失去 40 個字**（頁碼與短標題，
#: 平均 2.2 字/頁）—— 那些頁面本來就沒有可保的文字層。
#:
#: 那次量到「文字保住 65%」看起來很嚴重，其實是小分母造成的錯覺
#: （原檔全部只有 113 字）。**看比例之前先看絕對值。**
#:
#: 影像佔比**不能**當判準：原生簡報的滿版背景圖也是 100% 覆蓋，跟掃描件
#: 分不開（實測過）。
_TEXT_CHARS = 30


def _should_skip(page, gray) -> bool:
    """這一頁該不該原樣保留？

    **為什麼需要這個判斷**：原生 PDF（文字是向量的）丟進來，我們會把整頁
    算成圖再貼回去 —— 文字從此**選不到、搜尋不到、複製不到**，而畫面上
    看起來一模一樣。使用者不會發現，直到有人要搜尋那份文件。

    判準是**兩個條件同時成立**：
      ①這一頁有文字層（抽得到字）
      ②而且已經夠正了（歪斜 < 0.3°）

    只看①不行：掃描件被 OCR 過之後也有文字層，但它該處理（歪的就是歪的）。
    只看②不行：一份已經很正的掃描件，裁邊與去底色仍然有價值。
    """
    try:
        text = page.get_text().strip()
    except Exception:  # noqa: BLE001
        return False
    if len(text) < _TEXT_CHARS:
        return False
    # **一定要先裁邊再估角**（跟主管線同一個順序，理由見模組開頭）——
    # 我第一版直接對整張圖估，四周的黑邊主導了投影剖面，一份歪 3° 的掃描件
    # 被估成 −0.1° → 判成「已經是正的」而跳過。**這是模組說明裡就寫著的
    # 陷阱，我照樣踩了一次。**
    #
    # 另外要用完整的角度範圍（`limit` 用預設的 6°）：`limit=2.0` 看不到 3°
    # 的歪斜；`step=0.05` 在文字稀疏的頁面上比 0.1 更吵（實測 −0.45 vs −0.10）。
    return abs(deskew_angle(crop_page(gray))) < _SKIP_ANGLE


def straighten_pdf(src: Path, dst: Path, *, dpi: int = 200,
                   do_binarize: bool = False, detect_quad: bool = True,
                   enhance: bool = True,
                   out_size: "tuple[int, int] | None" = None,
                   overrides: dict | None = None,
                   progress=None, cancelled=None) -> list[PageResult]:
    """整份 PDF：一頁進、一頁出，**不把整份留在記憶體裡**。

    50 頁 300 dpi 全讀進記憶體約 2 GB —— 會撞上作業佇列的記憶體准入，
    小機器上更可能把服務吃垮。所以逐頁算、逐頁寫。
    """
    import fitz
    results: list[PageResult] = []
    src_doc = fitz.open(str(src))
    out_doc = fitz.open()
    try:
        total = src_doc.page_count
        for i in range(total):
            if cancelled is not None and cancelled():
                raise Cancelled()
            if progress is not None:
                progress(i, total)
            pix = src_doc[i].get_pixmap(dpi=dpi, alpha=False)
            arr = np.frombuffer(pix.samples, np.uint8).reshape(
                pix.height, pix.width, pix.n)
            gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY) if pix.n >= 3 \
                else arr[:, :, 0]
            # **已經是正的原生 PDF 頁面原樣保留** —— 處理它只會把向量文字
            # 變成圖片（見 `_should_skip`）。
            if _should_skip(src_doc[i], gray):
                out_doc.insert_pdf(src_doc, from_page=i, to_page=i)
                results.append(PageResult(
                    page=i + 1, angle=0.0, residual=0.0, quad_found=False,
                    width=int(rect_w := src_doc[i].rect.width),
                    height=int(src_doc[i].rect.height),
                    ms=0, skipped=True))
                del pix, arr, gray
                continue
            # 逐頁覆寫：使用者在畫面上拉過四個角、或指定過轉向的那幾頁。
            # **鍵是 1-based 頁碼**（畫面上看到的那個數字），不是索引。
            ov = (overrides or {}).get(i + 1) or {}
            rot = int(ov.get("rotate", 0) or 0)
            # 使用者拉的點是**正規化座標（0~1）、而且是轉向後的座標系** ——
            # 換算與自動偵測都交給 `straighten_page`（那裡才知道轉向後的
            # 長寬）。**彩色一起送進去**：陰影裡的紙只有靠色度才救得回來
            #（`_paper_mask`）。只給灰階時 IMG_2905 的純度只有 0.784，
            # 也就是框進去的東西有兩成是桌面。
            fixed, res = straighten_page(
                gray, quad=(ov.get("quad") or None),
                rgb=arr if pix.n >= 3 else None, detect_quad=detect_quad,
                do_binarize=do_binarize, dpi=dpi, page_no=i + 1,
                rotate_deg=rot, enhance=enhance)
            # **編碼要看內容**：灰階掃描件用 JPEG（實測 2.7 MB → 1.0 MB，
            # 50 頁差 85 MB）；二值化過的用 PNG（只有黑白，實測 42 KB，
            # 換成 JPEG 反而會多出壓縮雜點）。
            # **`imencode` 吃的是 BGR**，而 PyMuPDF 的 pixmap 給的是 RGB ——
            # 不轉的話紅藍會對調（名片的紅色標題會變成藍色）。
            # **指定輸出尺寸**（像素）：維持比例放進去、留白補齊。
            # 轉 90° / 270° 的那幾頁跟著把長寬對調 —— 不然直的頁面會被塞進
            # 橫的畫布，中間一小條、兩邊一大片白。
            if out_size:
                ow, oh = out_size
                if rot in (90, 270):
                    ow, oh = oh, ow
                fixed = fit_to(fixed, ow, oh)
            enc = cv2.cvtColor(fixed, cv2.COLOR_RGB2BGR) if fixed.ndim == 3 else fixed
            if do_binarize:
                blob = cv2.imencode(".png", enc)[1].tobytes()
            else:
                blob = cv2.imencode(".jpg", enc,
                                    [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()
            # 頁面尺寸照原頁（點數）—— 不可以用像素當點數，那會變成巨大的頁面
            rect = src_doc[i].rect
            # **轉 90° / 270° 之後長寬要對調**，否則直的內容會被塞進橫的頁面
            # 而被壓扁（畫面上看起來「有轉，但比例不對」）。
            pw, ph = rect.width, rect.height
            if rot in (90, 270):
                pw, ph = ph, pw
            if out_size:
                # 指定過尺寸就照它算頁面大小：像素 ÷ dpi × 72 = 點。
                # （使用者填 mm 時呼叫端已經換算成像素了。）
                pw = fixed.shape[1] / dpi * 72.0
                ph = fixed.shape[0] / dpi * 72.0
            page = out_doc.new_page(width=pw, height=ph)
            page.insert_image(page.rect, stream=blob)
            results.append(res)
            del pix, arr, gray, fixed, blob     # 不讓上一頁撐到下一頁
        if progress is not None:
            progress(total, total)
        out_doc.save(str(dst), garbage=3, deflate=True)
    finally:
        out_doc.close()
        src_doc.close()
    return results


class Cancelled(Exception):
    """使用者按了停止 —— 呼叫端要把產出丟掉。"""


def report(path: str, do_binarize: bool = False) -> None:
    g = cv2.imread(path, 0)
    if g is None:
        raise SystemExit(f"讀不到影像：{path}")
    t0 = time.time()
    q = find_page_quad(g)
    out = straighten(g, q, do_binarize)
    dt = time.time() - t0
    # 自我檢查：修正後再估一次，殘留要接近 0（轉反方向時這裡會現形）
    resid = deskew_angle(out, limit=2.0, step=0.05)
    print(f"{path}: {g.shape[1]}x{g.shape[0]} → {out.shape[1]}x{out.shape[0]}"
          f"｜四邊形 {'有' if q is not None else '無（走純拉正）'}"
          f"｜殘留 {resid:+.2f}°｜{dt * 1000:.0f} ms")
    cv2.imwrite(path.rsplit(".", 1)[0] + "_fixed.png", out)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit(__doc__)
    for a in args:
        report(a, "--binarize" in sys.argv)
