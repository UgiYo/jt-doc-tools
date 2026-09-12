import importlib.util
import io
import pathlib
import zipfile
import sys
from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parents[1]

def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

image_edit = load('pite_image_edit', 'app/tools/ppt_image_text_editor/image_edit.py')
pptx_core = load('pite_pptx_core', 'app/tools/ppt_image_text_editor/pptx_core.py')
edit_text = image_edit.edit_text
list_slide_images = pptx_core.list_slide_images
read_media = pptx_core.read_media
replace_media = pptx_core.replace_media


def _fake_pptx(img: bytes) -> bytes:
    slide = b'''<?xml version="1.0"?><p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:cSld><p:spTree><p:pic><p:blipFill><a:blip r:embed="rId2"/></p:blipFill></p:pic></p:spTree></p:cSld></p:sld>'''
    rels = b'''<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.png"/></Relationships>'''
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        z.writestr('ppt/slides/slide1.xml',slide)
        z.writestr('ppt/slides/_rels/slide1.xml.rels',rels)
        z.writestr('ppt/media/image1.png',img)
    return out.getvalue()


def test_list_and_replace_media_preserves_relationships():
    im=Image.new('RGB',(100,40),'white'); b=io.BytesIO(); im.save(b,'PNG')
    pptx=_fake_pptx(b.getvalue())
    refs=list_slide_images(pptx)
    assert len(refs)==1 and refs[0].slide==1 and refs[0].media_path=='ppt/media/image1.png'
    changed=Image.new('RGB',(100,40),'red'); c=io.BytesIO(); changed.save(c,'PNG')
    out=replace_media(pptx,{'ppt/media/image1.png':c.getvalue()})
    assert read_media(out,'ppt/media/image1.png')==c.getvalue()
    with zipfile.ZipFile(io.BytesIO(out)) as z:
        assert b'rId2' in z.read('ppt/slides/slide1.xml')


def test_edit_text_keeps_canvas_size():
    im=Image.new('RGB',(200,80),'white'); d=ImageDraw.Draw(im); d.text((20,20),'Gitlab',fill='black'); b=io.BytesIO(); im.save(b,'PNG')
    edited=edit_text(b.getvalue(),box=(18,18,95,45),new_text='GitLab')
    out=Image.open(io.BytesIO(edited))
    assert out.size==(200,80)


def test_image_editors_are_registered_for_the_ui():
    from app.tool_registry import discover_tools

    ids = {tool.metadata.id for tool in discover_tools()}
    assert {"ppt-image-text-editor", "image-text-editor"} <= ids
