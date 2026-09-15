from __future__ import annotations
import asyncio,hashlib,json,re,threading,uuid
from pathlib import Path
from fastapi import APIRouter,File,Form,HTTPException,Request,UploadFile
from fastapi.responses import FileResponse,HTMLResponse,Response
from ...config import settings
from ...core import upload_owner as _uo
from ...core import ocr_engine as _oe
from ...core.job_manager import job_manager
from .editable_bridge import build_editable_pptx
from .image_edit import available_fonts,edit_text,image_format_for_path,to_png
from .pptx_core import list_slide_images,read_media,replace_media
router=APIRouter();_ID_RE=re.compile(r"^[a-f0-9]{32}$");_EDITABLE_CONVERSION_VERSION="6"
# OCR 與可編輯 PPTX 轉換都很吃 CPU / RAM；同一個 container 內一次只跑一件，
# 但工作仍由全站 JobManager 排程，因此其他頁面、其他使用者與「我的作業」不會卡住。
_PPT_HEAVY_LIMIT=threading.Semaphore(1);_MANIFEST_LOCK=threading.RLock()
def _work_dir():p=settings.temp_dir/"ppt_image_text_editor";p.mkdir(parents=True,exist_ok=True);return p
def _src(uid):return _work_dir()/f"{uid}.pptx"
def _manifest(uid):return _work_dir()/f"{uid}.json"
def _read_manifest(uid):
 with _MANIFEST_LOCK:return json.loads(_manifest(uid).read_text(encoding="utf-8"))
def _patch_manifest(uid,**values):
 with _MANIFEST_LOCK:
  data=json.loads(_manifest(uid).read_text(encoding="utf-8"));data.update(values)
  _manifest(uid).write_text(json.dumps(data,ensure_ascii=False),encoding="utf-8")
 return data
def _safe_id(uid):
 if not _ID_RE.fullmatch(uid or ""):raise HTTPException(400,"invalid upload id")
 return uid
def _parse_edits(s):
 try:
  e=json.loads(s)
  if not isinstance(e,list):raise ValueError
  return e
 except Exception as exc:raise HTTPException(400,"edits_json 格式錯誤") from exc
def _style(e):
 try:size=int(e.get("font_size")) if e.get("font_size") not in (None,"","auto") else None
 except (TypeError,ValueError):size=None
 return {"font_family":e.get("font_family") or None,"font_size":size,"text_color":e.get("text_color") or None,"bold":bool(e.get("bold",False))}
def _apply_edits(raw,edits,output_format="PNG"):
 current,_=to_png(raw);ordered=sorted(edits,key=lambda x:int(x.get("top",0)),reverse=True)
 for i,e in enumerate(ordered):
  try:left,top,width,height=int(e["left"]),int(e["top"]),int(e["width"]),int(e["height"])
  except (KeyError,TypeError,ValueError) as exc:raise HTTPException(400,"修改座標格式錯誤") from exc
  current=edit_text(current,box=(left,top,left+width,top+height),new_text=str(e.get("new_text","")),output_format=output_format if i==len(ordered)-1 else "PNG",**_style(e))
 return current
@router.get("/",response_class=HTMLResponse)
async def index(request:Request):return request.app.state.templates.TemplateResponse(request,"ppt_image_text_editor.html",{"request":request})
@router.get("/fonts")
async def fonts():return {"fonts":available_fonts()}
@router.post("/upload")
async def upload(request:Request,file:UploadFile=File(...)):
 name=file.filename or "input.pptx"
 if not name.lower().endswith(".pptx"):raise HTTPException(400,"目前僅支援 .pptx")
 raw=await file.read()
 if not raw:raise HTTPException(400,"空檔案")
 if len(raw)>200*1024*1024:raise HTTPException(413,"PPTX 超過 200 MB 上限")
 try:refs=list_slide_images(raw)
 except Exception as exc:raise HTTPException(400,f"PPTX 解析失敗：{exc}") from exc
 uid=uuid.uuid4().hex;_src(uid).write_bytes(raw);_manifest(uid).write_text(json.dumps({"filename":name},ensure_ascii=False),encoding="utf-8");_uo.record(uid,request);unique=sorted({r.media_path for r in refs})
 return {"upload_id":uid,"filename":name,"slides_with_images":len({r.slide for r in refs}),"image_refs":len(refs),"unique_images":len(unique)}
def _wait_heavy_slot(job):
 while not _PPT_HEAVY_LIMIT.acquire(timeout=.5):
  if job.cancelled:return False
  job.message="等待 PPT OCR／轉換資源…"
 return True
