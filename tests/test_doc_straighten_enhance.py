"""文件擺正的「清晰化」—— 判準是**文字辨識率**與**內容有沒有被毀掉**。

使用者 2026-09-14：「現在有拉正 但是文件不會清晰化」。

這支工具的清晰化很容易做成災難，所以每一條參數都是量出來的：

* **二值化不是清晰化**：同一組素材上局部二值化把辨識率從 0.775 打到
  **0.108**（中文細筆畫被吃掉），而且**看起來最乾淨的那張正是最糟的**。
  它維持獨立選項、預設關閉，用途是縮檔案。
* **`divide(圖, 局部最大值)` 會把整片深色內容洗成純白**：一塊深灰照片區
  平均亮度 **66.3 → 254.9**，整塊不見了。改用有上下限的增益場。
* **白點只能提亮不能壓暗**：不夾 `>= 1.0` 的話，純白的掃描件會被壓成 245
  —— 97% 的像素被改動，而使用者根本沒有要求任何處理。

這些都是「看起來還行、其實把檔案弄壞了」的形狀，只有量出來才看得到。
"""
from __future__ import annotations

import difflib
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")
fitz = pytest.importorskip("fitz")

from app.tools.doc_straighten import straighten_core as SC  # noqa: E402

#: **行要夠長**：陰影從版面的 55% 開始，短行整行都在亮的那一側 ——
#: 第一版的行只到 40% 左右，於是「不處理」也有 0.995，這條測試測不到東西。
_LINES = [
    "Purchase Agreement between the parties named below and herein",
    "This agreement is made on 5 January 2026 between the parties",
    "named above, and shall remain in force for twenty-four months.",
    "Payment terms: wire transfer within thirty days of acceptance.",
    "Delivery shall be completed before the end of the second quarter.",
]


def _clean_page() -> "np.ndarray":
    doc = fitz.open()
    pg = doc.new_page(width=595, height=842)
    y = 120
    for line in _LINES:
        pg.insert_text((60, y), line, fontsize=13, fontname="helv")
        y += 34
    pix = pg.get_pixmap(dpi=200)
    doc.close()
    a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
    return cv2.cvtColor(a, cv2.COLOR_RGB2GRAY) if pix.n >= 3 else a[:, :, 0].copy()


def _dark_block_page() -> "np.ndarray":
    """黑底反白標題列 ＋ 一塊深灰照片區 —— 最容易被「清晰化」洗掉的東西。"""
    doc = fitz.open()
    pg = doc.new_page(width=595, height=842)
    pg.draw_rect(fitz.Rect(50, 60, 545, 110), color=None, fill=(0.1, 0.1, 0.1))
    pg.insert_text((70, 95), "MONTHLY REPORT", fontsize=20, fontname="hebo",
                   color=(1, 1, 1))
    pg.draw_rect(fitz.Rect(50, 140, 270, 340), color=None, fill=(0.25, 0.25, 0.25))
    pg.insert_text((60, 400), "Body text that must stay readable.",
                   fontsize=13, fontname="helv")
    pix = pg.get_pixmap(dpi=200)
    doc.close()
    a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
    return cv2.cvtColor(a, cv2.COLOR_RGB2GRAY) if pix.n >= 3 else a[:, :, 0].copy()


def _hard_shadow(g: "np.ndarray") -> "np.ndarray":
    """右半邊被硬生生擋掉六成五的光（書緣 / 手機自己的影子）。"""
    h, w = g.shape
    xs = np.linspace(0, 1, w)[None, :]
    return np.clip(g * np.where(xs > 0.55, 0.35, 1.0), 0, 255).astype(np.uint8)


def _ocr(img) -> float:
    d = Path(tempfile.mkdtemp(prefix="dsenh-"))
    try:
        p = d / "x.png"
        cv2.imwrite(str(p), img)
        out = subprocess.run(["tesseract", str(p), "stdout", "-l", "eng"],
                             capture_output=True, text=True, timeout=180).stdout
    finally:
        shutil.rmtree(d, ignore_errors=True)
    want = " ".join(" ".join(_LINES).split())
    return difflib.SequenceMatcher(None, want, " ".join(out.split())).ratio()


