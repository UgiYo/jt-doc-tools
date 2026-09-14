from pathlib import Path

from app.tools.base import ToolMetadata, ToolModule
from .router import router

tool = ToolModule(
    metadata=ToolMetadata(
        id="editable-slides",
        name="可編輯簡報工作室",
        description="匯入或建立結構化投影片，瀏覽器編輯後匯出原生可編輯 PPTX",
        icon="presentation",
        category="內容處理",
        version="0.1.0",
    ),
    router=router,
    templates_dir=Path(__file__).parent / "templates",
)
