import http.server
import socketserver
import threading
import time

import pytest


class _Routes(http.server.BaseHTTPRequestHandler):
    # path -> (status, body bytes, delay seconds); set per server below.
    routes = {}

    def do_GET(self):
        status, body, delay = self.routes.get(self.path, (404, b"not found", 0))
        if delay:
            time.sleep(delay)
        try:
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError:  # the client gave up first
            pass

    def log_message(self, *args):
        pass


class LocalHTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self):
        # HTTPServer.server_bind asks socket.getfqdn() for a name, a reverse
        # lookup that takes seconds on some CI runners.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


@pytest.fixture
def http_server():
    """A real HTTP server on 127.0.0.1; ``server.route(path, body, status, delay)``
    adds a response and ``server.url(path)`` builds its URL."""
    handler = type("Handler", (_Routes,), {"routes": {}})
    server = LocalHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    server.route = lambda path, body=b"", status=200, delay=0: handler.routes.__setitem__(
        path, (status, body, delay)
    )
    server.url = lambda path: f"http://127.0.0.1:{server.server_address[1]}{path}"
    yield server
    server.shutdown()
    server.server_close()
