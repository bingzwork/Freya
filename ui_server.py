import argparse
import json
import mimetypes
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from main import FreyaApp
from app.core.initializer import SystemConfig
from app.capabilities.formatter import format_capability_result
from app.capabilities.router import CapabilityResult
FREYA=None
SUBSCRIBERS=set()
LAST_IMAGE_SUBJECT = ""
LOCK=threading.Lock()
SUPPORTED_EXTENSIONS={".jpg",".jpeg",".png",".webp",".mp3",".wav",".m4a",".flac",".mp4",".mov",".webm",".txt",".md",".pdf",".docx",".csv",".xlsx",".json"}
IMAGE_EXTENSIONS={".jpg",".jpeg",".png",".webp",".gif",".bmp"}
RESEARCH_WORDS=("research","search","look this up","find information","deep web","latest","recent","current")
UNKNOWN_PERSON_REQUEST=re.compile(r"\b(find|search|latest|recent|current|look\s+up)\b.{0,80}\b(photo|picture|image)\b.{0,80}\b(this person|the person|him|her|them)\b",re.I)

def emit_avatar(state,**metadata):
    payload={"state":state,**metadata}
    with LOCK: subscribers=list(SUBSCRIBERS)
    for subscriber in subscribers:
        try: subscriber.put_nowait(payload)
        except queue.Full: pass

def _ffprobe(path):
    executable=shutil.which("ffprobe") or "ffprobe"; result=subprocess.run([executable,"-v","error","-show_format","-show_streams","-of","json",str(path)],capture_output=True,text=True,timeout=30,check=False)
    if result.returncode: raise RuntimeError(result.stderr.strip()[-600:] or "ffprobe failed")
    return json.loads(result.stdout or "{}")

def _document_summary(question, content):
    """Return a grounded local summary without re-routing attachment language."""
    clean = re.sub(r"\s+", " ", str(content or "")).strip()
    if not clean:
        return "The attached document contains no readable text."
    if len(clean) <= 1800:
        return f"The attached document contains: {clean}"
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    excerpt = " ".join(sentences[:5]).strip() or clean[:1800]
    return f"Summary of the attached document: {excerpt[:1800]}"

def _document_text(path):
    suffix=path.suffix.lower()
    if suffix in {".txt",".md",".json",".csv"}: return path.read_text(encoding="utf-8",errors="replace")[:120000]
    if suffix==".pdf":
        try:
            from pypdf import PdfReader
            return "\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)[:120000]
        except Exception as exc: return f"PDF text extraction unavailable: {exc}"
    if suffix==".docx":
        try:
            from docx import Document
            return "\n".join(p.text for p in Document(str(path)).paragraphs)[:120000]
        except Exception as exc: return f"DOCX text extraction unavailable: {exc}"
    if suffix==".xlsx":
        try:
            from openpyxl import load_workbook
            workbook=load_workbook(str(path),read_only=True,data_only=True); rows=[]
            for sheet in workbook.worksheets:
                rows.append(f"Sheet: {sheet.title}")
                for row in sheet.iter_rows(values_only=True):
                    rows.append("\t".join("" if value is None else str(value) for value in row))
                    if len(rows)>6000: break
            return "\n".join(rows)[:120000]
        except Exception as exc: return f"XLSX text extraction unavailable: {exc}"
    return ""

def _execute_named_capability(router, capability_name, query, **context):
    """Execute a declared capability without rematching away explicit inputs."""
    capability_router=getattr(router,"_capability_router",None)
    executor=getattr(capability_router,"execute_named",None)
    if callable(executor):
        return executor(capability_name,query,**context)
    return router.execute_capability(capability_name,query,**context)

def _image_paths(workspace,paths):
    root=(workspace/"data"/"ui_uploads").resolve(); found=[]
    for raw in paths[:8] if isinstance(paths,list) else []:
        path=Path(str(raw)).resolve()
        if root in path.parents and path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS: found.append(path)
    return found
def _attachment_paths(workspace,paths):
    root=(workspace/"data"/"ui_uploads").resolve(); found=[]
    for raw in paths[:8] if isinstance(paths,list) else []:
        candidate=Path(str(raw)).resolve()
        if root in candidate.parents and candidate.is_file() and candidate.suffix.lower() in SUPPORTED_EXTENSIONS:
            found.append(candidate)
    return found


