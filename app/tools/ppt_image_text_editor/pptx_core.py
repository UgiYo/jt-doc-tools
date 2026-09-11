from __future__ import annotations

import posixpath
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
import xml.etree.ElementTree as ET

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


@dataclass(frozen=True)
class PptImageRef:
    slide: int
    rel_id: str
    media_path: str


def _slide_no(path: str) -> int:
    stem = PurePosixPath(path).stem
    try:
        return int(stem.replace("slide", ""))
    except ValueError:
        return 0


def list_slide_images(pptx_bytes: bytes) -> list[PptImageRef]:
    """Return every image relationship used by slides."""
    refs: list[PptImageRef] = []
    with zipfile.ZipFile(BytesIO(pptx_bytes), "r") as zf:
        names = set(zf.namelist())
        slides = sorted(
            (n for n in names if n.startswith("ppt/slides/slide") and n.endswith(".xml")),
            key=_slide_no,
        )
        for slide_path in slides:
            rels_path = posixpath.join(
                posixpath.dirname(slide_path), "_rels", PurePosixPath(slide_path).name + ".rels"
            )
            if rels_path not in names:
                continue
            rel_root = ET.fromstring(zf.read(rels_path))
            image_targets: dict[str, str] = {}
            for rel in rel_root.findall(f"{{{_REL_NS}}}Relationship"):
                typ = rel.attrib.get("Type", "")
                if not typ.endswith("/image"):
                    continue
                rid = rel.attrib.get("Id", "")
                target = rel.attrib.get("Target", "")
                media = posixpath.normpath(posixpath.join(posixpath.dirname(slide_path), target))
                if PurePosixPath(media).suffix.lower() in _IMAGE_EXTS and media in names:
                    image_targets[rid] = media
            if not image_targets:
                continue

            slide_root = ET.fromstring(zf.read(slide_path))
            seen: set[tuple[str, str]] = set()
            for blip in slide_root.iter(f"{{{_A_NS}}}blip"):
                rid = blip.attrib.get(f"{{{_R_NS}}}embed", "")
                media = image_targets.get(rid)
                if not media or (rid, media) in seen:
                    continue
                seen.add((rid, media))
                refs.append(PptImageRef(_slide_no(slide_path), rid, media))
    return refs


def read_media(pptx_bytes: bytes, media_path: str) -> bytes:
    with zipfile.ZipFile(BytesIO(pptx_bytes), "r") as zf:
        return zf.read(media_path)


def replace_media(pptx_bytes: bytes, replacements: dict[str, bytes]) -> bytes:
    """Replace selected ppt/media files without touching slide XML/relationships."""
    src = BytesIO(pptx_bytes)
    out = BytesIO()
    with zipfile.ZipFile(src, "r") as zin, zipfile.ZipFile(out, "w") as zout:
        for info in zin.infolist():
            data = replacements.get(info.filename)
            if data is None:
                data = zin.read(info.filename)
            zout.writestr(info, data)
    return out.getvalue()
