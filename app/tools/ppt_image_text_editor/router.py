from __future__ import annotations
import asyncio,hashlib,json,re,time,uuid
from pathlib import Path
from fastapi import APIRouter,File,Form,HTTPException,Request,UploadFile
from fastapi.responses import FileResponse,HTMLResponse,Response
from ...config import settings
from ...core import upload_owner as _uo
from ...core import ocr_engine as _oe
from .editable_bridge import build_editable_deck
from app.tools.editable_slides.pptx_io import export_pptx
from .image_edit import available_fonts,edit_text,image_format_for_path,to_png
from .pptx_core import list_slide_images,read_media,replace_media
router=APIRouter();_ID_RE=re.compile(r"^[a-f0-9]{32}$");_EDITABLE_CONVERSION_VERSION="4"
_OCR_LIMIT=asyncio.Semaphore(1);_CONVERT_LIMIT=_OCR_LIMIT;_jobs={};_convert_jobs={};_tasks=set();_analysis_tasks={}
def _job_view(uid):
 job=_jobs.get(uid)
 if not job:return None
 view={k:v for k,v in job.items() if k not in {"result"}}
 if job["status"]=="queued":
  waiting=sorted((j for j in _jobs.values() if j["status"]=="queued" and not j.get("cancel_requested")),key=lambda j:j["created_at"])
  view["queue_position"]=next((i+1 for i,j in enumerate(waiting) if j["uid"]==uid),1)
 if job["status"]=="done":view["images"]=job.get("result",[])
 return view
def _remember_task(task,uid=None):
 _tasks.add(task);task.add_done_callback(_tasks.discard)
 if uid:
  _analysis_tasks[uid]=task
  def forget(done):
   if _analysis_tasks.get(uid) is done:_analysis_tasks.pop(uid,None)
  task.add_done_callback(forget)
def _prune_jobs():
 cutoff=time.time()-86400
 for key,job in list(_jobs.items()):
  if job["status"] in {"done","failed","cancelled"} and job.get("completed_at",0)<cutoff:_jobs.pop(key,None)
def _work_dir():p=settings.temp_dir/"ppt_image_text_editor";p.mkdir(parents=True,exist_ok=True);return p
def _src(uid):return _work_dir()/f"{uid}.pptx"
def _manifest(uid):return _work_dir()/f"{uid}.json"
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
async def _run_analysis(uid,langs):
 job=_jobs[uid]
 try:
  raw=await asyncio.to_thread(_src(uid).read_bytes);refs=await asyncio.to_thread(list_slide_images,raw);grouped={}
  for ref in refs:
   item=grouped.setdefault(ref.media_path,{"media_path":ref.media_path,"slides":[],"rel_ids":[]});item["slides"].append(ref.slide);item["rel_ids"].append(ref.rel_id)
  job["total"]=len(grouped)
  async with _OCR_LIMIT:
   if job.get("cancel_requested"):job.update(status="cancelled",completed_at=time.time());return
   job["status"]="running";job["started_at"]=time.time();result=[]
   for idx,(media_path,item) in enumerate(grouped.items()):
    if job.get("cancel_requested"):job.update(status="cancelled",completed_at=time.time());return
    try:
     png,(w,h)=await asyncio.to_thread(to_png,read_media(raw,media_path))
     words,engine=await asyncio.to_thread(_oe.recognize_image,png,langs,preprocess=True,allow_local_easyocr=_oe.local_easyocr_safe())
     result.append({**item,"index":idx,"width":w,"height":h,"engine":engine,"preview_url":f"/tools/ppt-image-text-editor/preview/{uid}/{idx}","words":words})
    except Exception as exc:result.append({**item,"index":idx,"width":0,"height":0,"words":[],"error":str(exc)})
    job["completed"]=idx+1
   cache={str(i):x[0] for i,x in enumerate(grouped.items())};data=json.loads(_manifest(uid).read_text(encoding="utf-8"));data["media_map"]=cache;data["analysis"]=result
   await asyncio.to_thread(_manifest(uid).write_text,json.dumps(data,ensure_ascii=False),encoding="utf-8")
   job.update(status="done",result=result,completed_at=time.time())
 except Exception as exc:job.update(status="failed",error=str(exc),completed_at=time.time())

@router.post("/analysis/{uid}")
async def start_analysis(uid:str,request:Request,langs:str=Form("chi_tra+eng")):
 uid=_safe_id(uid);_uo.require(uid,request);_prune_jobs();existing=_jobs.get(uid)
 if existing and existing["status"] in {"queued","running","done"}:return _job_view(uid)
 job={"uid":uid,"status":"queued","created_at":time.time(),"completed":0,"total":0,"error":None,"cancel_requested":False};_jobs[uid]=job
 task=asyncio.create_task(_run_analysis(uid,langs));_remember_task(task,uid);return _job_view(uid)

@router.post("/analysis/{uid}/cancel")
async def cancel_analysis(uid:str,request:Request):
 uid=_safe_id(uid);_uo.require(uid,request);job=_jobs.get(uid)
 if not job:raise HTTPException(404,"analysis job not found")
 if job["status"]=="queued":
  job.update(cancel_requested=True,status="cancelled",completed_at=time.time())
  task=_analysis_tasks.get(uid)
  if task:task.cancel()
 elif job["status"]=="running":job["cancel_requested"]=True
 return _job_view(uid)

