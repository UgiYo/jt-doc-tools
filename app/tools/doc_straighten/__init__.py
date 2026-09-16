"""掃描修正 —— 拍歪 / 掃歪的文件裁邊、拉正、去除不勻底色。

**工具 id `doc-straighten` 不動** —— 改 id 要連 `roles.py`、backfill
migration、既有安裝的權限一起搬。v1.15.55 之前叫「文件擺正」，
舊名仍留在搜尋關鍵字裡（本來會打「擺正」的人要找得到）。
"""
from pathlib import Path

from ..base import ToolMetadata, ToolModule
from .router import router

metadata = ToolMetadata(
    id="doc-straighten",
    name="掃描修正",
    description="把拍歪、掃歪的文件裁掉黑邊、拉正、去除不勻的底色，"
                "輸出端正的 PDF。收 PDF、手機拍的照片與文書檔。",
    icon="crop",
    category="檔案編輯",
)

tool = ToolModule(
    metadata=metadata,
    router=router,
    templates_dir=Path(__file__).resolve().parent / "templates",
)
