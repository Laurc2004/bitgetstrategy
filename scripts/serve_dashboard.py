"""Serve the demo plus a read-only live account on loopback."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, unquote
import argparse
import json

ROOT=Path(__file__).resolve().parents[1]


def serve(account, port):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self,*args,**kw):super().__init__(*args,directory=str(ROOT),**kw)
        def do_GET(self):
            route=unquote(urlsplit(self.path).path)
            if route=='/api/live':
                path=account/'dashboard.json'
                if not path.exists():self.send_error(503,'Account is starting');return
                data=path.read_bytes()
                self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8')
                self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)))
                self.end_headers();self.wfile.write(data);return
            parts=Path(route).parts
            if any(p.startswith('.') for p in parts) or route.startswith(('/runs/','/data/raw/')):
                self.send_error(404);return
            path=(ROOT/route.lstrip('/')).resolve()
            if not path.is_relative_to(ROOT):self.send_error(404);return
            if path.is_dir() and route not in ('/',''):
                self.send_error(404);return
            super().do_GET()
        def end_headers(self):
            self.send_header('X-Content-Type-Options','nosniff')
            super().end_headers()
        def log_message(self,*args):pass
    print(f'Dashboard http://127.0.0.1:{port}/dashboard.html',flush=True)
    ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--account',required=True,type=Path);p.add_argument('--port',type=int,default=8766)
    a=p.parse_args();serve(a.account.resolve(),a.port)
