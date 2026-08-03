"""Run the detection harness.

The server does four things.

1. It reads the raw ClientHello before the TLS library consumes it.
2. It records the HTTP headers and their order.
3. It serves a page that collects the browser fingerprint and the telemetry.
4. It scores each session and writes the result to a log.

Run the server against your own test origin only.
"""

import argparse
import csv
import datetime
import io
import json
import os
import socket
import ssl
import struct
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import reference
import scoring
import tlsfp

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DATA_DIR = os.path.join(BASE_DIR, "data")
CERT_FILE = os.path.join(DATA_DIR, "harness-cert.pem")
KEY_FILE = os.path.join(DATA_DIR, "harness-key.pem")
LOG_FILE = os.path.join(DATA_DIR, "sessions.jsonl")

SESSIONS = {}
SESSION_ORDER = []
TLS_BY_PEER = {}
LOCK = threading.Lock()


def make_certificate():
    """Create a self-signed certificate for the local test origin."""
    if os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE):
        return
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    os.makedirs(DATA_DIR, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "botlab.local")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=825))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.DNSName("botlab.local"),
            ]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    with open(KEY_FILE, "wb") as handle:
        handle.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ))
    with open(CERT_FILE, "wb") as handle:
        handle.write(cert.public_bytes(serialization.Encoding.PEM))


def peek_client_hello(sock, timeout=2.0):
    """Read the ClientHello without consuming it. Return the fingerprint or None."""
    sock.settimeout(timeout)
    try:
        head = sock.recv(5, socket.MSG_PEEK)
        if len(head) < 5 or head[0] != 0x16:
            return None
        need = struct.unpack(">H", head[3:5])[0] + 5
        data = b""
        for _ in range(40):
            data = sock.recv(min(need, 16384), socket.MSG_PEEK)
            if len(data) >= need:
                break
        return tlsfp.fingerprint(data)
    except (OSError, tlsfp.ParseError, struct.error):
        return None
    finally:
        try:
            sock.settimeout(None)
        except OSError:
            pass


class PeekingServer(ThreadingHTTPServer):
    """An HTTPS server that fingerprints the handshake before it completes."""

    daemon_threads = True

    def __init__(self, address, handler, context):
        super().__init__(address, handler)
        self.context = context

    def get_request(self):
        raw, addr = self.socket.accept()
        if self.context is None:
            return raw, addr
        fingerprint = peek_client_hello(raw)
        if fingerprint is not None:
            with LOCK:
                TLS_BY_PEER[addr] = fingerprint
        try:
            wrapped = self.context.wrap_socket(raw, server_side=True)
        except (ssl.SSLError, OSError):
            raw.close()
            raise BlockingIOError("the TLS handshake failed")
        return wrapped, addr


def read_label(path):
    """Return the run label from the query string, if the client sent one."""
    if "?" not in path:
        return ""
    from urllib.parse import parse_qs
    return parse_qs(path.split("?", 1)[1]).get("label", [""])[0][:60]


def new_session(handler):
    """Build a session record from the connection and the request headers."""
    order = [name.lower() for name in handler.headers.keys()]
    headers = {name.lower(): value for name, value in handler.headers.items()}
    with LOCK:
        tls = TLS_BY_PEER.get(handler.client_address)
    return {
        "id": uuid.uuid4().hex[:12],
        "time": datetime.datetime.now().isoformat(timespec="seconds"),
        "ip": handler.client_address[0],
        "path": handler.path,
        "headers": headers,
        "header_order": order,
        "tls": tls,
        "js": None,
        "behavior": None,
        "extension": None,
        "source": "page",
        "label": read_label(handler.path),
    }


def store(session):
    """Save the session, score it, and append the result to the log."""
    session["result"] = scoring.evaluate(session)
    with LOCK:
        if session["id"] not in SESSIONS:
            SESSION_ORDER.append(session["id"])
        SESSIONS[session["id"]] = session
        while len(SESSION_ORDER) > 500:
            SESSIONS.pop(SESSION_ORDER.pop(0), None)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LOG_FILE, "a") as handle:
        handle.write(json.dumps(session) + "\n")
    return session["result"]


def read_static(name):
    path = os.path.join(STATIC_DIR, os.path.basename(name))
    if not os.path.exists(path):
        return None
    with open(path, "rb") as handle:
        return handle.read()


