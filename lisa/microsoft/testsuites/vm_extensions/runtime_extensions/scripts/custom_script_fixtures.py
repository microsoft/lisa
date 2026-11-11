# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Loopback-only download fixtures, installed using managed Run Command."""

import json
import socket
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Dict

SCRIPT = b"#!/bin/sh\necho fixture\n"


def serve(root: Path) -> None:
    requests: Dict[str, int] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            name = self.path.split("?", 1)[0].rsplit("/", 1)[-1]
            requests[name] = requests.get(name, 0) + 1
            (root / "requests.json").write_text(json.dumps(requests))
            code = 200
            body = SCRIPT
            if name == "health":
                body = b"OK"
            elif name == "crlf.sh" or name == "extensionless":
                body = SCRIPT.replace(b"\n", b"\r\n")
            elif name == "bom.sh":
                body = b"\xef\xbb\xbf" + SCRIPT.replace(b"\n", b"\r\n")
            elif name == "binary":
                body = bytes(range(256))
            elif name == "script.py":
                body = b"print('python-fixture')\n"
            elif name == "missing.sh":
                code, body = 404, b"Not found"
            elif name in ("retry429.sh", "retry503.sh") and requests[name] == 1:
                code = 429 if name == "retry429.sh" else 503
                body = b"Retry once"
            self.send_response(code)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if name == "partial.sh" and requests[name] == 1:
                self.wfile.write(body[:5])
                self.wfile.flush()
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
            else:
                self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port_file = root / "port.tmp"
    port_file.write_text(str(server.server_port))
    port_file.replace(root / "port")
    server.serve_forever()


if __name__ == "__main__":
    serve(Path(sys.argv[1]))