def _vision_context(workspace, paths, question):
    images = _image_paths(workspace, paths)
    if not images:
        return "", {"processed": False, "paths": []}
    emit_avatar("READING", activity="vision", image_count=len(images))
    router = getattr(getattr(getattr(FREYA, "system", None), "facade", None), "_router", None)
    image_paths = [str(path) for path in images]
    if router is None:
        return "", {"processed": False, "paths": image_paths, "error": "Vision routing is unavailable because the canonical router is not initialized"}
    try:
        result = _bounded_call(router.execute_capability, 60.0, "vision", question, paths=image_paths, question=question, capability_action="structured_analyze", original_request=question)
        if isinstance(result, dict):
            success = bool(result.get("success"))
            data = result.get("data") if isinstance(result.get("data"), dict) else result
            error = str(result.get("error") or result.get("message") or "Multimodal vision could not process the attached image")
        else:
            success = bool(getattr(result, "success", False))
            data = getattr(result, "data", None) if isinstance(getattr(result, "data", None), dict) else {}
            error = str(getattr(result, "error", None) or getattr(result, "message", None) or "Multimodal vision could not process the attached image")
        if not success or not isinstance(data, dict):
            emit_avatar("ERROR", message=error)
            emit_avatar("IDLE", activity="vision_failed")
            return "", {"processed": False, "paths": image_paths, "error": error}
        text_value = str(data.get("text") or data.get("message") or "").strip()
        observations = data.get("observations") if isinstance(data.get("observations"), dict) else {}
        return "\n\n[GROUNDed VISUAL CONTEXT FROM VISIONCAPABILITY]\n" + text_value[:12000], {"processed": True, "paths": image_paths, "text": text_value, "observations": observations}
    except Exception as error:
        emit_avatar("ERROR", message=str(error))
        emit_avatar("IDLE", activity="vision_failed")
        return "", {"processed": False, "paths": image_paths, "error": str(error)}

def _has_supplied_identity(question):
    return bool(re.search(r"\bof\s+(?:[\"']([^\"']+)[\"']|([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}))",question)) or bool(re.search(r"\b(?:named|called|name is)\s+[A-Za-z][A-Za-z -]{1,60}",question,re.I))

IMAGE_SEARCH_RE = re.compile(r"\b(?:find|search|show|look\s+for|give\s+me|want|fetch)\b.{0,80}\b(?:photo(?:['’]?s)?|picture(?:s)?|image(?:s)?)\b|\b(?:photo(?:['’]?s)?|picture(?:s)?|image(?:s)?)\b.{0,80}\b(?:of|for)\b", re.I)
FACEBOOK_FOLLOWUP_RE = re.compile(r"\b(?:facebook|fb)\b", re.I)

def _is_image_search_request(question):
    value = str(question or "")
    if REVERSE_IMAGE_RE.search(value):
        return False
    return bool(IMAGE_SEARCH_RE.search(value))

REVERSE_IMAGE_RE = re.compile(r"\b(?:find\s+(?:similar|other|copies|where)|reverse\s+search|search\s+using|where\s+(?:did|is)\s+this|find\s+this\s+image)\b", re.I)

def _is_reverse_image_request(question):
    return bool(REVERSE_IMAGE_RE.search(str(question or "")))
def _direct_social_response(question):
    """Handle bounded courtesy turns without invoking research or the LLM.

    This is a routing/control optimization, not a replacement for knowledge
    answers: only short, unambiguous social turns are eligible.
    """
    normalized = re.sub(r"[^a-z0-9\s?]", "", str(question or "").lower()).strip()
    if not normalized or len(normalized.split()) > 8:
        return None
    if re.fullmatch(r"(?:hi|hello|hey|good morning|good afternoon|good evening)(?: freya)?", normalized):
        return "Hello. I’m Freya. What would you like to work on?"
    if re.fullmatch(r"(?:how are you|how are you doing|what's up|whats up)\??", normalized):
        return "I’m doing well and ready to help. What would you like to explore?"
    if re.fullmatch(r"(?:thanks|thank you|thank you freya|thanks freya)", normalized):
        return "You’re welcome. I’m here if you need anything else."
    if re.fullmatch(r"(?:bye|goodbye|see you|good night)(?: freya)?", normalized):
        return "Goodbye. I’ll be here when you’re ready to continue."
    return None



def _is_freshness_sensitive_request(question):
    normalized=" ".join(str(question or "").lower().split())
    return bool(re.search(r"\b(?:latest|newest|current|currently|today|now|recent|price|cost|benchmark|specs?|specification|release|availability|version|generation|vs\.?|versus|compare|comparison)\b", normalized))

