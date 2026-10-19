import http.server
import socketserver
import threading
import time
from pathlib import Path

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


@pytest.fixture
def dead_port():
    """A local port nothing listens on: connections to it are refused."""
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def no_proxy_env(monkeypatch):
    """No proxy variables, and no proxy marked bad by an earlier test."""
    import os

    from proxylib import clear_caches

    for name in list(os.environ):
        if name.lower().endswith("_proxy"):
            monkeypatch.delenv(name)
    clear_caches()
    yield
    clear_caches()


class _Recorder(socketserver.StreamRequestHandler):
    """Reads one request head, records (method, target, headers), then serves
    it per the server's ``respond``."""

    def handle(self):
        lines = []
        while True:
            line = self.rfile.readline(65537)
            if line in (b"\r\n", b"\n", b""):
                break
            lines.append(line.decode("latin-1").rstrip("\r\n"))
        if not lines:
            return
        method, target, _ = lines[0].split(" ", 2)
        headers = {}
        for line in lines[1:]:
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
        self.server.seen.append((method, target, headers))
        self.server.respond(self, method, target, headers)

    def reply(self, status, body=b"", extra=()):
        head = [f"HTTP/1.1 {status}", f"Content-Length: {len(body)}", "Connection: close", *extra]
        self.wfile.write(("\r\n".join(head) + "\r\n\r\n").encode("latin-1") + body)


class _RecordingServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def _serve(respond, ssl_context=None):
    server = _RecordingServer(("127.0.0.1", 0), _Recorder)
    if ssl_context is not None:
        server.socket = ssl_context.wrap_socket(server.socket, server_side=True)
    server.seen = []
    server.respond = respond
    server.port = server.server_address[1]
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    return server


def _relay(source, destination):
    try:
        while True:
            data = source.recv(65536)
            if not data:
                break
            destination.sendall(data)
    except OSError:
        pass
    finally:
        for sock in (source, destination):
            try:
                sock.shutdown(2)
            except OSError:
                pass


@pytest.fixture
def recording_proxy():
    """A forward proxy on 127.0.0.1 that records each request head it gets:
    a CONNECT is tunnelled to its target, a plain request answered 200
    ``b"via proxy"`` without being forwarded. ``proxy.seen`` lists
    ``(method, target, headers)``, header names lowercased."""
    import socket

    def respond(handler, method, target, headers):
        if method != "CONNECT":
            handler.reply("200 OK", b"via proxy")
            return
        host, _, port = target.rpartition(":")
        upstream = socket.create_connection((host, int(port)), timeout=5)
        handler.wfile.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        handler.wfile.flush()
        threading.Thread(target=_relay, args=(upstream, handler.connection), daemon=True).start()
        _relay(handler.connection, upstream)

    server = _serve(respond)
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="session")
def tls_cert(tmp_path_factory):
    """(certificate, key) paths of a throwaway self-signed certificate for
    127.0.0.1, made with the openssl command; skips without one."""
    import shutil
    import subprocess

    openssl = shutil.which("openssl")
    git = shutil.which("git")
    if openssl is None and git is not None:
        # Git for Windows ships one, off PATH outside its own shell.
        root = Path(git).resolve().parent.parent
        found = [str(p) for p in root.glob("*/bin/openssl.exe")] + [str(p) for p in root.glob("usr/bin/openssl.exe")]
        openssl = found[0] if found else None
    if openssl is None:
        pytest.skip("needs the openssl command for a test certificate")
    folder = tmp_path_factory.mktemp("tls")
    cert, key = folder / "cert.pem", folder / "key.pem"
    subprocess.run(
        [openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(cert),
         "-days", "2", "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1"],
        check=True, capture_output=True, timeout=60,
    )
    return cert, key


@pytest.fixture
def tls_server(tls_cert):
    """An HTTPS server on 127.0.0.1 answering 200 ``b"tls ok"``; ``.seen``
    records what reached it and ``.cafile`` verifies it."""
    import ssl

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(*map(str, tls_cert))
    server = _serve(lambda handler, *_: handler.reply("200 OK", b"tls ok"), context)
    server.cafile = str(tls_cert[0])
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture
def gateway():
    """A URL-prefix gateway on 127.0.0.1: answers 200 ``b"via gateway"`` with a
    ``seen=1`` cookie, or a redirect to ``/landed`` for a target ending in
    ``/redirect``; ``.seen`` records each request."""

    def respond(handler, method, target, headers):
        if target.endswith("/redirect"):
            handler.reply("302 Found", extra=("Location: /landed",))
        else:
            handler.reply("200 OK", b"via gateway", extra=("Set-Cookie: seen=1; Path=/",))

    server = _serve(respond)
    yield server
    server.shutdown()
    server.server_close()