def _analysis_view(uid):
 try:data=_read_manifest(uid)
 except FileNotFoundError:return None
 jid=data.get("analysis_job_id");job=job_manager.get(jid) if jid else None
 if not job:
  result=data.get("analysis")
  return ({"uid":uid,"status":"done","completed":len(result),"total":len(result),"images":result} if result is not None else None)
 total=int((job.meta or {}).get("total") or 0);completed=min(total,int(round(job.progress*total))) if total else 0
 job_manager.mark_polled(job.id)
 status={"pending":"queued","error":"failed","interrupted":"failed"}.get(job.status,job.status)
 view={"uid":uid,"job_id":job.id,"status":status,"created_at":job.created_at,"completed":completed,"total":total,"error":job.error}
 if job.status=="pending":view["queue_position"]=job_manager.queue_positions().get(job.id)
 if job.status=="done":view["images"]=data.get("analysis") or []
 return view
def _run_analysis(job,uid,langs):
 if not _wait_heavy_slot(job):return
 try:
  job.message="讀取投影片圖片…";raw=_src(uid).read_bytes();refs=list_slide_images(raw);grouped={}
  for ref in refs:
   item=grouped.setdefault(ref.media_path,{"media_path":ref.media_path,"slides":[],"rel_ids":[]});item["slides"].append(ref.slide);item["rel_ids"].append(ref.rel_id)
  total=len(grouped);job.meta["total"]=total;result=[]
  for idx,(media_path,item) in enumerate(grouped.items()):
   if job.cancelled:return
   job.message=f"OCR 辨識中（{idx+1}/{total}）"
   try:
    png,(w,h)=to_png(read_media(raw,media_path));words,engine=_oe.recognize_image(png,langs,preprocess=True,allow_local_easyocr=_oe.local_easyocr_safe())
    result.append({**item,"index":idx,"width":w,"height":h,"engine":engine,"preview_url":f"/tools/ppt-image-text-editor/preview/{uid}/{idx}","words":words})
   except Exception as exc:result.append({**item,"index":idx,"width":0,"height":0,"words":[],"error":str(exc)})
   job.progress=(idx+1)/max(1,total)
  cache={str(i):x[0] for i,x in enumerate(grouped.items())};_patch_manifest(uid,media_map=cache,analysis=result)
  job.message=f"OCR 完成，共辨識 {total} 張圖片"
 finally:_PPT_HEAVY_LIMIT.release()

@router.post("/analysis/{uid}")
async def start_analysis(uid:str,request:Request,langs:str=Form("chi_tra+eng")):
 uid=_safe_id(uid);_uo.require(uid,request);existing=_analysis_view(uid)
 if existing and existing["status"] in {"queued","running","done"}:return existing
 m=_read_manifest(uid);name=Path(m.get("filename") or "presentation.pptx").name
 job=job_manager.submit("ppt-image-text-editor",lambda j:_run_analysis(j,uid,langs),meta={"filename":f"OCR 辨識｜{name}","upload_id":uid,"operation":"ocr","view_url":f"/tools/ppt-image-text-editor/?upload={uid}"},request=request)
 _patch_manifest(uid,analysis_job_id=job.id);return _analysis_view(uid)

@router.post("/analysis/{uid}/cancel")
async def cancel_analysis(uid:str,request:Request):
 uid=_safe_id(uid);_uo.require(uid,request);m=_read_manifest(uid);jid=m.get("analysis_job_id")
 if not jid or not job_manager.get(jid):raise HTTPException(404,"analysis job not found")
 job_manager.cancel(jid);return _analysis_view(uid)

@router.get("/analysis/{uid}")
async def analysis_status(uid:str,request:Request):
 uid=_safe_id(uid);_uo.require(uid,request);view=_analysis_view(uid)
 if view:return view
 raise HTTPException(404,"analysis job not started")

@router.get("/images/{uid}")
async def images(uid:str,request:Request,langs:str="chi_tra+eng"):
 """Backward-compatible endpoint; OCR runs off the event loop."""
 state=await start_analysis(uid,request,langs)
 while state["status"] in {"queued","running"}:
  await asyncio.sleep(.5);state=_analysis_view(uid)
 if state["status"]=="failed":raise HTTPException(500,state.get("error") or "OCR failed")
 if state["status"]=="cancelled":raise HTTPException(409,"OCR cancelled")
 return {"upload_id":uid,"fonts":available_fonts(),"images":state.get("images",[])}

@router.get("/preview/{uid}/{index}")
async def preview(uid:str,index:int,request:Request):
 uid=_safe_id(uid);_uo.require(uid,request);m=json.loads(_manifest(uid).read_text(encoding="utf-8"));path=(m.get("media_map") or {}).get(str(index))
 if not path:raise HTTPException(404,"image not analyzed")
 png,_=to_png(read_media(_src(uid).read_bytes(),path));return Response(png,media_type="image/png")
@router.post("/preview/{uid}/{index}")
async def rendered_preview(uid:str,index:int,request:Request,edits_json:str=Form(...)):
 uid=_safe_id(uid);_uo.require(uid,request);edits=_parse_edits(edits_json);m=json.loads(_manifest(uid).read_text(encoding="utf-8"));path=(m.get("media_map") or {}).get(str(index))
 if not path:raise HTTPException(404,"image not analyzed")
 es=[e for e in edits if int(e.get("image_index",-1))==index];original=read_media(_src(uid).read_bytes(),path);png=_apply_edits(original,es,"PNG") if es else to_png(original)[0];return Response(png,media_type="image/png",headers={"Cache-Control":"no-store"})