def _research_text_request(question):
    router=getattr(getattr(getattr(FREYA,"system",None),"facade",None),"_router",None)
    if router is None:
        raise RuntimeError("Research routing is unavailable because the canonical router is not initialized")
    research_query=re.sub(r"^\s*(?:please\s+)?(?:search|look\s+up|find|show)\s+(?:the\s+)?(?:public\s+)?(?:web|internet)?\s*(?:for|about)?\s*", "", str(question or ""), flags=re.I).strip(" .?!") or str(question or "").strip()
    research_query=re.sub(r"\btoday(?:'s|s)?\b", "latest", research_query, flags=re.I).strip()
    result=_bounded_call(router.execute_capability,45.0,"research_capability",research_query,capability_action="research_topic",topic=research_query,original_request=question,max_sources=8)
    data=getattr(result,"data",None) if isinstance(getattr(result,"data",None),dict) else {}
    if getattr(result,"success",False):
        return result,data
    try:
        from app.research.capability import WebSearchTool
        search=WebSearchTool().search(research_query,max_results=8)
        records=search.get("results",[]) if isinstance(search,dict) else []
        if records:
            lines=[]
            citations=[]
            for item in records:
                if not isinstance(item,dict):
                    continue
                title=str(item.get("title") or "Public web result").strip()
                url=str(item.get("url") or "").strip()
                if url:
                    lines.append(f"- {title}: {url}")
                    citations.append({"title":title,"url":url,"snippet":str(item.get("snippet") or "")})
            if lines:
                message="I found public-web results for this request. Full page synthesis was unavailable, so I am showing the retrieved sources without inventing claims.\n\n"+"\n".join(lines)
                fallback=CapabilityResult(success=True,data={"sources":citations,"citations":citations,"results":records,"partial":True},message=message,capability_name="research_capability")
                return fallback,fallback.data
    except Exception:
        pass
    return result,data


def _image_search_query(question):
    query=" ".join(str(question or "").strip().split())
    query=re.sub(r"^\s*(?:please\s+)?(?:find|search|show|look\s+for|give\s+me|fetch|want)\s+(?:me\s+)?", "", query, flags=re.I)
    query=re.sub(r"\b(?:photo(?:['’]?s)?|pictures?|images?)\b", "", query, flags=re.I)
    query=re.sub(r"^\s*(?:of|for)\s+", "", query, flags=re.I)
    return re.sub(r"\s+", " ", query).strip(" .?!\t\r\n")

def _bounded_call(function, timeout_seconds, *args, **kwargs):
    executor=ThreadPoolExecutor(max_workers=1, thread_name_prefix="freya-foreground")
    future=executor.submit(function, *args, **kwargs)
    try:
        return future.result(timeout=max(1.0,float(timeout_seconds)))
    except FutureTimeoutError as error:
        future.cancel()
        raise TimeoutError(f"Foreground operation timed out after {timeout_seconds:.0f} seconds") from error
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

def _record_conversation_turn(role, content):
    try:
        memory=getattr(getattr(FREYA,"system",None),"_memory_coordinator",None)
        if memory is not None and hasattr(memory,"record_conversation"):
            memory.record_conversation({"role":role,"content":str(content)})
    except Exception:
        pass

def _recent_image_subject():
    global LAST_IMAGE_SUBJECT
    try:
        memory=getattr(getattr(FREYA,"system",None),"_memory_coordinator",None)
        history=memory.get_conversation_context(limit=8) if memory is not None else []
        for turn in reversed(history or []):
            content=str(turn.get("content") or "") if isinstance(turn,dict) else str(getattr(turn,"content",""))
            if _is_image_search_request(content):
                subject=_image_search_query(content)
                if subject: return subject
    except Exception:
        pass
    return LAST_IMAGE_SUBJECT

def _facebook_followup_search(question):
    subject=_recent_image_subject()
    if not subject: return None
    router=getattr(getattr(getattr(FREYA,"system",None),"facade",None),"_router",None)
    if router is None: return None
    query=f"{subject} Facebook"
    result=_bounded_call(router.execute_capability,20.0,"research_capability",query,capability_action="search_web",max_results=8,original_request=question)
    data=getattr(result,"data",None) if isinstance(getattr(result,"data",None),dict) else {}
    records=data.get("results",[]) if isinstance(data,dict) else []
    verified=[]
    for item in records if isinstance(records,list) else []:
        if not isinstance(item,dict): continue
        url=str(item.get("url") or item.get("href") or "").strip()
        if not url or not re.search(r"(^|\.)facebook\.com$",urlparse(url).netloc.lower()): continue
        if url.rstrip("/").lower() in {"https://facebook.com","https://www.facebook.com"}: continue
        verified.append({"title":str(item.get("title") or "Facebook result"),"url":url,"snippet":str(item.get("snippet") or "")})
    if verified:
        return "\n".join([f"I found public Facebook results related to {subject}:"]+[f"- {x['title']}: {x['url']}" for x in verified[:3]])
    return f"I couldn't verify which Facebook profile or page belongs to {subject}. I did not return the generic Facebook homepage."

