from pathlib import Path

from app.tools.base import ToolMetadata, ToolModule
from .router import router

tool = ToolModule(
    metadata=ToolMetadata(
        id="ppt-image-text-editor",
        name="PPT 圖片轉可編輯簡報",
        description="OCR 辨識圖片式 PowerPoint，可修正文字並下載文字可編輯的 PPTX",
        icon="🖼️",
        category="內容處理",
        version="0.2.0",
    ),
    router=router,
    templates_dir=Path(__file__).parent / "templates",
)