@router.post("/export/{uid}")
async def export(uid:str,request:Request,edits_json:str=Form(...)):
 uid=_safe_id(uid);_uo.require(uid,request);edits=_parse_edits(edits_json);m=json.loads(_manifest(uid).read_text(encoding="utf-8"));media_map=m.get("media_map") or {};raw=_src(uid).read_bytes();by_media={}
 for e in edits:
  path=media_map.get(str(e.get("image_index")))
  if not path:raise HTTPException(400,"找不到指定圖片；請先執行 OCR 分析")
  by_media.setdefault(path,[]).append(e)
 replacements={path:_apply_edits(read_media(raw,path),es,image_format_for_path(path)) for path,es in by_media.items()};out=replace_media(raw,replacements);out_path=_work_dir()/f"{uid}_edited.pptx";out_path.write_bytes(out);base=Path(m.get("filename") or "edited.pptx").stem;return FileResponse(str(out_path),media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",filename=f"{base}_edited.pptx")

def _editable_path(uid):return _work_dir()/f"{uid}_editable.pptx"
def _convert_view(uid):
 try:data=_read_manifest(uid)
 except FileNotFoundError:return None
 saved=data.get("editable_job") or {};jid=saved.get("job_id");job=job_manager.get(jid) if jid else None
 if job:
  job_manager.mark_polled(job.id)
  status={"pending":"queued","error":"failed","interrupted":"failed"}.get(job.status,job.status)
  return {"uid":uid,"job_id":job.id,"status":status,"created_at":job.created_at,"completed_at":job.updated_at if job.status in {"done","error","cancelled","interrupted"} else None,"error":job.error,"signature":saved.get("signature"),"filename":job.result_filename or saved.get("filename")}
 if saved.get("status")=="done" and _editable_path(uid).exists():return saved
 return None
def _build_editable_file(uid,analyses,edits):
 _editable_path(uid).write_bytes(build_editable_pptx(_src(uid).read_bytes(),analyses,edits))
def _run_editable_conversion(job,uid,analyses,edits,filename,signature):
 if not _wait_heavy_slot(job):return
 try:
  if job.cancelled:return
  job.message="正在保留原範本並建立可編輯文字…";job.progress=.15
  _build_editable_file(uid,analyses,edits)
  if job.cancelled:
   _editable_path(uid).unlink(missing_ok=True);return
  job.result_path=_editable_path(uid);job.result_filename=filename;job.progress=.95;job.message="可編輯 PPTX 已完成"
  _patch_manifest(uid,editable_job={"job_id":job.id,"status":"done","signature":signature,"filename":filename})
 finally:_PPT_HEAVY_LIMIT.release()

@router.post("/editable/{uid}")
async def editable(uid:str,request:Request,edits_json:str=Form("[]")):
 uid=_safe_id(uid);_uo.require(uid,request);edits=_parse_edits(edits_json);m=_read_manifest(uid);analyses=m.get("analysis") or []
 if not analyses:raise HTTPException(400,"請先執行 OCR 分析")
 signature=hashlib.sha256((_EDITABLE_CONVERSION_VERSION+"\n"+json.dumps(edits,ensure_ascii=False,sort_keys=True)).encode()).hexdigest()
 existing=_convert_view(uid)
 if existing and existing["status"] in {"queued","running"}:
  if existing["signature"]!=signature:raise HTTPException(409,"這份簡報正在轉換，請等待完成")
  return existing
 if existing and existing["status"]=="done" and existing["signature"]==signature and _editable_path(uid).exists():return existing
 original=Path(m.get("filename") or "presentation.pptx");filename=f"{original.stem}_editable.pptx"
 ready=threading.Event()
 def run(j):ready.wait(timeout=10);_run_editable_conversion(j,uid,analyses,edits,filename,signature)
 job=job_manager.submit("ppt-image-text-editor",run,meta={"filename":f"可編輯 PPTX｜{original.name}","upload_id":uid,"operation":"editable-pptx","view_url":f"/tools/ppt-image-text-editor/?upload={uid}"},request=request)
 try:_patch_manifest(uid,editable_job={"job_id":job.id,"status":"queued","signature":signature,"filename":filename})
 finally:ready.set()
 return _convert_view(uid)

@router.get("/editable/{uid}")
async def editable_status(uid:str,request:Request):
 uid=_safe_id(uid);_uo.require(uid,request);job=_convert_view(uid)
 if not job:raise HTTPException(404,"editable conversion not started")
 return job

@router.get("/editable/{uid}/download")
async def editable_download(uid:str,request:Request):
 uid=_safe_id(uid);_uo.require(uid,request);job=_convert_view(uid)
 if not job or job["status"]!="done" or not _editable_path(uid).exists():raise HTTPException(409,"可編輯 PPTX 尚未完成")
 return FileResponse(str(_editable_path(uid)),media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",filename=job["filename"])
