from __future__ import annotations
import io,json,re,uuid
from pathlib import Path
from fastapi import APIRouter,File,Form,HTTPException,Request,UploadFile
from fastapi.responses import FileResponse,HTMLResponse,Response
from PIL import Image
from ...config import settings
from ...core import upload_owner as _uo
from ...core import ocr_engine as _oe
from ..ppt_image_text_editor.image_edit import apply_overlays,available_fonts,edit_text,image_format_for_path,to_png
router=APIRouter(); _ID_RE=re.compile(r"^[a-f0-9]{32}$"); _ALLOWED={".png",".jpg",".jpeg",".webp",".bmp",".tif",".tiff"}; _MEDIA={"PNG":"image/png","JPEG":"image/jpeg","WEBP":"image/webp","BMP":"image/bmp","TIFF":"image/tiff"}
def _work_dir():
 p=settings.temp_dir/"image_text_editor";p.mkdir(parents=True,exist_ok=True);return p
def _safe_id(uid):
 if not _ID_RE.fullmatch(uid or ""):raise HTTPException(400,"invalid upload id")
 return uid
def _manifest(uid):return _work_dir()/f"{uid}.json"
def _source(uid,m):return _work_dir()/f"{uid}{m['suffix']}"
def _load(uid,request):
 uid=_safe_id(uid);_uo.require(uid,request);p=_manifest(uid)
 if not p.exists():raise HTTPException(404,"upload not found")
 m=json.loads(p.read_text(encoding="utf-8"));return m,_source(uid,m).read_bytes()
def _parse_edits(s):
 try:
  e=json.loads(s)
  if not isinstance(e,list):raise ValueError
  return e
 except Exception as exc:raise HTTPException(400,"edits_json 格式錯誤") from exc
def _style(e):
 size=e.get("font_size")
 try:size=int(size) if size not in (None,"","auto") else None
 except (TypeError,ValueError):size=None
 return {"font_family":e.get("font_family") or None,"font_size":size,"text_color":e.get("text_color") or None,"bold":bool(e.get("bold",False))}
def _apply(raw,edits,output_format="PNG"):
 text_edits=[e for e in edits if e.get("kind")!="overlay"];overlays=[e for e in edits if e.get("kind")=="overlay"]
 current,_=to_png(raw);ordered=sorted(text_edits,key=lambda x:int(x.get("top",0)),reverse=True)
 for e in ordered:
  try:left,top,width,height=int(e["left"]),int(e["top"]),int(e["width"]),int(e["height"])
  except (KeyError,TypeError,ValueError) as exc:raise HTTPException(400,"修改座標格式錯誤") from exc
  current=edit_text(current,box=(left,top,left+width,top+height),new_text=str(e.get("new_text","")),output_format="PNG",**_style(e))
 if overlays:return apply_overlays(current,overlays,output_format)
 if text_edits:
  with Image.open(io.BytesIO(current)) as im:
   buf=io.BytesIO();fmt=(output_format or "PNG").upper();im=im.convert("RGB") if fmt=="JPEG" else im;im.save(buf,format=fmt,**({"quality":95} if fmt=="JPEG" else {}));return buf.getvalue()
 return current
@router.get("/",response_class=HTMLResponse)
async def index(request:Request):return request.app.state.templates.TemplateResponse(request,"image_text_editor.html",{"request":request})
@router.get("/fonts")
async def fonts():return {"fonts":available_fonts()}
@router.post("/upload")
async def upload(request:Request,file:UploadFile=File(...),langs:str=Form("chi_tra+eng")):
 name=Path(file.filename or "image.png").name;suffix=Path(name).suffix.lower()
 if suffix not in _ALLOWED:raise HTTPException(400,"支援 PNG / JPG / JPEG / WebP / BMP / TIFF")
 raw=await file.read()
 if not raw:raise HTTPException(400,"空檔案")
 if len(raw)>50*1024*1024:raise HTTPException(413,"圖片超過 50 MB 上限")
 try:png,(width,height)=to_png(raw);words,engine=_oe.recognize_image(png,langs,preprocess=True,allow_local_easyocr=_oe.local_easyocr_safe())
 except Exception as exc:raise HTTPException(400,f"圖片/OCR 處理失敗：{exc}") from exc
 uid=uuid.uuid4().hex;(_work_dir()/f"{uid}{suffix}").write_bytes(raw);_manifest(uid).write_text(json.dumps({"filename":name,"suffix":suffix},ensure_ascii=False),encoding="utf-8");_uo.record(uid,request)
 return {"upload_id":uid,"filename":name,"width":width,"height":height,"engine":engine,"words":words,"fonts":available_fonts(),"preview_url":f"/tools/image-text-editor/preview/{uid}"}
@router.get("/preview/{uid}")
async def preview(uid:str,request:Request):
 _,raw=_load(uid,request);png,_=to_png(raw);return Response(png,media_type="image/png",headers={"Cache-Control":"no-store"})
@router.post("/preview/{uid}")
async def rendered_preview(uid:str,request:Request,edits_json:str=Form(...)):
 _,raw=_load(uid,request);edits=_parse_edits(edits_json);png=_apply(raw,edits,"PNG") if edits else to_png(raw)[0];return Response(png,media_type="image/png",headers={"Cache-Control":"no-store"})
@router.post("/export/{uid}")
async def export(uid:str,request:Request,edits_json:str=Form(...)):
 m,raw=_load(uid,request);edits=_parse_edits(edits_json);fmt=image_format_for_path(m["filename"])
 if edits:out=_apply(raw,edits,fmt)
 else:
  with Image.open(io.BytesIO(raw)) as im:
   buf=io.BytesIO()
   if fmt=="JPEG" and im.mode not in ("RGB","L"):im=im.convert("RGB")
   im.save(buf,format=fmt,**({"quality":95} if fmt=="JPEG" else {}));out=buf.getvalue()
 stem=Path(m["filename"]).stem;out_path=_work_dir()/f"{uid}_edited{m['suffix']}";out_path.write_bytes(out);return FileResponse(str(out_path),media_type=_MEDIA.get(fmt,"application/octet-stream"),filename=f"{stem}_edited{m['suffix']}")
