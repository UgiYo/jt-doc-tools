from __future__ import annotations
import base64,io,json,math
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
_FORMAT_BY_EXT={'.png':'PNG','.jpg':'JPEG','.jpeg':'JPEG','.bmp':'BMP','.gif':'GIF','.tif':'TIFF','.tiff':'TIFF','.webp':'WEBP'}
_FONT_CANDIDATES={'Noto Sans CJK':['/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc','NotoSansCJK-Regular.ttc','C:/Windows/Fonts/msjh.ttc'],'Noto Sans CJK Bold':['/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc','NotoSansCJK-Bold.ttc','C:/Windows/Fonts/msjhbd.ttc'],'Noto Serif CJK':['/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc','NotoSerifCJK-Regular.ttc','C:/Windows/Fonts/mingliu.ttc'],'Noto Serif CJK Bold':['/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc','NotoSerifCJK-Bold.ttc'],'DejaVu Sans':['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','DejaVuSans.ttf','C:/Windows/Fonts/arial.ttf'],'DejaVu Sans Bold':['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf','DejaVuSans-Bold.ttf','C:/Windows/Fonts/arialbd.ttf'],'DejaVu Serif':['/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf','DejaVuSerif.ttf'],'DejaVu Serif Bold':['/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf','DejaVuSerif-Bold.ttf']}
_BOLD_CANDIDATES={'Noto Sans CJK':_FONT_CANDIDATES['Noto Sans CJK Bold'],'Noto Serif CJK':_FONT_CANDIDATES['Noto Serif CJK Bold'],'DejaVu Sans':_FONT_CANDIDATES['DejaVu Sans Bold'],'DejaVu Serif':_FONT_CANDIDATES['DejaVu Serif Bold']};_OVERLAY_PREFIX='__JT_OVERLAY__'
def available_fonts():
 r=[]
 for n,c in _FONT_CANDIDATES.items():
  for p in c:
   try:ImageFont.truetype(p,16);r.append({'name':n,'value':n});break
   except OSError:continue
 return r or [{'name':'Default','value':'default'}]
def to_png(b):
 im=Image.open(io.BytesIO(b)).convert('RGB');o=io.BytesIO();im.save(o,format='PNG');return o.getvalue(),im.size
def image_format_for_path(p):return _FORMAT_BY_EXT.get(Path(p).suffix.lower(),'PNG')
def _clip_box(b,s):x0,y0,x1,y1=b;w,h=s;return max(0,x0),max(0,y0),min(w,x1),min(h,y1)
def estimate_background(im,b):
 x0,y0,x1,y1=_clip_box(b,im.size);pad=max(2,round(max(1,y1-y0)*.18));samples=[]
 for reg in [(x0-pad,y0-pad,x1+pad,y0),(x0-pad,y1,x1+pad,y1+pad),(x0-pad,y0,x0,y1),(x1,y0,x1+pad,y1)]:
  r=_clip_box(reg,im.size)
  if r[2]<=r[0] or r[3]<=r[1]:continue
  c=im.crop(r).convert('RGB');samples.extend(c.resize((min(16,c.width),min(16,c.height))).get_flattened_data())
 if not samples:return(255,255,255)
 m=len(samples)//2;return tuple(sorted(p[i] for p in samples)[m] for i in range(3))