def _reverse_image_search_with_attachments(question, attachments):
    router=getattr(getattr(getattr(FREYA,"system",None),"facade",None),"_router",None)
    if router is None:
        raise RuntimeError("Reverse-image routing is unavailable because the canonical router is not initialized")
    paths=_image_paths(getattr(FREYA,"workspace",Path.cwd()), attachments)
    if not paths:
        return CapabilityResult(success=False,data={"image_results":[]},message="Attach an image file before requesting reverse-image research.",capability_name="research_capability")
    emit_avatar("BROWSING",activity="reverse_image_research")
    try:
        raw = _bounded_call(router.execute_capability, 55.0, "research_capability", question, capability_action="reverse_image_search", image_path=str(paths[0]), limit=10, original_request=question)
        if isinstance(raw, dict):
            payload = dict(raw.get("data") or {}) if isinstance(raw.get("data"), dict) else {}
            candidates = raw.get("image_results") or raw.get("matches") or payload.get("image_results") or payload.get("matches") or []
            payload["image_results"] = candidates
            payload["matches"] = candidates
            success = bool(raw.get("success", bool(candidates)))
            return CapabilityResult(success=success, data=payload, message=str(raw.get("message") or raw.get("error") or ("Reverse-image research completed." if success else "Free reverse-image research returned no usable public candidates.")), capability_name="research_capability", error=None if success else str(raw.get("error") or "Free reverse-image research returned no usable public candidates."))
        return raw
    finally:
        emit_avatar("THINKING",activity="result_synthesis")

def _image_search_by_text(question):
    router=getattr(getattr(getattr(FREYA,"system",None),"facade",None),"_router",None)
    if router is None: raise RuntimeError("Image-search routing is unavailable because the canonical router is not initialized")
    query=_image_search_query(question)
    if not query:
        return CapabilityResult(success=False,data={"image_results":[]},message="I couldn't determine what subject to search for in the image request.",capability_name="research_capability")
    return _bounded_call(router.execute_capability,25.0,"research_capability",query,capability_action="image_search",max_results=8,original_request=question)

def _is_research_request(question):
    lower=question.lower(); return any(word in lower for word in RESEARCH_WORDS)

def _attachment_block(path):
    suffix=path.suffix.lower(); stat=path.stat(); header={"name":path.name,"extension":suffix,"mime_type":mimetypes.guess_type(path.name)[0] or "application/octet-stream","size_bytes":stat.st_size}
    if suffix in IMAGE_EXTENSIONS: return "Attached image was sent to VisionCapability for multimodal processing; use the grounded visual context below."
    if suffix in {".mp3",".wav",".m4a",".flac",".mp4",".mov",".webm"}:
        header["capability_route"]="audio/video inspection"
        try: header["ffprobe"]=_ffprobe(path)
        except Exception as exc: header["ffprobe_error"]=str(exc)
        if suffix in {".mp3",".wav",".m4a",".flac"}: header["transcription"]="No local speech-to-text engine is installed; metadata inspection completed without inventing a transcript."
        return "Attached media inspection:\n"+json.dumps(header,ensure_ascii=False,indent=2)
    header["capability_route"]="document/file input"; return "Attached document:\n"+json.dumps(header,ensure_ascii=False,indent=2)+"\n\nDocument content:\n"+_document_text(path)

def attachment_context(workspace,paths,question="",inputs_return_meta=False):
    if not isinstance(paths,list): return ("",{"processed":False}) if inputs_return_meta else ""
    root=(workspace/"data"/"ui_uploads").resolve(); blocks=[]
    for raw in paths[:8]:
        try:
            path=Path(str(raw)).resolve()
            if root not in path.parents or not path.is_file(): continue
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS: blocks.append(f"Attached file {path.name} is not a supported Freya file type."); continue
            if path.suffix.lower() in IMAGE_EXTENSIONS: continue
            blocks.append(_attachment_block(path))
        except (OSError,UnicodeError,ValueError) as exc: blocks.append(f"Attached file could not be read: {exc}")
    visual,meta=_vision_context(workspace,paths,question) if _image_paths(workspace,paths) else ("",{"processed":False})
    combined="\n\n".join(blocks)+visual
    return (combined,meta) if inputs_return_meta else combined

