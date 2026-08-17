import argparse
import json
import queue
import threading
import uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import parse_qs,urlparse
from main import FreyaApp
from app.core.initializer import SystemConfig
FREYA=None
SUBSCRIBERS=set()
LOCK=threading.Lock()
def emit_avatar(state,**metadata):
    payload={"state":state,**metadata}
    with LOCK: subscribers=list(SUBSCRIBERS)
    for subscriber in subscribers:
        try: subscriber.put_nowait(payload)
        except queue.Full: pass
def attachment_context(workspace,paths):
    if not isinstance(paths,list): return ""
    root=(workspace/"data"/"ui_uploads").resolve(); blocks=[]
    for raw in paths[:8]:
        try:
            path=Path(str(raw)).resolve()
            if root not in path.parents or not path.is_file(): continue
            blocks.append("Attached file: "+path.name+chr(10)+path.read_text(encoding="utf-8",errors="replace")[:120000])
        except (OSError,UnicodeError): pass
    return (chr(10)*2).join(blocks)
class Handler(BaseHTTPRequestHandler):
    workspace=Path.cwd()
    def send_payload(self,status,payload,content_type="application/json"):
        data=payload if isinstance(payload,bytes) else json.dumps(payload).encode("utf-8")
        self.send_response(status); self.send_header("Content-Type",content_type); self.send_header("Access-Control-Allow-Origin","*"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_OPTIONS(self):
        self.send_response(204); self.send_header("Access-Control-Allow-Origin","*"); self.send_header("Access-Control-Allow-Headers","Content-Type"); self.send_header("Access-Control-Allow-Methods","GET, POST, OPTIONS"); self.end_headers()
    def do_GET(self):
        path=urlparse(self.path).path
        if path=="/api/health": self.send_payload(200,FREYA.get_health_surface()); return
        if path=="/api/capabilities":
            registry=getattr(FREYA.system,"capability_registry",None)
            if registry is None:
                from app.orchestrator.capability_registry import get_capability_registry
                registry=get_capability_registry()
            items=registry.list_capabilities(active_only=False) if hasattr(registry,"list_capabilities") else []
            names=[{"name":getattr(item,"name",str(item)),"available":bool(getattr(item,"active",True))} for item in items]
            self.send_payload(200,{"capabilities":names}); return
        if path=="/api/avatar/events":
            subscriber=queue.Queue(maxsize=32)
            with LOCK: SUBSCRIBERS.add(subscriber)
            try:
                self.send_response(200); self.send_header("Content-Type","text/event-stream"); self.send_header("Access-Control-Allow-Origin","*"); self.send_header("Cache-Control","no-cache"); self.send_header("Connection","keep-alive"); self.end_headers()
                self.wfile.write(b'data: {"state":"IDLE"}'+bytes([10,10])); self.wfile.flush()
                while True:
                    try: payload=subscriber.get(timeout=20); data=("data: "+json.dumps(payload)).encode()+bytes([10,10])
                    except queue.Empty: data=b": keepalive"+bytes([10,10])
                    self.wfile.write(data); self.wfile.flush()
            except (BrokenPipeError,ConnectionResetError,OSError): pass
            finally:
                with LOCK: SUBSCRIBERS.discard(subscriber)
            return
        self.send_payload(404,{"error":"not found"})
    def do_POST(self):
        length=int(self.headers.get("Content-Length","0")); body=self.rfile.read(length); path=urlparse(self.path).path
        if path=="/api/chat":
            try:
                payload=json.loads(body.decode("utf-8")); message=str(payload.get("message","")).strip()
                if not message: self.send_payload(400,{"error":"message is required"}); return
                context=attachment_context(self.workspace,payload.get("attachments",[])); composed=message if not context else message+chr(10)*2+context
                emit_avatar("THINKING"); answer=FREYA.chat(composed); emit_avatar("SPEAKING"); self.send_payload(200,{"answer":answer}); emit_avatar("IDLE")
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                emit_avatar("IDLE")
                return
            except Exception as error:
                emit_avatar("ERROR", message=str(error))
                emit_avatar("IDLE")
                try:
                    self.send_payload(500, {"error": str(error)})
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
            return
        if path=="/api/upload":
            query=parse_qs(urlparse(self.path).query); filename=Path(query.get("filename",["attachment.bin"])[0]).name; folder=self.workspace/"data"/"ui_uploads"; folder.mkdir(parents=True,exist_ok=True); target=folder/(uuid.uuid4().hex+"_"+filename); target.write_bytes(body); self.send_payload(200,{"name":filename,"path":str(target)}); return
        self.send_payload(404,{"error":"not found"})
    def log_message(self,_format,*_args): return
def serve(workspace,host="127.0.0.1",port=8787):
    global FREYA
    workspace=Path(workspace).resolve(); FREYA=FreyaApp(workspace,SystemConfig(enable_autonomy=False,workspace=workspace)); FREYA.start(); Handler.workspace=workspace; server=ThreadingHTTPServer((host,port),Handler)
    try: server.serve_forever()
    finally: FREYA.shutdown(); server.server_close()
if __name__=="__main__":
    parser=argparse.ArgumentParser(); parser.add_argument("--workspace",type=Path,default=Path.cwd()); parser.add_argument("--host",default="127.0.0.1"); parser.add_argument("--port",type=int,default=8787); args=parser.parse_args(); serve(args.workspace,args.host,args.port)
