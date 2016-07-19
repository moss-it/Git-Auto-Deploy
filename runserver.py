#!/usr/bin/env python
import json
from BaseHTTPServer import BaseHTTPRequestHandler
from BaseHTTPServer import HTTPServer
from SocketServer import ThreadingMixIn

from new_frontend_deploy.core.session import SessionContext
from new_frontend_deploy.revisions import get_all_revisions, activate

PORT = 1338
FRONTEND_TOKEN = "7f2dbc5a1e9adcd8e4dc2a0e03e087c251906109"


class MyHandler(BaseHTTPRequestHandler):
    def _response(self, response_text):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"text": response_text}))

    def do_POST(self):

        length = int(self.headers.getheader('content-length'))
        data = json.loads(self.rfile.read(length))

        if data.get("token") != FRONTEND_TOKEN:
            self._response('Access denied')
            return

        if not data.get("app"):
            self._response("Error! There is no app in json!")

        with SessionContext() as session:

            if self.path == "/revisions/":
                resp = get_all_revisions(session, data)
                self._response(resp)

            elif self.path == "/activate/":
                activate(session, data)
                self._response("resp")
        return


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in a separate thread."""


if __name__ == '__main__':
    server = ThreadedHTTPServer(('', PORT), MyHandler)
    print 'Starting server, use <Ctrl-C> to stop'
    server.serve_forever()