def _semantic_research_query(question):
    query=question.strip()
    query=re.sub(r"^\s*(?:please\s+|can you\s+|could you\s+|would you\s+|do\s+)?(?:a\s+)?(?:deep\s+)?(?:web\s+)?search(?:\s+and)?\s*", "", query, flags=re.I)
    query=re.sub(r"^\s*(?:find\s+information\s+about|look\s+up|find|search\s+for)\s*", "", query, flags=re.I)
    query=re.sub(r"\b(?:shown here|in this image|in this screenshot|this image|this screenshot|this photo)\b", "", query, flags=re.I)
    query=re.sub(r"\s+", " ", query).strip(" ,.!?-")
    if not query or re.fullmatch(r"(?:for|about|what is|what's|what)\s*", query, flags=re.I):
        return "what is shown in the attached image"
    return query

def _dedupe_image_results(records):
    """Keep only provider-supplied image records; never invent thumbnails."""
    unique=[]
    seen=set()
    for item in records if isinstance(records,list) else []:
        if not isinstance(item,dict):
            continue
        image_url=str(item.get("image_url") or item.get("imageUrl") or item.get("thumbnail_url") or item.get("thumbnail") or "").strip()
        page_url=str(item.get("url") or item.get("source_url") or "").strip()
        if not image_url:
            continue
        # Prefer a provider perceptual hash when available; otherwise use the
        # normalized image URL as a deterministic non-perceptual fallback.
        key=str(item.get("perceptual_hash") or item.get("image_hash") or image_url.split("?")[0].lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append({
            "title":str(item.get("title") or item.get("name") or "Image result"),
            "image_url":image_url,
            "thumbnail_url":str(item.get("thumbnail_url") or item.get("thumbnail") or image_url),
            "url":page_url,
            "source_domain":str(item.get("source_domain") or item.get("domain") or ""),
            "snippet":str(item.get("snippet") or ""),
        })
    return unique[:12]


def _research_with_visual_context(question,visual_context,visual_meta=None):
    router=getattr(getattr(getattr(FREYA,"system",None),"facade",None),"_router",None)
    if router is None: raise RuntimeError("Research routing is unavailable because the canonical router is not initialized")
    base_query=_semantic_research_query(question)
    raw_terms=(visual_meta or {}).get("search_terms",[]) if isinstance(visual_meta,dict) else []
    terms=[str(term).strip() for term in raw_terms if str(term).strip()][:5]
    queries=[]
    for term in terms:
        candidate=re.sub(r"\s+"," ",term).strip()
        if candidate and candidate.lower() not in {item.lower() for item in queries}:
            queries.append(candidate[:180])
    if not queries:
        queries=[base_query[:180]]
    results=[]
    errors=[]
    deadline = time.monotonic() + max(10.0, float(os.getenv("FREYA_VISUAL_RESEARCH_DEADLINE", "40")))
    for query in queries[:5]:
        if time.monotonic() >= deadline:
            errors.append("Overall visual research deadline reached")
            break
        try:
            result=_bounded_call(router.execute_capability, max(5.0, deadline-time.monotonic()), "research_capability", query, capability_action="research_topic", topic=query, original_request=question, visual_context=visual_context[:8000], search_query=query, max_sources=5)
        except Exception as error:
            errors.append("Visual research query timed out or failed")
            continue
        if getattr(result,"success",False):
            results.append(result)
        else:
            errors.append(str(getattr(result,"message","") or getattr(getattr(result,"data",None),"get",lambda *_: "")( "error", "Research query failed")))
    if not results:
        if errors:
            return CapabilityResult(success=False,data={"queries":queries,"errors":errors,"image_results":[]},message="Vision succeeded, but public-web research failed: " + "; ".join(errors[:3]),capability_name="research_capability")
        return CapabilityResult(success=False,data={"queries":queries,"image_results":[]},message="Vision succeeded, but no public-web research result was available.",capability_name="research_capability")
    merged={"queries":queries,"image_results":[],"errors":errors,"partial":bool(errors)}
    list_keys=("key_findings","supporting_evidence","sources","citations","conflicts","uncertainty")
    for key in list_keys:
        merged[key]=[]
    merged["answer"]=""
    merged["confidence"]=0.0
    for result in results:
        data=getattr(result,"data",None)
        if not isinstance(data,dict):
            continue
        if not merged["answer"] and data.get("answer"):
            merged["answer"]=str(data.get("answer"))
        merged["confidence"]=max(float(merged["confidence"]),float(data.get("confidence") or 0.0))
        for key in list_keys:
            value=data.get(key)
            if isinstance(value,list):
                merged[key].extend(value)
        raw_images=data.get("image_results") or data.get("results") or []
        if isinstance(raw_images,list):
            merged["image_results"].extend(raw_images)
    for key in list_keys:
        dedup=[]
        seen=set()
        for item in merged[key]:
            marker=json.dumps(item,ensure_ascii=False,sort_keys=True,default=str) if isinstance(item,(dict,list)) else str(item)
            if marker not in seen:
                seen.add(marker); dedup.append(item)
        merged[key]=dedup[:20]
    merged["image_results"]=_dedupe_image_results(merged["image_results"])
    if not merged["image_results"]:
        merged["image_results_note"]="The configured public-web research provider returned text/source records but no image thumbnails. No image card is shown unless a provider supplies a real image URL. Reverse-image search is not configured locally."
    first=results[0]
    return CapabilityResult(success=True,data=merged,message="Research completed across " + str(len(queries)) + " bounded visual queries.",capability_name="research_capability")


def _privacy_response(question,visual_text):
    if UNKNOWN_PERSON_REQUEST.search(question) and not _has_supplied_identity(question):
        return "I received and processed the image with Freya’s vision capability, but I cannot infer or identify an unknown person from their face. If you provide the person’s name or another reliable textual identity, I can use the visual context together with approved research tools to look for recent, sourced images.",True
    return "",False

class Handler(BaseHTTPRequestHandler):
    workspace=Path.cwd()
    def send_payload(self,status,payload,content_type="application/json"):
        data=payload if isinstance(payload,bytes) else json.dumps(payload,ensure_ascii=False).encode("utf-8"); self.send_response(status); self.send_header("Content-Type",content_type); self.send_header("Access-Control-Allow-Origin","*"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_OPTIONS(self):
        self.send_response(204); self.send_header("Access-Control-Allow-Origin","*"); self.send_header("Access-Control-Allow-Headers","Content-Type"); self.send_header("Access-Control-Allow-Methods","GET, POST, OPTIONS"); self.end_headers()
    def do_GET(self):
        path=urlparse(self.path).path
        if path=="/api/health": self.send_payload(200,FREYA.get_health_surface()); return
        if path=="/api/capabilities":
            try:
                from app.orchestrator.capability_registry import get_capability_registry
                registry=get_capability_registry(); items=registry.list_capabilities(active_only=False) if hasattr(registry,"list_capabilities") else []
                self.send_payload(200,{"capabilities":[{"name":getattr(item,"name",str(item)),"available":True} for item in items]})
            except Exception as exc: self.send_payload(200,{"capabilities":[],"error":str(exc)})
            return
        if path=="/api/avatar-events":
            subscriber=queue.Queue(maxsize=32)
            with LOCK: SUBSCRIBERS.add(subscriber)
            try:
                self.send_response(200); self.send_header("Content-Type","text/event-stream"); self.send_header("Access-Control-Allow-Origin","*"); self.send_header("Cache-Control","no-cache"); self.send_header("Connection","keep-alive"); self.end_headers(); self.wfile.write(b'data: {"state":"IDLE"}\n\n'); self.wfile.flush()
                while True:
                    try: data=("data: "+json.dumps(subscriber.get(timeout=20),ensure_ascii=False)).encode()+b"\n\n"
                    except queue.Empty: data=b":keepalive\n\n"
                    self.wfile.write(data); self.wfile.flush()
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError,OSError): pass
            finally:
                with LOCK: SUBSCRIBERS.discard(subscriber)
            return
        self.send_payload(404,{"error":"not found"})
    def do_POST(self):
        length=int(self.headers.get("Content-Length","0")); body=self.rfile.read(length); path=urlparse(self.path).path
        if path=="/api/upload":
            query=parse_qs(urlparse(self.path).query); filename=Path(query.get("filename",["attachment.bin"])[0]).name; suffix=Path(filename).suffix.lower()
            if suffix not in SUPPORTED_EXTENSIONS: self.send_payload(415,{"error":"This file type is not currently supported."}); return
            if len(body)>100*1024*1024: self.send_payload(413,{"error":"The attachment is larger than the 100 MB local limit."}); return
            folder=self.workspace/"data"/"ui_uploads"; folder.mkdir(parents=True,exist_ok=True); target=folder/(uuid.uuid4().hex+"_"+filename); target.write_bytes(body); self.send_payload(200,{"name":filename,"path":str(target),"size":len(body),"mime":self.headers.get("Content-Type","application/octet-stream")}); return
        if path=="/api/chat":
            try:
                payload=json.loads(body.decode("utf-8")); message=str(payload.get("message","")).strip(); attachments=payload.get("attachments",[])
                if not message and not attachments: self.send_payload(400,{"error":"Write a message or attach a file first."}); return
                context,vision_meta=attachment_context(self.workspace,attachments,message,inputs_return_meta=True); privacy,blocked=_privacy_response(message,context)
                social_response=_direct_social_response(message) if not attachments and not blocked else None
                if social_response is not None:
                    emit_avatar("SPEAKING",activity="conversation")
                    self.send_payload(200,{"answer":social_response,"image_results":[],"vision_observations":{},"research_queries":[]})
                    emit_avatar("IDLE",activity="conversation_complete")
                    return
                reverse_image_requested=_is_reverse_image_request(message) and bool(attachments)
                if blocked:
                    emit_avatar("SPEAKING",activity="privacy_response"); self.send_payload(200,{"answer":privacy}); emit_avatar("SUCCESS"); emit_avatar("IDLE"); return
                research_requested=_is_research_request(message) or _is_freshness_sensitive_request(message)
                image_search_requested=_is_image_search_request(message)
                image_results=[]
                research_data={}
                if research_requested: emit_avatar("SEARCHING",activity="research")
                emit_avatar("THINKING",activity="routing")
                if vision_meta.get("processed") and context:
                    if reverse_image_requested:
                        research_result=_reverse_image_search_with_attachments(message,attachments)
                        research_data=getattr(research_result,"data",None) if isinstance(getattr(research_result,"data",None),dict) else {}
                        image_results=_dedupe_image_results(research_data.get("image_results") or research_data.get("matches") or [])
                        answer=format_capability_result(research_result) if getattr(research_result,"success",False) else str(getattr(research_result,"error",None) or getattr(research_result,"message",None) or "Free reverse-image research returned no usable public candidates.")
                    else:
                        answer=str(vision_meta.get("text") or context.split("[END VISUAL CONTEXT]")[0]).replace("[GROUNDed VISUAL CONTEXT FROM VISIONCAPABILITY]","").strip()
                elif attachments and not reverse_image_requested:
                    attachment_paths=_attachment_paths(self.workspace,attachments)
                    if not attachment_paths:
                        answer="The attached file could not be read from Freya’s approved local upload area."
                    else:
                        source_path=attachment_paths[0]
                        router=getattr(getattr(getattr(FREYA,"system",None),"facade",None),"_router",None)
                        if source_path.suffix.lower() in IMAGE_EXTENSIONS and router is not None:
                            emit_avatar("READING",activity="vision",image_count=1)
                            raw=_bounded_call(_execute_named_capability,60.0,router,"vision",message,capability_action="analyze",paths=[str(source_path)],question=message,original_request=message)
                            if isinstance(raw,dict):
                                raw_data=raw.get("data") if isinstance(raw.get("data"),dict) else raw
                                observations=raw_data.get("observations") or raw.get("observations") or {}
                                vision_meta={"processed":bool(raw.get("success",True)),"observations":observations,"text":str(raw_data.get("text") or raw_data.get("message") or raw.get("message") or "")}
                                answer=str(raw_data.get("message") or raw_data.get("text") or raw.get("message") or "Vision completed, but returned no readable description.")
                            else:
                                answer=str(getattr(raw,"message",None) or getattr(raw,"error",None) or "Vision completed, but returned no readable description.")
                        elif router is not None:
                            emit_avatar("READING",activity="file_input",file_name=source_path.name)
                            raw=_bounded_call(_execute_named_capability,30.0,router,"file_input",message,capability_action="intake",path=str(source_path),file_path=str(source_path),file_reference=str(source_path),original_request=message)
                            success=bool(raw.get("success")) if isinstance(raw,dict) else bool(getattr(raw,"success",False))
                            if success:
                                content=_document_text(source_path)
                                if content.strip():
                                    answer=_document_summary(message, content)
                                else:
                                    answer=str(raw.get("message") if isinstance(raw,dict) else getattr(raw,"message",None) or f"File input accepted: {source_path.name}")
                            else:
                                # The upload path has already passed the local workspace
                                # allowlist. If a router adapter drops explicit path
                                # fields, still provide the user a grounded local
                                # document result instead of exposing an internal
                                # capability-contract error.
                                content=_document_text(source_path)
                                if content.strip():
                                    answer=_document_summary(message, content)
                                else:
                                    answer=str((raw.get("error") or raw.get("message")) if isinstance(raw,dict) else (getattr(raw,"error",None) or getattr(raw,"message",None)) or "The attached file could not be processed.")
                        else:
                            answer="Attachment processing is unavailable because the canonical router is not initialized."
                elif research_requested:
                        research_result,research_data=_research_text_request(message)
                        research_data=getattr(research_result,"data",None) if isinstance(getattr(research_result,"data",None),dict) else {}
                        if not getattr(research_result,"success",False):
                            answer=str(getattr(research_result,"message","") or "I couldn't retrieve enough reliable current evidence from the available public-web providers right now.")
                            image_results=[]
                        else:
                            answer=format_capability_result(research_result)
                            image_results=research_data.get("image_results",[])
                elif reverse_image_requested:
                    research_result=_reverse_image_search_with_attachments(message,attachments)
                    research_data=getattr(research_result,"data",None) if isinstance(getattr(research_result,"data",None),dict) else {}
                    image_results=_dedupe_image_results(research_data.get("image_results") or research_data.get("matches") or [])
                    answer=format_capability_result(research_result) if getattr(research_result,"success",False) else str(getattr(research_result,"error",None) or getattr(research_result,"message",None) or "Free reverse-image research returned no usable public candidates.")
                elif image_search_requested:
                    global LAST_IMAGE_SUBJECT
                    LAST_IMAGE_SUBJECT = _image_search_query(message)
                    image_result = _image_search_by_text(message)
                    image_data = getattr(image_result, "data", None) if isinstance(getattr(image_result, "data", None), dict) else {}
                    raw_images = image_data.get("image_results", []) if isinstance(image_data, dict) else []
                    image_results = _dedupe_image_results(raw_images)
                    if image_results:
                        answer = f"I found public image results for {_image_search_query(message)}."
                    else:
                        answer = str(getattr(image_result, "message", "") or "I searched the public web, but the available image-search providers returned no usable image results.")
                    _record_conversation_turn("user", message)
                    _record_conversation_turn("assistant", answer)
                elif research_requested:
                    research_result,research_data=_research_text_request(message)
                    if getattr(research_result,"success",False):
                        answer=format_capability_result(research_result)
                    else:
                        answer="I couldn't retrieve enough reliable current evidence from the available public-web providers right now."
                elif FACEBOOK_FOLLOWUP_RE.search(message):
                    followup_answer = _facebook_followup_search(message)
                    if followup_answer:
                        answer = followup_answer
                        _record_conversation_turn("user", message)
                        _record_conversation_turn("assistant", answer)
                    else:
                        composed=message or "Please inspect the attached files and report the useful findings."
                        answer=_bounded_call(FREYA.system.facade.chat, 60.0, composed, context={"original_request":message})
                else:
                    composed=message or "Please inspect the attached files and report the useful findings."
                    if context: composed += "\n\n"+context
                    if context or research_requested:
                        composed += "\n\n[ROUTING INSTRUCTION] Preserve the complete user request when selecting or composing downstream capability queries. Never use only the first command verb as a search query. Use visual context only as grounded evidence."
                    answer=_bounded_call(FREYA.system.facade.chat, 60.0, composed, context={"original_request":message,"attachment_paths":attachments,"visual_context":context,"has_images":False,"research_requested":research_requested})
                emit_avatar("SPEAKING",activity="response"); self.send_payload(200,{"answer":answer,"image_results":image_results,"vision_observations":vision_meta.get("observations",{}) if isinstance(vision_meta,dict) else {},"research_queries":research_data.get("queries",[]) if isinstance(research_data,dict) else []}); emit_avatar("SUCCESS"); emit_avatar("IDLE")
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError): emit_avatar("IDLE")
            except Exception as error:
                try:
                    trace_path=self.workspace / "outputs" / "ui_server_exception_trace.log"
                    trace_path.parent.mkdir(parents=True,exist_ok=True)
                    trace_path.open("a",encoding="utf-8").write(traceback.format_exc()+"\n")
                except Exception:
                    pass
                emit_avatar("ERROR",message=str(error)); emit_avatar("IDLE")
                try: self.send_payload(504 if isinstance(error, TimeoutError) else 500,{"error":("Freya timed out before completing this request." if isinstance(error, TimeoutError) else "Freya could not complete this request. The failure was logged for diagnosis.")})
                except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError): pass
            return
        self.send_payload(404,{"error":"not found"})
    def log_message(self,_format,*_args): return

def serve(workspace,host="127.0.0.1",port=8787):
    global FREYA
    workspace=Path(workspace).resolve(); FREYA=FreyaApp(workspace,SystemConfig(enable_autonomy=False,workspace=workspace)); FREYA.start(); Handler.workspace=workspace; server=ThreadingHTTPServer((host,port),Handler)
    try: server.serve_forever()
    finally: FREYA.shutdown(); server.server_close()
if __name__=="__main__":
    parser=argparse.ArgumentParser(); parser.add_argument("--workspace",type=Path,default=Path.cwd()); parser.add_argument("--host",default="127.0.0.1"); parser.add_argument("--port",type=int,default=8787); args=parser.parse_args(); serve(args.workspace,args.host,args.port)
