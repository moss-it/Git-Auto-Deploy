#!/usr/bin/env python
import json
import re
import urllib2
from BaseHTTPServer import BaseHTTPRequestHandler
from BaseHTTPServer import HTTPServer
from SocketServer import ThreadingMixIn
from urlparse import urlparse, parse_qs

from new_frontend_deploy.core.session import SessionContext
from new_frontend_deploy.revisions import get_all_revisions, activate
from new_frontend_deploy.settings import SLACK_URL

PORT = 1338
DEPLOYMENT_TOKEN = "7f2dbc5a1e9adcd8e4dc2a0e03e087c251906109"
TEMPLATE = "^manager (?P<command>.*)$"


def send_msg(msg):
    url = SLACK_URL
    data = json.dumps({"text": msg})
    req = urllib2.Request(
        url,
        data,
        {'Content-Type': 'application/json'}
    )
    urllib2.urlopen(req)


def process(token, data, *args):
    message = data['text'][0]
    mention_name = data['user_name'][0].lower()

    if token != DEPLOYMENT_TOKEN:
        return "<@{}> You have incorrect token! <@dk>".format(mention_name)

    if not re.match(TEMPLATE, message, re.DOTALL):
        return send_msg("Wrong request")

    kwargs = re.search(TEMPLATE, message, re.DOTALL).groupdict()

    command = kwargs.get('command')
    if not command:
        send_msg("<@{}> Wrong command!".format(mention_name))
        # TODO: sent help

    command = command.split(" ")
    resp = "Manager error"
    with SessionContext() as session:

        if "get" in command:
            resp = get_all_revisions(session, command[1])

        elif "activate" in command:
            resp = activate(session, command[1], command[-1])

    send_msg("<@{}> {}".format(mention_name, resp))


class MyHandler(BaseHTTPRequestHandler):
    def _response(self, response_text):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"text": response_text}))

    def do_POST(self):
        self.request = parse_qs(urlparse(self.path).query)
        token = self.request.get('token')[0]
        if token != DEPLOYMENT_TOKEN:
            self._response('Access denied')
            return

        length = int(self.headers.getheader('content-length'))
        data = parse_qs(self.rfile.read(length), keep_blank_values=1)

        response = process(token, data)
        self._response(response)
        return


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in a separate thread."""


if __name__ == '__main__':
    server = ThreadedHTTPServer(('', PORT), MyHandler)
    print 'Starting server, use <Ctrl-C> to stop'
    server.serve_forever()
