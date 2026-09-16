from __future__ import annotations

import base64
import io
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_FORMAT_BY_EXT = {".png":"PNG",".jpg":"JPEG",".jpeg":"JPEG",".bmp":"BMP",".gif":"GIF",".tif":"TIFF",".tiff":"TIFF",".webp":"WEBP"}
_FONT_CANDIDATES = {
    "Noto Sans CJK": ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "NotoSansCJK-Regular.ttc", "C:/Windows/Fonts/msjh.ttc"],
    "Noto Sans CJK Bold": ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "NotoSansCJK-Bold.ttc", "C:/Windows/Fonts/msjhbd.ttc"],
    "Noto Serif CJK": ["/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc", "NotoSerifCJK-Regular.ttc", "C:/Windows/Fonts/mingliu.ttc"],
    "Noto Serif CJK Bold": ["/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc", "NotoSerifCJK-Bold.ttc"],
    "DejaVu Sans": ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf"],
    "DejaVu Sans Bold": ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DejaVuSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"],
    "DejaVu Serif": ["/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", "DejaVuSerif.ttf"],
    "DejaVu Serif Bold": ["/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf", "DejaVuSerif-Bold.ttf"],
    "Noto Sans CJK TC": ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "NotoSansCJK-Regular.ttc", "C:/Windows/Fonts/msjh.ttc"],
    "Noto Serif CJK TC": ["/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc", "NotoSerifCJK-Regular.ttc", "C:/Windows/Fonts/mingliu.ttc"],
}
_BOLD_CANDIDATES = {
    "Noto Sans CJK": ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "NotoSansCJK-Bold.ttc", "C:/Windows/Fonts/msjhbd.ttc"],
    "Noto Serif CJK": ["/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc", "NotoSerifCJK-Bold.ttc"],
    "DejaVu Sans": ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DejaVuSans-Bold.ttf"],
    "DejaVu Serif": ["/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf", "DejaVuSerif-Bold.ttf"],
    "Noto Sans CJK TC": ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "NotoSansCJK-Bold.ttc", "C:/Windows/Fonts/msjhbd.ttc"],
    "Noto Serif CJK TC": ["/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc", "NotoSerifCJK-Bold.ttc"],
}
_LEGACY_FONT_NAMES = {"Noto Sans CJK TC", "Noto Serif CJK TC"}
_OVERLAY_PREFIX="__JT_OVERLAY__"


def available_fonts() -> list[dict[str, str]]:
    result=[]
    for name, candidates in _FONT_CANDIDATES.items():
        if name in _LEGACY_FONT_NAMES: continue
        for path in candidates:
            try: ImageFont.truetype(path,16);result.append({"name":name,"value":name});break
            except OSError: continue
    if not result:result.append({"name":"Default","value":"default"})
    return result

def to_png(image_bytes:bytes)->tuple[bytes,tuple[int,int]]:
    img=Image.open(io.BytesIO(image_bytes)).convert("RGB");out=io.BytesIO();img.save(out,format="PNG");return out.getvalue(),img.size

def image_format_for_path(media_path:str)->str:return _FORMAT_BY_EXT.get(Path(media_path).suffix.lower(),"PNG")
def _clip_box(box,size):x0,y0,x1,y1=box;w,h=size;return max(0,x0),max(0,y0),min(w,x1),min(h,y1)
def estimate_background(img,box):
    x0,y0,x1,y1=_clip_box(box,img.size);pad=max(2,round(max(1,y1-y0)*.18));samples=[]
    for region in [(x0-pad,y0-pad,x1+pad,y0),(x0-pad,y1,x1+pad,y1+pad),(x0-pad,y0,x0,y1),(x1,y0,x1+pad,y1)]:
        r=_clip_box(region,img.size)
        if r[2]<=r[0] or r[3]<=r[1]:continue
        crop=img.crop(r).convert("RGB");samples.extend(crop.resize((min(16,crop.width),min(16,crop.height))).get_flattened_data())
    if not samples:return (255,255,255)
    mid=len(samples)//2;return tuple(sorted(p[i] for p in samples)[mid] for i in range(3))