@router.get("/analysis/{uid}")
async def analysis_status(uid:str,request:Request):
 uid=_safe_id(uid);_uo.require(uid,request);view=_job_view(uid)
 if view:return view
 try:data=json.loads(_manifest(uid).read_text(encoding="utf-8"))
 except FileNotFoundError:raise HTTPException(404,"upload not found")
 if data.get("analysis") is not None:return {"uid":uid,"status":"done","completed":len(data["analysis"]),"total":len(data["analysis"]),"images":data["analysis"]}
 raise HTTPException(404,"analysis job not started")

@router.get("/images/{uid}")
async def images(uid:str,request:Request,langs:str="chi_tra+eng"):
 """Backward-compatible endpoint; OCR runs off the event loop."""
 state=await start_analysis(uid,request,langs)
 while state["status"] in {"queued","running"}:
  await asyncio.sleep(.5);state=_job_view(uid)
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
def _public_convert_job(job):return {k:v for k,v in job.items() if k not in {"analyses","edits"}}
def _persist_convert_job(uid,job):
 data=json.loads(_manifest(uid).read_text(encoding="utf-8"))
 data["editable_job"]={**_public_convert_job(job),"edits":job.get("edits",[])}
 _manifest(uid).write_text(json.dumps(data,ensure_ascii=False),encoding="utf-8")
def _restore_convert_job(uid):
 try:data=json.loads(_manifest(uid).read_text(encoding="utf-8"))
 except FileNotFoundError:return None
 saved=data.get("editable_job")
 if not saved:return None
 return {**saved,"analyses":data.get("analysis") or [],"edits":saved.get("edits") or []}
def _convert_view(uid):
 job=_convert_jobs.get(uid) or _restore_convert_job(uid)
 return _public_convert_job(job) if job else None
def _build_editable_file(uid,analyses,edits):
 deck=build_editable_deck(_src(uid).read_bytes(),analyses,edits)
 _editable_path(uid).write_bytes(export_pptx(deck))
async def _run_editable_conversion(uid):
 job=_convert_jobs[uid]
 try:
  async with _CONVERT_LIMIT:
   job.update(status="running",started_at=time.time());_persist_convert_job(uid,job)
   await asyncio.to_thread(_build_editable_file,uid,job["analyses"],job["edits"])
   job.update(status="done",completed_at=time.time());_persist_convert_job(uid,job)
 except Exception as exc:
  job.update(status="failed",error=str(exc),completed_at=time.time());_persist_convert_job(uid,job)

@router.post("/editable/{uid}")
async def editable(uid:str,request:Request,edits_json:str=Form("[]")):
 uid=_safe_id(uid);_uo.require(uid,request);edits=_parse_edits(edits_json);m=json.loads(_manifest(uid).read_text(encoding="utf-8"));analyses=m.get("analysis") or []
 if not analyses:raise HTTPException(400,"請先執行 OCR 分析")
 signature=hashlib.sha256((_EDITABLE_CONVERSION_VERSION+"\n"+json.dumps(edits,ensure_ascii=False,sort_keys=True)).encode()).hexdigest()
 existing=_convert_jobs.get(uid) or _restore_convert_job(uid)
 if existing and existing["status"] in {"queued","running"}:
  if existing["signature"]!=signature:raise HTTPException(409,"這份簡報正在轉換，請等待完成")
  if uid not in _convert_jobs:
   existing["status"]="queued";_convert_jobs[uid]=existing;_persist_convert_job(uid,existing);task=asyncio.create_task(_run_editable_conversion(uid));_remember_task(task)
  return _convert_view(uid)
 if existing and existing["status"]=="done" and existing["signature"]==signature and _editable_path(uid).exists():return _public_convert_job(existing)
 base=Path(m.get("filename") or "presentation.pptx").stem
 job={"uid":uid,"status":"queued","created_at":time.time(),"completed_at":None,"error":None,"signature":signature,"filename":f"{base}_editable.pptx","analyses":analyses,"edits":edits}
 _convert_jobs[uid]=job;_persist_convert_job(uid,job);task=asyncio.create_task(_run_editable_conversion(uid));_remember_task(task);return _convert_view(uid)

@router.get("/editable/{uid}")
async def editable_status(uid:str,request:Request):
 uid=_safe_id(uid);_uo.require(uid,request);job=_convert_jobs.get(uid)
 if not job:
  job=_restore_convert_job(uid)
  if job and job["status"] in {"queued","running"}:
   job["status"]="queued";_convert_jobs[uid]=job;_persist_convert_job(uid,job);task=asyncio.create_task(_run_editable_conversion(uid));_remember_task(task)
 if not job:raise HTTPException(404,"editable conversion not started")
 return _public_convert_job(job)

@router.get("/editable/{uid}/download")
async def editable_download(uid:str,request:Request):
 uid=_safe_id(uid);_uo.require(uid,request);job=_convert_jobs.get(uid) or _restore_convert_job(uid)
 if not job or job["status"]!="done" or not _editable_path(uid).exists():raise HTTPException(409,"可編輯 PPTX 尚未完成")
 return FileResponse(str(_editable_path(uid)),media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",filename=job["filename"])
