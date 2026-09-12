from pathlib import Path

from app.tools.base import ToolMetadata, ToolModule
from .router import router

tool = ToolModule(
    metadata=ToolMetadata(
        id="image-text-editor",
        name="圖片文字編輯",
        description="OCR 辨識圖片中的文字，直接修改、即時預覽並匯出圖片",
        icon="image",
        category="內容處理",
        version="0.1.0",
    ),
    router=router,
    templates_dir=Path(__file__).parent / "templates",
)
