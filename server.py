from http.server import HTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlparse
import json,base64
from pathlib import Path
from engine import db,SCHEMAS,parse,ingest,matches,decision
ROOT=Path(__file__).parent
class Handler(BaseHTTPRequestHandler):
 def send(self,obj,status=200):
  body=json.dumps(obj,default=str).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
 def do_GET(self):
  if urlparse(self.path).path=='/api/dashboard':return self.send(matches())
  if self.path=='/api/schema':return self.send(SCHEMAS)
  if self.path in ['/','/index.html']:
   data=(ROOT/'index.html').read_bytes();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
  self.send({'error':'Not found'},404)
 def do_POST(self):
  try:
   n=int(self.headers.get('Content-Length','0'))
   if n>15_000_000:raise ValueError('File too large (15 MB max)')
   req=json.loads(self.rfile.read(n));route=urlparse(self.path).path
   if route=='/api/preview':
    data=base64.b64decode(req['data']);rows=parse(data,req['filename']);return self.send({'headers':list(rows[0]) if rows else [],'preview':rows[:5],'count':len(rows)})
   if route=='/api/import':return self.send(ingest(req['kind'],base64.b64decode(req['data']),req['filename'],req['mapping']))
   if route=='/api/decision':decision(req['id'],req['status'],req.get('owner',''),req.get('note',''));return self.send({'ok':True})
   self.send({'error':'Not found'},404)
  except Exception as e:self.send({'error':str(e)},400)
if __name__=='__main__':
 db().close();print('Florida Logistics Agent: http://127.0.0.1:8765',flush=True);HTTPServer(('127.0.0.1',8765),Handler).serve_forever()