class Handler(BaseHTTPRequestHandler):
    server_version = "botlab/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.client_address[0], fmt % args))

    def _send(self, code, body, content_type="text/html; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]

        if path in ("/", "/index.html"):
            session = new_session(self)
            store(session)
            page = read_static("index.html").decode()
            page = page.replace("__SESSION_ID__", session["id"])
            return self._send(200, page)

        if path == "/dashboard":
            page = read_static("dashboard.html")
            return self._send(200, page.decode())

        if path == "/collector.js":
            body = read_static("collector.js")
            return self._send(200, body, "application/javascript; charset=utf-8")

        if path == "/api/sessions":
            with LOCK:
                rows = [SESSIONS[i] for i in reversed(SESSION_ORDER) if i in SESSIONS]
            return self._send(200, json.dumps(rows[:60]), "application/json")

        if path == "/api/probe":
            session = new_session(self)
            store(session)
            return self._send(200, json.dumps(session, indent=2), "application/json")

        if path == "/export.csv":
            return self._send(200, build_csv(), "text/csv; charset=utf-8")

        return self._send(404, "Not found. Open / for the test page.")

    def do_OPTIONS(self):
        """Answer the preflight request that the extension sends."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        if self.path.split("?")[0] != "/collect":
            return self._send(404, "Not found.")
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode() or "{}")
        except ValueError:
            return self._send(400, "The request body is not valid JSON.", "text/plain")

        session = new_session(self)
        session["js"] = payload.get("js")
        session["extension"] = payload.get("extension")
        session["source"] = payload.get("source", "page")
        session["behavior"] = payload.get("behavior")
        session["label"] = payload.get("label", "")
        session["source_page"] = payload.get("session", "")
        result = store(session)
        return self._send(200, json.dumps(result), "application/json")


CSV_COLUMNS = [
    "time", "id", "label", "ip", "score", "verdict", "first_catching_layer",
    "strongest_layer", "total_weight", "ja4", "ja3", "user_agent",
] + ["w_" + name for name in scoring.LAYERS] + [
    "detection_ids", "source", "divergences",
]


def build_csv():
    """Return every logged session as a CSV table for analysis."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    if not os.path.exists(LOG_FILE):
        return buffer.getvalue()
    with open(LOG_FILE) as handle:
        for line in handle:
            try:
                s = json.loads(line)
            except ValueError:
                continue
            result = s.get("result", {})
            layers = result.get("layers", {})
            ids = []
            for layer in scoring.LAYERS:
                ids += layers.get(layer, {}).get("ids", [])
            row = {
                "time": s.get("time", ""),
                "id": s.get("id", ""),
                "label": s.get("label", ""),
                "ip": s.get("ip", ""),
                "score": result.get("score", ""),
                "verdict": result.get("verdict", ""),
                "first_catching_layer": result.get("first_catching_layer", ""),
                "strongest_layer": result.get("strongest_layer", ""),
                "total_weight": result.get("total_weight", ""),
                "ja4": (s.get("tls") or {}).get("ja4", ""),
                "ja3": (s.get("tls") or {}).get("ja3", ""),
                "user_agent": s.get("headers", {}).get("user-agent", ""),
                "detection_ids": " ".join(ids),
                "source": s.get("source", "page"),
                "divergences": " ".join(
                    d.get("field", "") for d in ((s.get("extension") or {}).get("divergences") or [])),
            }
            for layer in scoring.LAYERS:
                row["w_" + layer] = layers.get(layer, {}).get("weight", 0)
            writer.writerow(row)
    return buffer.getvalue()


def main():
    parser = argparse.ArgumentParser(description="Run the bot detection harness.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--no-tls", action="store_true",
                        help="Serve plain HTTP. The TLS layer reports no data.")
    args = parser.parse_args()

    context = None
    if not args.no_tls:
        make_certificate()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(CERT_FILE, KEY_FILE)
        context.set_alpn_protocols(["http/1.1"])

    server = PeekingServer((args.host, args.port), Handler, context)
    scheme = "http" if args.no_tls else "https"
    print("Test page:  %s://%s:%d/" % (scheme, args.host, args.port))
    print("Dashboard:  %s://%s:%d/dashboard" % (scheme, args.host, args.port))
    print("CSV export: %s://%s:%d/export.csv" % (scheme, args.host, args.port))
    print("Stop the server with Ctrl+C.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
