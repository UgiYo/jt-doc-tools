from pathlib import Path

from app.tools.base import ToolMetadata, ToolModule
from .router import router

tool = ToolModule(
    metadata=ToolMetadata(
        id="ppt-image-text-editor",
        name="PPT 圖片文字編輯",
        description="逐頁辨識圖片式 PowerPoint，在預覽中修改文字並輸出保留原版面的 PPTX",
        icon="🖼️",
        category="內容處理",
        version="0.3.0",
    ),
    router=router,
    templates_dir=Path(__file__).parent / "templates",
)