def estimate_foreground(im,b,bg):
 ps=list(im.crop(_clip_box(b,im.size)).convert('RGB').get_flattened_data())
 if not ps:return(0,0,0)
 def d(p):return math.sqrt(sum((p[i]-bg[i])**2 for i in range(3)))
 cs=[p for p in ps if d(p)>=55]
 if not cs:return(0,0,0) if sum(bg)>382 else(255,255,255)
 cs.sort(key=d,reverse=True);top=cs[:max(1,len(cs)//5)];return tuple(int(sum(p[i] for p in top)/len(top)) for i in range(3))
def _font_paths(f=None,bold=False,font_path=None):
 r=[]
 if font_path:r.append(font_path)
 if f and f!='default':r.extend((_BOLD_CANDIDATES if bold else _FONT_CANDIDATES).get(f,[]))
 if bold:r+=['/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc','NotoSansCJK-Bold.ttc','C:/Windows/Fonts/msjhbd.ttc']
 return r+['/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc','NotoSansCJK-Regular.ttc','C:/Windows/Fonts/msjh.ttc','DejaVuSans.ttf','Arial.ttf']
def _load_font(size,f=None,bold=False,font_path=None):
 for p in _font_paths(f,bold,font_path):
  try:return ImageFont.truetype(p,size=size)
  except OSError:continue
 return ImageFont.load_default()
def _fit_font(d,t,w,h,f=None,bold=False,font_path=None):
 lo,hi=5,max(6,int(h*1.45));best=_load_font(lo,f,bold,font_path)
 while lo<=hi:
  m=(lo+hi)//2;ft=_load_font(m,f,bold,font_path);bb=d.textbbox((0,0),t,font=ft)
  if bb[2]-bb[0]<=w and bb[3]-bb[1]<=h:best=ft;lo=m+1
  else:hi=m-1
 return best
def _parse_color(v):
 if not v:return None
 v=str(v).strip()
 if v.startswith('#') and len(v)==7:
  try:return tuple(int(v[i:i+2],16) for i in(1,3,5))
  except ValueError:return None
 return None
def _save(im,fmt):
 o=io.BytesIO();fmt=(fmt or 'PNG').upper()
 if fmt=='JPEG' and im.mode not in('RGB','L'):im=im.convert('RGB')
 im.save(o,format=fmt,**({'quality':95} if fmt=='JPEG' else{}));return o.getvalue()
def edit_text(image_bytes:bytes,*,box,new_text,font_path=None,font_family=None,font_size=None,text_color=None,bold=False,pad_px=2,output_format='PNG'):
 if isinstance(new_text,str) and new_text.startswith(_OVERLAY_PREFIX):
  try:return apply_overlays(image_bytes,[json.loads(new_text[len(_OVERLAY_PREFIX):])],output_format)
  except(json.JSONDecodeError,TypeError,ValueError):pass
 im=Image.open(io.BytesIO(image_bytes)).convert('RGB');x0,y0,x1,y1=_clip_box(box,im.size)
 if x1<=x0 or y1<=y0:raise ValueError('invalid edit box')
 bg=estimate_background(im,(x0,y0,x1,y1));fg=_parse_color(text_color) or estimate_foreground(im,(x0,y0,x1,y1),bg);d=ImageDraw.Draw(im);er=_clip_box((x0-pad_px,y0-pad_px,x1+pad_px,y1+pad_px),im.size);d.rectangle(er,fill=bg)
 if new_text:
  tw=max(1,er[2]-er[0]-2);th=max(1,er[3]-er[1]-2);ft=_load_font(max(5,min(300,int(font_size))),font_family,bold,font_path) if font_size else _fit_font(d,new_text,tw,th,font_family,bold,font_path);bb=d.textbbox((0,0),new_text,font=ft);w,h=bb[2]-bb[0],bb[3]-bb[1];d.text((er[0]+max(1,(tw-w)//2),er[1]+max(1,(th-h)//2)-bb[1]),new_text,font=ft,fill=fg)
 return _save(im,output_format)
def apply_overlays(image_bytes:bytes,overlays:list[dict],output_format='PNG'):
 im=Image.open(io.BytesIO(image_bytes)).convert('RGBA')
 for obj in sorted(overlays,key=lambda o:int(o.get('z',0))):
  kind=str(obj.get('overlay_type') or '').lower()
  try:x=max(0,int(float(obj.get('left',0))));y=max(0,int(float(obj.get('top',0))));w=max(1,int(float(obj.get('width',1))));h=max(1,int(float(obj.get('height',1))));opacity=max(.05,min(1,float(obj.get('opacity',1))));rotation=float(obj.get('rotation',0))
  except(TypeError,ValueError):continue
  x2=min(im.width,x+w);y2=min(im.height,y+h)
  if x>=im.width or y>=im.height or x2<=x or y2<=y:continue
  color=_parse_color(obj.get('color')) or(0,0,0);stroke=max(1,min(30,int(obj.get('stroke_width') or 3)));ow,oh=x2-x,y2-y;local=Image.new('RGBA',(ow,oh),(0,0,0,0));d=ImageDraw.Draw(local)
  if kind=='text':
   text=str(obj.get('text') or '')
   if text:
    size=max(5,min(300,int(obj.get('font_size') or max(12,h*.65))));ft=_load_font(size,obj.get('font_family') or None,bool(obj.get('bold')));d.multiline_text((0,0),text,font=ft,fill=(*color,255),spacing=max(2,size//5))
  elif kind=='image':
   src=str(obj.get('data_url') or '')
   if src.startswith('data:image/') and ',' in src:
    try:
     raw=base64.b64decode(src.split(',',1)[1],validate=True)
     if len(raw)<=12*1024*1024:local=Image.open(io.BytesIO(raw)).convert('RGBA').resize((ow,oh),Image.Resampling.LANCZOS)
    except Exception:pass
  elif kind=='whiteout':d.rectangle((0,0,ow-1,oh-1),fill=(255,255,255,255))
  elif kind=='rect':d.rectangle((0,0,ow-1,oh-1),outline=(*color,255),width=stroke)
  elif kind=='ellipse':d.ellipse((0,0,ow-1,oh-1),outline=(*color,255),width=stroke)
  elif kind in{'line','arrow'}:
   d.line((0,0,ow-1,oh-1),fill=(*color,255),width=stroke)
   if kind=='arrow':
    ang=math.atan2(oh,ow);head=max(8,stroke*4);pts=[(ow-1,oh-1),(ow-1-head*math.cos(ang-.55),oh-1-head*math.sin(ang-.55)),(ow-1-head*math.cos(ang+.55),oh-1-head*math.sin(ang+.55))];d.polygon(pts,fill=(*color,255))
  if opacity<1:local.putalpha(local.getchannel('A').point(lambda a:int(a*opacity)))
  if rotation:local=local.rotate(-rotation,resample=Image.Resampling.BICUBIC,expand=True)
  px=round(x+ow/2-local.width/2);py=round(y+oh/2-local.height/2);im.alpha_composite(local,(px,py))
 return _save(im,output_format)
