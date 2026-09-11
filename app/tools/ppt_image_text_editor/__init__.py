from pathlib import Path

from app.tools.base import ToolMetadata, ToolModule
from .router import router

TOOL = ToolModule(
    metadata=ToolMetadata(
        id="ppt-image-text-editor",
        name="PPT 圖片文字編輯",
        description="OCR 辨識 PowerPoint 圖片中的文字並直接修改後匯出 PPTX",
        icon="🖼️",
        category="Office",
        version="0.1.0",
    ),
    router=router,
    templates_dir=Path(__file__).parent / "templates",
)