def estimate_foreground(img,box,background):
    pixels=list(img.crop(_clip_box(box,img.size)).convert("RGB").get_flattened_data())
    if not pixels:return (0,0,0)
    def dist(p):return math.sqrt(sum((p[i]-background[i])**2 for i in range(3)))
    contrasting=[p for p in pixels if dist(p)>=55]
    if not contrasting:return (0,0,0) if sum(background)>382 else (255,255,255)
    contrasting.sort(key=dist,reverse=True);top=contrasting[:max(1,len(contrasting)//5)];return tuple(int(sum(p[i] for p in top)/len(top)) for i in range(3))
def _font_paths(font_family=None,bold=False,font_path=None):
    result=[]
    if font_path:result.append(font_path)
    if font_family and font_family!="default":
        if font_family.endswith(" Bold"):result.extend(_FONT_CANDIDATES.get(font_family,[]))
        else:result.extend((_BOLD_CANDIDATES if bold else _FONT_CANDIDATES).get(font_family,[]))
    if bold:result += ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc","NotoSansCJK-Bold.ttc","C:/Windows/Fonts/msjhbd.ttc"]
    result += ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc","NotoSansCJK-Regular.ttc","C:/Windows/Fonts/msjh.ttc","DejaVuSans.ttf","Arial.ttf"]
    return result
def _load_font(size,font_family=None,bold=False,font_path=None):
    for candidate in _font_paths(font_family,bold,font_path):
        try:return ImageFont.truetype(candidate,size=size)
        except OSError:continue
    return ImageFont.load_default()
def _fit_font(draw,text,target_w,target_h,font_family=None,bold=False,font_path=None):
    lo,hi=5,max(6,int(target_h*1.45));best=_load_font(lo,font_family,bold,font_path)
    while lo<=hi:
        mid=(lo+hi)//2;font=_load_font(mid,font_family,bold,font_path);bbox=draw.textbbox((0,0),text,font=font)
        if bbox[2]-bbox[0]<=target_w and bbox[3]-bbox[1]<=target_h:best=font;lo=mid+1
        else:hi=mid-1
    return best
def _parse_color(value):
    if not value:return None
    value=str(value).strip()
    if value.startswith('#') and len(value)==7:
        try:return tuple(int(value[i:i+2],16) for i in (1,3,5))
        except ValueError:return None
    return None
def _save(img,fmt):
    out=io.BytesIO();fmt=(fmt or "PNG").upper()
    if fmt=="JPEG" and img.mode not in ("RGB","L"):img=img.convert("RGB")
    img.save(out,format=fmt,**({"quality":95} if fmt=="JPEG" else {}));return out.getvalue()

def edit_text(image_bytes:bytes,*,box:tuple[int,int,int,int],new_text:str,font_path:str|None=None,font_family:str|None=None,font_size:int|None=None,text_color:str|None=None,bold:bool=False,pad_px:int=2,output_format:str="PNG")->bytes:
    if isinstance(new_text,str) and new_text.startswith(_OVERLAY_PREFIX):
        try:obj=json.loads(new_text[len(_OVERLAY_PREFIX):]);return apply_overlays(image_bytes,[obj],output_format)
        except (json.JSONDecodeError,TypeError,ValueError):pass
    img=Image.open(io.BytesIO(image_bytes)).convert("RGB");x0,y0,x1,y1=_clip_box(box,img.size)
    if x1<=x0 or y1<=y0:raise ValueError("invalid edit box")
    bg=estimate_background(img,(x0,y0,x1,y1));fg=_parse_color(text_color) or estimate_foreground(img,(x0,y0,x1,y1),bg);draw=ImageDraw.Draw(img);erase=_clip_box((x0-pad_px,y0-pad_px,x1+pad_px,y1+pad_px),img.size);draw.rectangle(erase,fill=bg)
    if new_text:
        tw=max(1,erase[2]-erase[0]-2);th=max(1,erase[3]-erase[1]-2);font=_load_font(max(5,min(300,int(font_size))),font_family,bold,font_path) if font_size else _fit_font(draw,new_text,tw,th,font_family,bold,font_path);tb=draw.textbbox((0,0),new_text,font=font);w,h=tb[2]-tb[0],tb[3]-tb[1];tx=erase[0]+max(1,(tw-w)//2);ty=erase[1]+max(1,(th-h)//2)-tb[1];draw.text((tx,ty),new_text,font=font,fill=fg)
    return _save(img,output_format)

def apply_overlays(image_bytes:bytes,overlays:list[dict],output_format:str="PNG")->bytes:
    img=Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    for obj in sorted(overlays,key=lambda o:int(o.get("z",0))):
        kind=str(obj.get("overlay_type") or "").lower()
        try:x=max(0,int(float(obj.get("left",0))));y=max(0,int(float(obj.get("top",0))));w=max(1,int(float(obj.get("width",1))));h=max(1,int(float(obj.get("height",1))))
        except (TypeError,ValueError):continue
        x2=min(img.width,x+w);y2=min(img.height,y+h)
        if x>=img.width or y>=img.height or x2<=x or y2<=y:continue
        color=_parse_color(obj.get("color")) or (0,0,0);stroke=max(1,min(30,int(obj.get("stroke_width") or 3)));layer=Image.new("RGBA",img.size,(0,0,0,0));draw=ImageDraw.Draw(layer)
        if kind=="text":
            text=str(obj.get("text") or "")
            if text:
                size=max(5,min(300,int(obj.get("font_size") or max(12,h*.65))));font=_load_font(size,obj.get("font_family") or None,bool(obj.get("bold")));draw.multiline_text((x,y),text,font=font,fill=(*color,255),spacing=max(2,size//5))
        elif kind=="image":
            src=str(obj.get("data_url") or "")
            if src.startswith("data:image/") and "," in src:
                try:
                    raw=base64.b64decode(src.split(",",1)[1],validate=True)
                    if len(raw)<=12*1024*1024:
                        pasted=Image.open(io.BytesIO(raw)).convert("RGBA");pasted=pasted.resize((x2-x,y2-y),Image.Resampling.LANCZOS);layer.alpha_composite(pasted,(x,y))
                except Exception:pass
        elif kind=="whiteout":draw.rectangle((x,y,x2,y2),fill=(255,255,255,255))
        elif kind=="rect":draw.rectangle((x,y,x2,y2),outline=(*color,255),width=stroke)
        elif kind=="ellipse":draw.ellipse((x,y,x2,y2),outline=(*color,255),width=stroke)
        elif kind in {"line","arrow"}:
            draw.line((x,y,x2,y2),fill=(*color,255),width=stroke)
            if kind=="arrow":
                ang=math.atan2(y2-y,x2-x);head=max(8,stroke*4);pts=[(x2,y2),(x2-head*math.cos(ang-.55),y2-head*math.sin(ang-.55)),(x2-head*math.cos(ang+.55),y2-head*math.sin(ang+.55))];draw.polygon(pts,fill=(*color,255))
        img=Image.alpha_composite(img,layer)
    return _save(img,output_format)