def test_a_clean_scan_is_left_completely_alone():
    """已經很平的掃描件：**一個像素都不可以動**。

    這條是「預設開著」的前提。白點沒有夾 `>= 1.0` 的話，純白會被壓成 245
    ——97% 的像素被改、墨點多 1.19%，而使用者根本沒要求任何處理。
    """
    g = _clean_page()
    out = SC.flatten_shading(g, dpi=200)
    diff = np.abs(out.astype(int) - g.astype(int))
    assert diff.max() == 0, f"乾淨的掃描件被動到了（最大變動 {diff.max()}）"


def test_large_dark_areas_are_not_washed_out():
    """**毀掉內容比留著陰影嚴重得多。**

    `divide` 版本實測把深灰區從 66.3 變成 254.9（整塊不見）。
    """
    g = _dark_block_page()
    out = SC.flatten_shading(g, dpi=200)
    photo = (slice(380, 900), slice(150, 700))
    header = (slice(150, 250), slice(150, 1200))
    before_p, after_p = g[photo].mean(), out[photo].mean()
    before_h, after_h = g[header].mean(), out[header].mean()
    assert after_p < before_p + 25, (
        f"深灰區被洗白了：{before_p:.1f} → {after_p:.1f}")
    assert after_h < before_h + 25, (
        f"黑底標題列被洗淡了：{before_h:.1f} → {after_h:.1f}（反白字會糊掉）")


def test_a_dark_page_under_a_hard_shadow_still_gets_its_paper_back():
    """深色內容要保住，**同時**陰影那一側的紙面要被提亮。

    兩個要求是互相拉扯的 —— 只驗其中一個的話，另一個可以壞得很徹底。
    """
    g = _hard_shadow(_dark_block_page())
    out = SC.flatten_shading(g, dpi=200)
    paper_right = (slice(300, 1400), slice(1000, 1150))
    photo = (slice(380, 900), slice(150, 700))
    assert out[paper_right].mean() > 230, (
        f"陰影那一側的紙面沒被救回來：{out[paper_right].mean():.1f}")
    assert out[photo].mean() < _dark_block_page()[photo].mean() + 25, (
        "救陰影的同時把深色內容洗掉了")


@pytest.mark.skipif(shutil.which("tesseract") is None,
                    reason="沒有 tesseract —— 辨識率這條要真的跑一次 OCR")
def test_a_hard_shadow_roughly_doubles_the_recognition_rate():
    """**這條是這個功能存在的理由**：0.472 → 0.982（實測）。"""
    g = _hard_shadow(_clean_page())
    before, after = _ocr(g), _ocr(SC.flatten_shading(g, dpi=200))
    assert before < 0.75, f"素材不夠壞，這條測不到東西（不處理就有 {before:.3f}）"
    assert after > 0.95, f"清晰化之後辨識率只有 {after:.3f}（修正前 {before:.3f}）"


@pytest.mark.skipif(shutil.which("tesseract") is None,
                    reason="沒有 tesseract")
def test_it_never_makes_recognition_worse():
    """乾淨的頁面不可以因為開了這個選項而變差。"""
    g = _clean_page()
    assert _ocr(SC.flatten_shading(g, dpi=200)) >= _ocr(g) - 0.005


def test_turning_it_off_really_turns_it_off():
    """`enhance=False` 要是真的什麼都不做 —— 而且預設是開著的。"""
    g = _hard_shadow(_clean_page())
    off, _ = SC.straighten_page(g.copy(), dpi=200, enhance=False)
    on, _ = SC.straighten_page(g.copy(), dpi=200, enhance=True)
    default, _ = SC.straighten_page(g.copy(), dpi=200)
    assert not np.array_equal(off, on), "開跟關的結果一樣 —— 這個選項沒接上"
    assert np.array_equal(default, on), "預設不是開著的"
