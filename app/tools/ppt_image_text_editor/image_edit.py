from __future__ import annotations

import io
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_FORMAT_BY_EXT = {".png":"PNG",".jpg":"JPEG",".jpeg":"JPEG",".bmp":"BMP",".gif":"GIF",".tif":"TIFF",".tiff":"TIFF",".webp":"WEBP"}
_FONT_CANDIDATES = {
    "Noto Sans CJK TC": ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "NotoSansCJK-Regular.ttc", "C:/Windows/Fonts/msjh.ttc"],
    "Noto Serif CJK TC": ["/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc", "NotoSerifCJK-Regular.ttc", "C:/Windows/Fonts/mingliu.ttc"],
}
_BOLD_CANDIDATES = {
    "Noto Sans CJK TC": ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "NotoSansCJK-Bold.ttc", "C:/Windows/Fonts/msjhbd.ttc"],
    "Noto Serif CJK TC": ["/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc", "NotoSerifCJK-Bold.ttc"],
}


def available_fonts() -> list[dict[str, str]]:
    result=[]
    for name, candidates in _FONT_CANDIDATES.items():
        for path in candidates:
            try:
                ImageFont.truetype(path, 16)
                result.append({"name": name, "value": name}); break
            except OSError: continue
    if not result: result.append({"name":"Default", "value":"default"})
    return result


def to_png(image_bytes: bytes) -> tuple[bytes, tuple[int,int]]:
    img=Image.open(io.BytesIO(image_bytes)).convert("RGB"); out=io.BytesIO(); img.save(out,format="PNG"); return out.getvalue(),img.size


def image_format_for_path(media_path: str) -> str: return _FORMAT_BY_EXT.get(Path(media_path).suffix.lower(),"PNG")

def _clip_box(box,size):
    x0,y0,x1,y1=box; w,h=size; return max(0,x0),max(0,y0),min(w,x1),min(h,y1)

def estimate_background(img,box):
    x0,y0,x1,y1=_clip_box(box,img.size); pad=max(2,round(max(1,y1-y0)*.18)); samples=[]
    for region in [(x0-pad,y0-pad,x1+pad,y0),(x0-pad,y1,x1+pad,y1+pad),(x0-pad,y0,x0,y1),(x1,y0,x1+pad,y1)]:
        r=_clip_box(region,img.size)
        if r[2]<=r[0] or r[3]<=r[1]: continue
        crop=img.crop(r).convert("RGB"); samples.extend(crop.resize((min(16,crop.width),min(16,crop.height))).get_flattened_data())
    if not samples:return (255,255,255)
    mid=len(samples)//2; return tuple(sorted(p[i] for p in samples)[mid] for i in range(3))

def estimate_foreground(img,box,background):
    pixels=list(img.crop(_clip_box(box,img.size)).convert("RGB").get_flattened_data())
    if not pixels:return (0,0,0)
    def dist(p):return math.sqrt(sum((p[i]-background[i])**2 for i in range(3)))
    contrasting=[p for p in pixels if dist(p)>=55]
    if not contrasting:return (0,0,0) if sum(background)>382 else (255,255,255)
    contrasting.sort(key=dist,reverse=True); top=contrasting[:max(1,len(contrasting)//5)]; return tuple(int(sum(p[i] for p in top)/len(top)) for i in range(3))

def _font_paths(font_family=None,bold=False,font_path=None):
    result=[]
    if font_path: result.append(font_path)
    if font_family and font_family!="default": result.extend((_BOLD_CANDIDATES if bold else _FONT_CANDIDATES).get(font_family,[]))
    if bold:
        result += ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc","NotoSansCJK-Bold.ttc","C:/Windows/Fonts/msjhbd.ttc"]
    result += ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc","NotoSansCJK-Regular.ttc","C:/Windows/Fonts/msjh.ttc","DejaVuSans.ttf","Arial.ttf"]
    return result

def _load_font(size,font_family=None,bold=False,font_path=None):
    for candidate in _font_paths(font_family,bold,font_path):
        try:return ImageFont.truetype(candidate,size=size)
        except OSError:continue
    return ImageFont.load_default()

def _fit_font(draw,text,target_w,target_h,font_family=None,bold=False,font_path=None):
    lo,hi=5,max(6,int(target_h*1.45)); best=_load_font(lo,font_family,bold,font_path)
    while lo<=hi:
        mid=(lo+hi)//2; font=_load_font(mid,font_family,bold,font_path); bbox=draw.textbbox((0,0),text,font=font)
        if bbox[2]-bbox[0]<=target_w and bbox[3]-bbox[1]<=target_h: best=font; lo=mid+1
        else:hi=mid-1
    return best

def _parse_color(value):
    if not value:return None
    value=str(value).strip()
    if value.startswith('#') and len(value)==7:
        try:return tuple(int(value[i:i+2],16) for i in (1,3,5))
        except ValueError:return None
    return None

def edit_text(image_bytes: bytes, *, box: tuple[int,int,int,int], new_text: str, font_path: str|None=None,
              font_family: str|None=None, font_size: int|None=None, text_color: str|None=None, bold: bool=False,
              pad_px: int=2, output_format: str="PNG") -> bytes:
    img=Image.open(io.BytesIO(image_bytes)).convert("RGB"); x0,y0,x1,y1=_clip_box(box,img.size)
    if x1<=x0 or y1<=y0:raise ValueError("invalid edit box")
    bg=estimate_background(img,(x0,y0,x1,y1)); fg=_parse_color(text_color) or estimate_foreground(img,(x0,y0,x1,y1),bg)
    draw=ImageDraw.Draw(img); erase=_clip_box((x0-pad_px,y0-pad_px,x1+pad_px,y1+pad_px),img.size); draw.rectangle(erase,fill=bg)
    if new_text:
        tw=max(1,erase[2]-erase[0]-2); th=max(1,erase[3]-erase[1]-2)
        font=_load_font(max(5,min(300,int(font_size))),font_family,bold,font_path) if font_size else _fit_font(draw,new_text,tw,th,font_family,bold,font_path)
        tb=draw.textbbox((0,0),new_text,font=font); w,h=tb[2]-tb[0],tb[3]-tb[1]; tx=erase[0]+max(1,(tw-w)//2); ty=erase[1]+max(1,(th-h)//2)-tb[1]
        draw.text((tx,ty),new_text,font=font,fill=fg)
    out=io.BytesIO(); fmt=(output_format or "PNG").upper(); img.save(out,format=fmt,**({"quality":95} if fmt=="JPEG" else {})); return out.getvalue()
