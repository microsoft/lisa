# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Release-gate tests for curl on Azure Linux.

Each case verifies one reviewed behaviour obligation directly against the node under
test.

Generated from a reviewed behaviour corpus by the Azure Linux release gate. Every
obligation below was first verified on a provisioned Azure Linux 4.0 guest on both
x86_64 and aarch64 before being re-expressed here.

Each case names the corpus obligation it discharges, so a failure upstream can be traced
back to the behaviour that was promised rather than to the test that happened to break.
"""

from __future__ import annotations

from typing import Any

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import CBLMariner, Posix
from lisa.util import SkippedException


def combined_output(result: Any) -> str:
    """Return one command result's streams merged and normalised to LF.

    A case controls the markers it prints but not which stream a tool writes a
    diagnostic to, and LISA runs every command on a pty that rewrites each newline
    as a carriage-return pair. Merging stdout and stderr removes the guess that made
    a case watch the wrong stream, and normalising the carriage returns removes the
    mismatch that made marker parsing silently fail.

    Args:
        result: The value ``node.execute`` returned.

    Returns:
        The command's stdout and stderr joined by a newline, with every CRLF and lone
        carriage return rewritten to a single LF.
    """
    merged = f"{result.stdout}\n{result.stderr}"
    return merged.replace("\r\n", "\n").replace("\r", "\n")


def section(text: str, begin: str, end: str) -> str:
    """Return the text framed by the `begin` and `end` markers.

    The end marker is located wherever it appears, so one printed as the final line --
    whose trailing newline the pty strips -- is still found rather than missed, which
    is the failure that made a hand-rolled ``split`` return the whole output as if it
    were data. An absent marker raises instead of returning everything, so a genuinely
    missing region fails loudly rather than passing. Pass an empty `begin` to take
    everything before `end`.

    Args:
        text: The combined, normalised output, from :func:`combined_output`.
        begin: The marker opening the region, or "" to start at the first character.
        end: The marker closing the region.

    Returns:
        The characters between the markers, without the markers themselves or the
        newlines adjoining them.

    Raises:
        ValueError: If either marker is absent from `text`.
    """
    start = text.find(begin)
    if start < 0:
        raise ValueError(f"begin marker {begin!r} not found in guest output")
    start += len(begin)
    stop = text.find(end, start)
    if stop < 0:
        raise ValueError(f"end marker {end!r} not found in guest output")
    return text[start:stop].strip("\n")


def section_lines(text: str, begin: str, end: str) -> list[str]:
    """Return the lines of the region framed by `begin` and `end`.

    A caller counting them sees exactly what the guest printed between the markers,
    with no spurious trailing empty entry from the newline before the end marker --
    the miscount that made a hand-rolled ``split`` assert the wrong length.

    Args:
        text: The combined, normalised output, from :func:`combined_output`.
        begin: The marker opening the region, or "" to start at the first character.
        end: The marker closing the region.

    Returns:
        The region's lines, empty when the region itself is empty.

    Raises:
        ValueError: If either marker is absent from `text`.
    """
    body = section(text, begin, end)
    return body.split("\n") if body else []


@TestSuiteMetadata(
    area="packages",
    category="functional",
    description="""
        Release-gate tests for curl on Azure Linux.

        Each case verifies one reviewed behaviour obligation directly against the node
        under test.
    """,
    requirement=simple_requirement(supported_os=[CBLMariner]),
    maturity="preview",
    tags=["ai-generated"],
)
class CurlSuite(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs["node"]
        assert isinstance(node.os, Posix)
        node.os.install_packages(
            [
                "curl",
            ]
        )

    @TestCaseMetadata(
        description="""
            Verifies that curl sends HTTP Basic credentials supplied through --user to a
            protected loopback service. The service returns a known response only when
            the Authorization header matches the configured credential.

            Corpus obligation: pkg:curl/authenticate-server-request
        """,
        priority=3,
        tags=["ai-generated"],
    )
    def verify_authenticate_server_request(self, node: Node, log: Logger) -> None:
        if node.os.information.version < "4.0.0":
            raise SkippedException(
                "this case is derived from an Azure Linux 4.0 corpus and was verified"
                " only on Azure Linux 4.0.0 guests; this node reports "
                f"{node.os.information.version}"
            )

        credential = "curl-auth-user:curl-auth-secret"
        request_path = "/protected"
        response_body = "authenticated-response-from-curl"
        auth_marker = "AUTHORIZATION_MATCHED"
        helper = rf"""
import base64
import socket
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

mode = sys.argv[1]
if mode == "probe":
    port = int(sys.argv[2])
    conn = socket.create_connection(("127.0.0.1", port), timeout=2)
    conn.sendall(b"GET /ready HTTP/1.0\r\nHost: localhost\r\n\r\n")
    data = b""
    while True:
        chunk = conn.recv(4096)
        if not chunk:
            break
        data += chunk
    conn.close()
    if not data.startswith(b"HTTP/"):
        sys.exit(1)
    sys.exit(0)

tmp = Path(sys.argv[2])
credential = "{credential}"
protected_path = "{request_path}"
response = b"{response_body}"
auth_marker = "{auth_marker}"
expected = "Basic " + base64.b64encode(credential.encode()).decode()

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, message, *args):
        return

    def do_GET(self):
        supplied = self.headers.get("Authorization", "")
        if self.path == protected_path and supplied == expected:
            (tmp / "auth").write_text(auth_marker + "\n")
            self.send_response(200)
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)
            return
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="curl-test"')
        self.send_header("Content-Length", "0")
        self.end_headers()

server = HTTPServer(("127.0.0.1", 0), Handler)
(tmp / "port").write_text(str(server.server_port) + "\n")
server.serve_forever()
"""
        command = rf"""
set -u
tmp=$(mktemp -d /tmp/curl-auth-test.XXXXXX)
server_pid=
cleanup() {{
    if [ -n "$server_pid" ]; then
        kill "$server_pid" 2>/dev/null || true
        wait "$server_pid" 2>/dev/null || true
    fi
    rm -rf "$tmp"
}}
trap cleanup EXIT
status=READY
curl_rc=MISSING
body=MISSING
auth=MISSING
credential='{credential}'
request_path='{request_path}'
response_body='{response_body}'
: >"$tmp/server.log"
: >"$tmp/curl.err"
cat <<'PY' >"$tmp/server.py"
{helper}
PY
if ! test -s "$tmp/server.py"; then
    status=FIXTURE_NOT_READY
elif ! python3 -m py_compile "$tmp/server.py" \
    >"$tmp/server.log" 2>&1; then
    status=FIXTURE_NOT_READY
else
    python3 "$tmp/server.py" serve "$tmp" \
        "$credential" "$request_path" "$response_body" \
        >"$tmp/server.out" 2>>"$tmp/server.log" &
    server_pid=$!
    i=0
    while [ "$i" -lt 50 ] && [ ! -s "$tmp/port" ]; do
        sleep 0.1
        i=$((i + 1))
    done
    if [ ! -s "$tmp/port" ]; then
        status=FIXTURE_NOT_READY
    else
        port=$(cat "$tmp/port")
        if ! python3 "$tmp/server.py" probe "$port" \
            >>"$tmp/server.log" 2>&1; then
            status=FIXTURE_NOT_READY
        else
            url="http://127.0.0.1:$port$request_path"
            curl --silent --show-error --user "$credential" \
                --output "$tmp/body" "$url" 2>"$tmp/curl.err"
            curl_rc=$?
            if [ -f "$tmp/body" ]; then
                body=$(cat "$tmp/body")
            fi
            if [ -f "$tmp/auth" ]; then
                auth=$(cat "$tmp/auth")
            fi
        fi
    fi
fi
if [ -n "$server_pid" ]; then
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
    server_pid=
fi
echo STATUS_BEGIN
echo "$status"
echo STATUS_END
echo CURL_RC_BEGIN
echo "$curl_rc"
echo CURL_RC_END
echo BODY_BEGIN
echo "$body"
echo BODY_END
echo AUTH_BEGIN
echo "$auth"
echo AUTH_END
echo CURL_DIAG_BEGIN
tail -n 20 "$tmp/curl.err" 2>/dev/null || true
echo CURL_DIAG_END
echo SERVER_LOG_BEGIN
tail -n 20 "$tmp/server.log" 2>/dev/null || true
echo SERVER_LOG_END
"""
        result = node.execute(command, shell=True)
        assert_that(result.exit_code).described_as(
            f"guest auth test exited with {result.exit_code}"
        ).is_equal_to(0)
        text = combined_output(result)
        status = section(text, "STATUS_BEGIN", "STATUS_END").strip()
        if status == "FIXTURE_NOT_READY":
            details = section(text, "SERVER_LOG_BEGIN", "SERVER_LOG_END")
            raise SkippedException(
                f"loopback authentication fixture was not ready: {details}"
            )
        assert_that(status).described_as(
            f"fixture status was {status!r}, expected 'READY'"
        ).is_equal_to("READY")
        curl_rc = section(text, "CURL_RC_BEGIN", "CURL_RC_END").strip()
        assert_that(curl_rc).described_as(
            f"curl exit code was {curl_rc!r}, expected '0'"
        ).is_equal_to("0")
        auth = section(text, "AUTH_BEGIN", "AUTH_END").strip()
        assert_that(auth).described_as(
            f"server auth evidence was {auth!r}, expected {auth_marker!r}"
        ).is_equal_to(auth_marker)
        body = section(text, "BODY_BEGIN", "BODY_END").strip()
        assert_that(body).described_as(
            f"authenticated body was {body!r}, expected {response_body!r}"
        ).is_equal_to(response_body)

    @TestCaseMetadata(
        description="""
            Verifies that curl downloads a loopback HTTP response to the path supplied
            with --output. It confirms the named file contains the exact response body
            and that curl writes no response-body bytes to standard output.

            Corpus obligation: pkg:curl/download-to-named-file
        """,
        priority=3,
        tags=["ai-generated"],
    )
    def verify_download_to_named_file(self, node: Node, log: Logger) -> None:
        if node.os.information.version < "4.0.0":
            raise SkippedException(
                "this case is derived from an Azure Linux 4.0 corpus and was verified"
                " only on Azure Linux 4.0.0 guests; this node reports "
                f"{node.os.information.version}"
            )

        payload = "curl-named-output-payload-7c41b9"
        helper = rf"""
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen

BODY = {payload!r}


class Handler(BaseHTTPRequestHandler):
    def _reply(self, status, data):
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/ready":
            self._reply(200, b"ready")
        elif self.path == "/response":
            self._reply(200, BODY.encode("utf-8"))
        else:
            self._reply(404, b"missing")

    def log_message(self, message, *args):
        return


if sys.argv[1] == "probe":
    try:
        with urlopen(sys.argv[2], timeout=1) as response:
            response.read()
    except HTTPError:
        pass
    except Exception:
        sys.exit(1)
    sys.exit(0)

server = HTTPServer(("127.0.0.1", 0), Handler)
with open(sys.argv[1], "w", encoding="utf-8") as port_file:
    port_file.write(str(server.server_port) + "\n")
server.serve_forever()
"""
        command = rf"""
tmp=$(mktemp -d /tmp/curl-named-output.XXXXXX)
server_pid=
trap 'if [ -n "$server_pid" ]; then kill "$server_pid" 2>/dev/null || true;
wait "$server_pid" 2>/dev/null || true; fi; rm -rf "$tmp"' EXIT
cat <<'PY' > "$tmp/server.py"
{helper}
PY
fixture=HELPER_INVALID
curl_rc=NOT_RUN
stdout_size=NOT_RUN
dest_state=NOT_RUN
if test -s "$tmp/server.py" && \
    python3 -m py_compile "$tmp/server.py"; then
    fixture=FIXTURE_NOT_READY
    python3 "$tmp/server.py" "$tmp/port" \
        >"$tmp/server.out" 2>"$tmp/server.err" &
    server_pid=$!
    count=0
    while [ "$count" -lt 30 ]; do
        if [ -s "$tmp/port" ]; then
            port=$(cat "$tmp/port")
            if python3 "$tmp/server.py" probe \
                "http://127.0.0.1:$port/ready"; then
                fixture=READY
                break
            fi
        fi
        sleep 0.1
        count=$((count + 1))
    done
fi
if [ "$fixture" = READY ]; then
    if curl --silent --show-error --noproxy '*' \
        --output "$tmp/named.bin" \
        "http://127.0.0.1:$port/response" \
        >"$tmp/curl.stdout" 2>"$tmp/curl.stderr"; then
        curl_rc=0
    else
        curl_rc=$?
    fi
    if [ -f "$tmp/curl.stdout" ]; then
        stdout_size=$(wc -c < "$tmp/curl.stdout")
    else
        stdout_size=MISSING
    fi
    if [ -f "$tmp/named.bin" ]; then
        dest_state=PRESENT
    else
        dest_state=MISSING
    fi
fi
if [ -n "$server_pid" ]; then
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
    server_pid=
fi
printf 'FIXTURE_BEGIN\n%s\nFIXTURE_END\n' "$fixture"
printf 'CURL_RC_BEGIN\n%s\nCURL_RC_END\n' "$curl_rc"
printf 'STDOUT_SIZE_BEGIN\n%s\nSTDOUT_SIZE_END\n' "$stdout_size"
printf 'DEST_STATE_BEGIN\n%s\nDEST_STATE_END\n' "$dest_state"
printf 'DEST_BODY_BEGIN\n'
if [ -f "$tmp/named.bin" ]; then
    cat "$tmp/named.bin"
else
    printf 'MISSING'
fi
printf '\nDEST_BODY_END\n'
printf 'DIAGNOSTICS_BEGIN\n'
if [ -f "$tmp/curl.stderr" ]; then
    tail -n 40 "$tmp/curl.stderr"
fi
if [ -f "$tmp/server.err" ]; then
    tail -n 40 "$tmp/server.err"
fi
printf 'DIAGNOSTICS_END\n'
"""
        result = node.execute(command, shell=True)
        text = combined_output(result)
        assert_that(result.exit_code).described_as(
            f"guest probe must complete; observed rc={result.exit_code}, output={text}"
        ).is_equal_to(0)
        fixture = section(text, "FIXTURE_BEGIN", "FIXTURE_END").strip()
        if fixture != "READY":
            raise SkippedException(
                f"loopback fixture was not ready; observed {fixture!r}; output={text}"
            )
        curl_rc = section(text, "CURL_RC_BEGIN", "CURL_RC_END").strip()
        stdout_size = section(text, "STDOUT_SIZE_BEGIN", "STDOUT_SIZE_END").strip()
        dest_state = section(text, "DEST_STATE_BEGIN", "DEST_STATE_END").strip()
        dest_body = section(text, "DEST_BODY_BEGIN", "DEST_BODY_END").strip()
        assert_that(curl_rc).described_as(
            f"curl --output must succeed; observed rc={curl_rc!r}; output={text}"
        ).is_equal_to("0")
        assert_that(dest_state).described_as(
            f"the named destination must exist; observed {dest_state!r}"
        ).is_equal_to("PRESENT")
        assert_that(dest_body).described_as(
            f"destination body was {dest_body!r}, expected {payload!r}"
        ).is_equal_to(payload)
        assert_that(stdout_size).described_as(
            f"curl stdout byte count was {stdout_size!r}, expected '0'"
        ).is_equal_to("0")

    @TestCaseMetadata(
        description="""
            Verifies that curl treats an HTTP 404 response as an error when invoked with
            --fail. It asserts that curl exits with code 22 and does not emit the
            server's response body.

            Corpus obligation: pkg:curl/fail-on-http-error
        """,
        priority=3,
        tags=["ai-generated"],
    )
    def verify_fail_on_http_error(self, node: Node, log: Logger) -> None:
        if node.os.information.version < "4.0.0":
            raise SkippedException(
                "this case is derived from an Azure Linux 4.0 corpus and was verified"
                " only on Azure Linux 4.0.0 guests; this node reports "
                f"{node.os.information.version}"
            )

        response_body = "body-that-must-not-be-emitted"
        ready_marker = "READY"
        not_ready_marker = "FIXTURE_NOT_READY"
        fixture_begin = "FIXTURE_BEGIN"
        fixture_end = "FIXTURE_END"
        rc_begin = "CURL_RC_BEGIN"
        rc_end = "CURL_RC_END"
        bytes_begin = "BODY_BYTES_BEGIN"
        bytes_end = "BODY_BYTES_END"
        curl_diag_begin = "CURL_DIAG_BEGIN"
        curl_diag_end = "CURL_DIAG_END"
        server_diag_begin = "SERVER_DIAG_BEGIN"
        server_diag_end = "SERVER_DIAG_END"
        server_code = rf"""
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, message, *args):
        return

    def do_GET(self):
        if self.path == "/ready":
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        payload = {response_body!r}.encode("utf-8")
        self.send_response(404)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def probe(port):
    connection = socket.create_connection(("127.0.0.1", port), 2)
    connection.sendall(
        b"GET /ready HTTP/1.0\r\nHost: localhost\r\n\r\n"
    )
    answer = connection.recv(64)
    connection.close()
    return answer.startswith(b"HTTP/")


if sys.argv[1] == "probe":
    sys.exit(0 if probe(int(sys.argv[2])) else 1)

port_file = sys.argv[1]
server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
with open(port_file, "w", encoding="utf-8") as stream:
    stream.write(str(server.server_port) + "\n")
server.serve_forever()
"""
        script = rf"""
tmp=$(mktemp -d /tmp/curl-fail-http.XXXXXX)
pid=""
trap 'if [ -n "$pid" ]; then kill "$pid" 2>/dev/null; fi;
wait "$pid" 2>/dev/null; rm -rf "$tmp"' EXIT
cat <<'PY' > "$tmp/server.py"
{server_code}
PY
fixture={not_ready_marker}
reason=helper-not-materialized
curl_rc=MISSING
body_bytes=MISSING
if [ -s "$tmp/server.py" ]; then
    if python3 -m py_compile "$tmp/server.py" 2>"$tmp/server.log"; then
        python3 "$tmp/server.py" "$tmp/port" \
            >>"$tmp/server.log" 2>&1 &
        pid=$!
        tries=0
        while [ "$tries" -lt 50 ]; do
            if [ -s "$tmp/port" ]; then
                break
            fi
            if ! kill -0 "$pid" 2>/dev/null; then
                break
            fi
            sleep 0.1
            tries=$((tries + 1))
        done
        if [ -s "$tmp/port" ]; then
            port=$(cat "$tmp/port")
            if python3 "$tmp/server.py" probe "$port" \
                >>"$tmp/server.log" 2>&1; then
                fixture={ready_marker}
                reason=none
                curl --fail --silent --show-error \
                    "http://127.0.0.1:$port/error" \
                    >"$tmp/body" 2>"$tmp/curl.err"
                curl_rc=$?
                body_bytes=$(wc -c < "$tmp/body" 2>/dev/null || echo MISSING)
            else
                reason=readiness-probe-failed
            fi
        else
            reason=port-not-published
        fi
    else
        reason=helper-did-not-compile
    fi
fi
if [ -n "$pid" ]; then
    kill "$pid" 2>/dev/null
    wait "$pid" 2>/dev/null
    pid=""
fi
printf '%s\n%s\n%s\n' '{fixture_begin}' "$fixture" '{fixture_end}'
printf '%s\n%s\n%s\n' '{rc_begin}' "$curl_rc" '{rc_end}'
printf '%s\n%s\n%s\n' \
    '{bytes_begin}' "$body_bytes" '{bytes_end}'
printf '%s\n' '{curl_diag_begin}'
cat "$tmp/curl.err" 2>/dev/null || true
printf '%s\n' '{curl_diag_end}'
printf '%s\n' '{server_diag_begin}'
printf 'reason=%s\n' "$reason"
cat "$tmp/server.log" 2>/dev/null || true
printf '%s\n' '{server_diag_end}'
"""
        result = node.execute(script, shell=True)
        text = combined_output(result)
        fixture = section(text, fixture_begin, fixture_end).strip()
        curl_rc = section(text, rc_begin, rc_end).strip()
        body_bytes = section(text, bytes_begin, bytes_end).strip()
        curl_diag = section(text, curl_diag_begin, curl_diag_end)
        server_diag = section(text, server_diag_begin, server_diag_end)
        if fixture == not_ready_marker:
            raise SkippedException(
                f"loopback HTTP fixture was not ready: {server_diag!r}"
            )
        assert_that(result.exit_code).described_as(
            f"guest script exit code was {result.exit_code}; output: {text!r}"
        ).is_equal_to(0)
        assert_that(fixture).described_as(
            f"fixture state was {fixture!r}; diagnostics: {server_diag!r}"
        ).is_equal_to(ready_marker)
        assert_that(curl_rc).described_as(
            f"curl exit code was {curl_rc!r}; diagnostics: {curl_diag!r}"
        ).is_equal_to("22")
        assert_that(body_bytes).described_as(
            f"curl emitted {body_bytes!r} response-body bytes; expected zero"
        ).is_equal_to("0")

    @TestCaseMetadata(
        description="""
            Verifies that curl follows an HTTP redirect when invoked with --location. A
            loopback server records both requests and returns a unique body from the
            final resource.

            Corpus obligation: pkg:curl/follow-http-redirect
        """,
        priority=3,
        tags=["ai-generated"],
    )
    def verify_follow_http_redirect(self, node: Node, log: Logger) -> None:
        if node.os.information.version < "4.0.0":
            raise SkippedException(
                "this case is derived from an Azure Linux 4.0 corpus and was verified"
                " only on Azure Linux 4.0.0 guests; this node reports "
                f"{node.os.information.version}"
            )

        start_path = "/redirect"
        final_path = "/final"
        response_body = "curl-followed-redirect"
        server = rf"""
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

port_file = sys.argv[1]
request_log = sys.argv[2]

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _record(self):
        with open(request_log, "a", encoding="utf-8") as stream:
            stream.write(self.path + "\n")

    def do_GET(self):
        self._record()
        if self.path == "{start_path}":
            self.send_response(302)
            self.send_header("Location", "{final_path}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "{final_path}":
            body = b"{response_body}"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, pattern, *args):
        return

httpd = HTTPServer(("127.0.0.1", 0), Handler)
with open(port_file, "w", encoding="utf-8") as stream:
    stream.write(str(httpd.server_port) + "\n")
httpd.serve_forever()
"""
        command = rf"""
tmp=$(mktemp -d)
server_pid=
cleanup() {{
    if [ -n "$server_pid" ]; then
        kill "$server_pid" 2>/dev/null
        wait "$server_pid" 2>/dev/null
    fi
    rm -rf "$tmp"
}}
trap cleanup EXIT

cat <<'PY' > "$tmp/server.py"
{server}
PY

if [ ! -s "$tmp/server.py" ]; then
    echo FIXTURE_NOT_READY
    exit 0
fi
if ! python3 -m py_compile "$tmp/server.py" 2>"$tmp/server.log"; then
    echo SERVER_LOG_BEGIN
    cat "$tmp/server.log"
    echo SERVER_LOG_END
    echo FIXTURE_NOT_READY
    exit 0
fi

python3 "$tmp/server.py" "$tmp/port" "$tmp/requests" \
    >"$tmp/server.out" 2>>"$tmp/server.log" &
server_pid=$!
ready=0
attempt=0
while [ "$attempt" -lt 50 ]; do
    if [ -s "$tmp/port" ]; then
        port=$(cat "$tmp/port")
        if python3 -c \
            'import socket,sys;s=socket.create_connection'\
            '(("127.0.0.1",int(sys.argv[1])),1);s.close()' \
            "$port"; then
            ready=1
            break
        fi
    fi
    attempt=$((attempt + 1))
    sleep 0.1
done

if [ "$ready" -ne 1 ]; then
    echo SERVER_LOG_BEGIN
    cat "$tmp/server.log" 2>/dev/null
    echo SERVER_LOG_END
    echo FIXTURE_NOT_READY
    exit 0
fi

echo CURL_VERSION_BEGIN
curl -V
echo CURL_VERSION_END
http_code=$(curl -sS --location \
    --output "$tmp/body" \
    --write-out '%{{http_code}}' \
    "http://127.0.0.1:$port{start_path}" 2>"$tmp/curl.err")
curl_rc=$?

kill "$server_pid" 2>/dev/null
wait "$server_pid" 2>/dev/null
server_pid=

echo CURL_RC_BEGIN
echo "$curl_rc"
echo CURL_RC_END
echo HTTP_CODE_BEGIN
echo "$http_code"
echo HTTP_CODE_END
echo BODY_BEGIN
if [ -f "$tmp/body" ]; then
    cat "$tmp/body"
    echo
else
    echo MISSING
fi
echo BODY_END
echo REQUESTS_BEGIN
if [ -f "$tmp/requests" ]; then
    cat "$tmp/requests"
else
    echo MISSING
fi
echo REQUESTS_END
echo CURL_ERROR_BEGIN
cat "$tmp/curl.err" 2>/dev/null
echo CURL_ERROR_END
echo SERVER_LOG_BEGIN
cat "$tmp/server.log" 2>/dev/null
echo SERVER_LOG_END
"""
        result = node.execute(command, shell=True)
        text = combined_output(result)
        if "FIXTURE_NOT_READY" in text:
            raise SkippedException("loopback redirect fixture was not ready")
        assert_that(result.exit_code).described_as(
            f"fixture script exit code; observed output: {text}"
        ).is_equal_to(0)
        curl_rc = section(text, "CURL_RC_BEGIN", "CURL_RC_END").strip()
        assert_that(curl_rc).described_as(
            f"curl exit code; observed {curl_rc}, expected 0"
        ).is_equal_to("0")
        http_code = section(text, "HTTP_CODE_BEGIN", "HTTP_CODE_END").strip()
        assert_that(http_code).described_as(
            f"final HTTP status; observed {http_code}, expected 200"
        ).is_equal_to("200")
        body = section(text, "BODY_BEGIN", "BODY_END").strip()
        assert_that(body).described_as(
            f"final response body; observed {body}, expected {response_body}"
        ).is_equal_to(response_body)
        requests = section_lines(text, "REQUESTS_BEGIN", "REQUESTS_END")
        assert_that(requests).described_as(
            f"requested paths; observed {requests}"
        ).is_equal_to([start_path, final_path])

    @TestCaseMetadata(
        description="""
            Verifies that curl honors an explicit --proxy value for an HTTP origin URL.
            A loopback proxy records and forwards the absolute request URL to a loopback
            origin, and the case checks both proxy receipt and curl's returned origin
            body.

            Corpus obligation: pkg:curl/request-through-proxy
        """,
        priority=3,
        tags=["ai-generated"],
    )
    def verify_request_through_proxy(self, node: Node, log: Logger) -> None:
        if node.os.information.version < "4.0.0":
            raise SkippedException(
                "this case is derived from an Azure Linux 4.0 corpus and was verified"
                " only on Azure Linux 4.0.0 guests; this node reports "
                f"{node.os.information.version}"
            )

        expected_body = "origin-response-through-explicit-proxy"
        request_path = "/through-proxy"
        ready_marker = "FIXTURE_READY=1"
        not_ready_marker = "FIXTURE_NOT_READY=1"
        proxy_seen_marker = "PROXY_SEEN=1"
        helper = rf"""
import http.client
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, urlunsplit

request_path = {request_path!r}
expected_body = {expected_body!r}.encode()


class OriginHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != request_path:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(expected_body)))
        self.end_headers()
        self.wfile.write(expected_body)

    def log_message(self, message, *args):
        return


class ProxyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.seen.append(self.path)
        parsed = urlsplit(self.path)
        target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        connection = http.client.HTTPConnection(
            parsed.hostname,
            parsed.port or 80,
            timeout=5,
        )
        try:
            connection.request("GET", target)
            response = connection.getresponse()
            body = response.read()
            self.send_response(response.status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        finally:
            connection.close()

    def log_message(self, message, *args):
        return


def reachable(port):
    for attempt in range(30):
        try:
            connection = socket.create_connection(("127.0.0.1", port), 1)
            connection.close()
            return True
        except OSError:
            time.sleep(0.05)
    return False


def region(name, value):
    print(f"{{name}}_BEGIN")
    if value:
        print(value, end="")
        if not value.endswith("\n"):
            print()
    print(f"{{name}}_END")


origin = ThreadingHTTPServer(("127.0.0.1", 0), OriginHandler)
proxy = ThreadingHTTPServer(("127.0.0.1", 0), ProxyHandler)
proxy.seen = []
origin_thread = threading.Thread(target=origin.serve_forever, daemon=True)
proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
origin_thread.start()
proxy_thread.start()
origin_url = f"http://127.0.0.1:{{origin.server_port}}{{request_path}}"
proxy_url = f"http://127.0.0.1:{{proxy.server_port}}"
fixture_ready = reachable(origin.server_port) and reachable(proxy.server_port)
curl_rc = "NOT_RUN"
curl_body = ""
curl_stderr = ""
try:
    if fixture_ready:
        completed = subprocess.run(
            [
                "curl",
                "--silent",
                "--show-error",
                "--max-time",
                "10",
                "--noproxy",
                "",
                "--proxy",
                proxy_url,
                origin_url,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        curl_rc = str(completed.returncode)
        curl_body = completed.stdout
        curl_stderr = completed.stderr
finally:
    origin.shutdown()
    proxy.shutdown()
    origin.server_close()
    proxy.server_close()
    origin_thread.join(timeout=2)
    proxy_thread.join(timeout=2)

seen_target = proxy.seen[-1] if proxy.seen else ""
print("STATUS_BEGIN")
print({ready_marker!r} if fixture_ready else {not_ready_marker!r})
print(f"CURL_RC={{curl_rc}}")
print({proxy_seen_marker!r} if seen_target == origin_url else "PROXY_SEEN=0")
print("STATUS_END")
region("BODY", curl_body)
region("PROXY_TARGET", seen_target)
region("CURL_DIAGNOSTIC", curl_stderr)
"""
        result = node.execute(
            f"""tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cat <<'PY' > "$tmp/proxy_case.py"
{helper}
PY
if ! test -s "$tmp/proxy_case.py"; then
    echo 'HELPER_BEGIN'
    echo 'helper was empty'
    echo 'HELPER_END'
    exit 1
fi
python3 -m py_compile "$tmp/proxy_case.py" || exit 1
python3 "$tmp/proxy_case.py"
""",
            shell=True,
        )
        text = combined_output(result)
        assert_that(result.exit_code).described_as(
            f"proxy exercise must complete; observed output: {text}"
        ).is_equal_to(0)
        if not_ready_marker in text:
            raise SkippedException(
                "the loopback origin or proxy fixture did not become reachable"
            )
        status_lines = section_lines(text, "STATUS_BEGIN", "STATUS_END")
        assert_that(status_lines).described_as(
            f"fixture readiness status was: {status_lines}"
        ).contains(ready_marker)
        assert_that(status_lines).described_as(
            f"curl status through the explicit proxy was: {status_lines}"
        ).contains("CURL_RC=0")
        assert_that(status_lines).described_as(
            f"proxy receipt status was: {status_lines}"
        ).contains(proxy_seen_marker)
        proxy_target = section(
            text,
            "PROXY_TARGET_BEGIN",
            "PROXY_TARGET_END",
        )
        assert_that(proxy_target).described_as(
            f"proxy received target: {proxy_target}"
        ).starts_with("http://127.0.0.1:")
        assert_that(proxy_target).described_as(
            f"proxy received target: {proxy_target}"
        ).ends_with(request_path)
        curl_body = section(text, "BODY_BEGIN", "BODY_END")
        assert_that(curl_body).described_as(
            f"curl returned body {curl_body!r}, expected {expected_body!r}"
        ).is_equal_to(expected_body)

    @TestCaseMetadata(
        description="""
            Verifies that curl resumes an existing partial download with --continue-at
            -. A loopback HTTP server records the Range header, and the completed
            destination is compared byte-for-byte with the known content.

            Corpus obligation: pkg:curl/resume-partial-download
        """,
        priority=3,
        tags=["ai-generated"],
    )
    def verify_resume_partial_download(self, node: Node, log: Logger) -> None:
        if node.os.information.version < "4.0.0":
            raise SkippedException(
                "this case is derived from an Azure Linux 4.0 corpus and was verified"
                " only on Azure Linux 4.0.0 guests; this node reports "
                f"{node.os.information.version}"
            )

        content = "resume-check-0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ-end"
        prefix = content[:19]
        helper = rf"""
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

body = {content!r}.encode("ascii")
port_path = sys.argv[1]
log_path = sys.argv[2]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        value = self.headers.get("Range", "NONE")
        with open(log_path, "a", encoding="utf-8") as stream:
            stream.write(value + "\n")
        start = 0
        status = 200
        if value.startswith("bytes=") and value.endswith("-"):
            try:
                start = int(value[6:-1])
            except ValueError:
                start = 0
            if 0 <= start < len(body):
                status = 206
        payload = body[start:] if status == 206 else body
        self.send_response(status)
        self.send_header("Content-Length", str(len(payload)))
        if status == 206:
            end = len(body) - 1
            total = len(body)
            self.send_header(
                "Content-Range", f"bytes {{start}}-{{end}}/{{total}}"
            )
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, pattern, *args):
        return


server = HTTPServer(("127.0.0.1", 0), Handler)
with open(port_path, "w", encoding="utf-8") as stream:
    stream.write(str(server.server_port) + "\n")
server.serve_forever()
"""
        command = rf"""
tmp=$(mktemp -d)
pid=""
trap '[ -z "$pid" ] || kill "$pid" 2>/dev/null; rm -rf "$tmp"' EXIT
helper_nonempty=no
compiled=no
ready=no
curl_rc=NOT_RUN
match=no
initial_size=MISSING
final_size=MISSING
range_value=MISSING
cat <<'PY' > "$tmp/server.py"
{helper}
PY
if test -s "$tmp/server.py"; then
    helper_nonempty=yes
fi
if test "$helper_nonempty" = yes && \
        python3 -m py_compile "$tmp/server.py"; then
    compiled=yes
    python3 "$tmp/server.py" "$tmp/port" "$tmp/ranges" \
        >"$tmp/server.out" 2>"$tmp/server.err" </dev/null &
    pid=$!
    count=0
    while test ! -s "$tmp/port" && test "$count" -lt 50; do
        sleep 0.1
        count=$((count + 1))
    done
    if test -s "$tmp/port"; then
        port=$(cat "$tmp/port")
        if python3 -c 'import socket,sys
socket.create_connection(("127.0.0.1",int(sys.argv[1])),2).close()' \
                "$port"; then
            ready=yes
        fi
    fi
fi
if test "$ready" = yes; then
    printf '%s' '{prefix}' > "$tmp/destination"
    printf '%s' '{content}' > "$tmp/expected"
    initial_size=$(wc -c < "$tmp/destination" 2>/dev/null || echo MISSING)
    curl --silent --show-error --continue-at - \
        --output "$tmp/destination" \
        "http://127.0.0.1:$port/content"
    curl_rc=$?
    if cmp -s "$tmp/destination" "$tmp/expected"; then
        match=yes
    fi
    final_size=$(wc -c < "$tmp/destination" 2>/dev/null || echo MISSING)
    range_value=$(
        if test -s "$tmp/ranges"; then
            cat "$tmp/ranges"
        else
            printf '%s' MISSING
        fi
    )
fi
if test -n "$pid"; then
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
    pid=""
fi
printf '%s\n' FIXTURE_BEGIN
printf '%s\n' "HELPER_NONEMPTY=$helper_nonempty"
printf '%s\n' "COMPILED=$compiled"
printf '%s\n' "READY=$ready"
printf '%s\n' FIXTURE_END
printf '%s\n' CURL_BEGIN
printf '%s\n' "RC=$curl_rc"
printf '%s\n' "INITIAL_SIZE=$initial_size"
printf '%s\n' "FINAL_SIZE=$final_size"
printf '%s\n' "MATCH=$match"
printf '%s\n' CURL_END
printf '%s\n' RANGE_BEGIN
printf '%s\n' "$range_value"
printf '%s\n' RANGE_END
printf '%s\n' SERVER_DIAGNOSTICS_BEGIN
if test -s "$tmp/server.err"; then
    tail -n 20 "$tmp/server.err"
fi
printf '%s\n' SERVER_DIAGNOSTICS_END
"""
        result = node.execute(command, shell=True)
        text = combined_output(result)
        fixture = section_lines(text, "FIXTURE_BEGIN", "FIXTURE_END")
        if "READY=no" in fixture:
            raise SkippedException(f"loopback fixture was not ready: {fixture!r}")
        assert_that(fixture).described_as(
            f"fixture preparation facts were {fixture!r}"
        ).contains("HELPER_NONEMPTY=yes", "COMPILED=yes", "READY=yes")
        curl_facts = section_lines(text, "CURL_BEGIN", "CURL_END")
        assert_that(curl_facts).described_as(
            f"curl execution facts were {curl_facts!r}"
        ).contains("RC=0")
        assert_that(curl_facts).described_as(
            f"partial destination facts were {curl_facts!r}"
        ).contains(f"INITIAL_SIZE={len(prefix)}")
        range_facts = section_lines(text, "RANGE_BEGIN", "RANGE_END")
        assert_that(range_facts).described_as(
            f"server observed Range values {range_facts!r}"
        ).contains(f"bytes={len(prefix)}-")
        assert_that(curl_facts).described_as(
            f"completed destination facts were {curl_facts!r}"
        ).contains(f"FINAL_SIZE={len(content)}")
        assert_that(curl_facts).described_as(
            f"destination comparison facts were {curl_facts!r}"
        ).contains("MATCH=yes")

    @TestCaseMetadata(
        description="""
            Verifies that curl --head sends a HEAD request to a healthy loopback HTTP
            service. It confirms that curl displays a controlled response header while
            omitting the response body.

            Corpus obligation: pkg:curl/retrieve-response-headers
        """,
        priority=3,
        tags=["ai-generated"],
    )
    def verify_retrieve_response_headers(self, node: Node, log: Logger) -> None:
        if node.os.information.version < "4.0.0":
            raise SkippedException(
                "this case is derived from an Azure Linux 4.0 corpus and was verified"
                " only on Azure Linux 4.0.0 guests; this node reports "
                f"{node.os.information.version}"
            )

        body_marker = "CURL_HEAD_RESPONSE_BODY_7E21"
        header_marker = "curl-head-header-4f92"
        request_path = "/head-check"
        server_script = rf"""
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

root = Path(sys.argv[1])
body = {body_marker!r}.encode()

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _reply(self, include_body):
        method = self.command + " " + self.path + "\n"
        (root / "method").write_text(method)
        self.send_response(200)
        self.send_header("X-Curl-Probe", {header_marker!r})
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def do_HEAD(self):
        self._reply(False)

    def do_GET(self):
        self._reply(True)

    def log_message(self, message, *args):
        pass

server = HTTPServer(("127.0.0.1", 0), Handler)
(root / "port").write_text(str(server.server_port) + "\n")
server.serve_forever()
"""
        command = rf"""tmp=$(mktemp -d /tmp/curl-head.XXXXXX)
pid=
cleanup() {{
    if [ -n "$pid" ]; then
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    fi
    rm -rf "$tmp"
}}
trap cleanup EXIT
cat <<'PY' > "$tmp/server.py"
{server_script}
PY
ready=0
if test -s "$tmp/server.py" && \
    python3 -m py_compile "$tmp/server.py"; then
    python3 "$tmp/server.py" "$tmp" \
        >"$tmp/server.out" 2>"$tmp/server.err" &
    pid=$!
    attempt=0
    while [ "$attempt" -lt 50 ]; do
        attempt=$((attempt + 1))
        if test -s "$tmp/port"; then
            port=$(cat "$tmp/port")
            if python3 -c 'import socket,sys; '\
                's=socket.create_connection('\
                '("127.0.0.1",int(sys.argv[1])),1); s.close()' \
                "$port"; then
                ready=1
                break
            fi
        fi
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.1
    done
fi
printf '%s\n' FIXTURE_BEGIN "READY=$ready" FIXTURE_END
if [ "$ready" -ne 1 ]; then
    printf '%s\n' SERVER_BEGIN
    cat "$tmp/server.err" 2>/dev/null || true
    printf '%s\n' SERVER_END
    exit 0
fi
url="http://127.0.0.1:$port{request_path}"
curl --head --silent --show-error "$url" >"$tmp/curl.out"
curl_rc=$?
printf '%s\n' CURL_OUTPUT_BEGIN
cat "$tmp/curl.out" 2>/dev/null || true
printf '%s\n' CURL_OUTPUT_END
printf '%s\n' METHOD_BEGIN
cat "$tmp/method" 2>/dev/null || printf '%s\n' MISSING
printf '%s\n' METHOD_END
printf '%s\n' STATUS_BEGIN "CURL_RC=$curl_rc" STATUS_END
printf '%s\n' SERVER_BEGIN
cat "$tmp/server.err" 2>/dev/null || true
printf '%s\n' SERVER_END
"""
        result = node.execute(command, shell=True)
        text = combined_output(result)
        assert_that(result.exit_code).described_as(
            f"fixture shell rc expected 0, observed {result.exit_code}"
        ).is_equal_to(0)
        fixture = section(text, "FIXTURE_BEGIN", "FIXTURE_END").strip()
        if fixture != "READY=1":
            diagnostics = section(text, "SERVER_BEGIN", "SERVER_END")
            raise SkippedException(
                f"loopback fixture was not ready: {fixture}; {diagnostics}"
            )
        assert_that(fixture).described_as(
            f"fixture readiness expected READY=1, observed {fixture}"
        ).is_equal_to("READY=1")
        status = section(text, "STATUS_BEGIN", "STATUS_END").strip()
        assert_that(status).described_as(
            f"curl status expected CURL_RC=0, observed {status}"
        ).is_equal_to("CURL_RC=0")
        method = section(text, "METHOD_BEGIN", "METHOD_END").strip()
        expected_method = f"HEAD {request_path}"
        assert_that(method).described_as(
            f"HTTP method expected {expected_method}, observed {method}"
        ).is_equal_to(expected_method)
        headers = section(text, "CURL_OUTPUT_BEGIN", "CURL_OUTPUT_END")
        expected_header = f"X-Curl-Probe: {header_marker}"
        assert_that(headers).described_as(
            f"expected response header {expected_header}, observed {headers!r}"
        ).contains(expected_header)
        assert_that(headers).described_as(
            f"HEAD output must omit {body_marker}, observed {headers!r}"
        ).does_not_contain(body_marker)

    @TestCaseMetadata(
        description="""
            Verifies that curl retries one transient HTTP 503 response and honors its
            Retry-After header. It confirms that the second request succeeds, returns
            the expected body, and occurs after the requested delay.

            Corpus obligation: pkg:curl/retry-transient-http-response
        """,
        priority=3,
        tags=["ai-generated"],
    )
    def verify_retry_transient_http_response(self, node: Node, log: Logger) -> None:
        if node.os.information.version < "4.0.0":
            raise SkippedException(
                "this case is derived from an Azure Linux 4.0 corpus and was verified"
                " only on Azure Linux 4.0.0 guests; this node reports "
                f"{node.os.information.version}"
            )

        expected = "curl-retry-success"
        retry_count = 1
        expected_attempts = retry_count + 1
        server_script = rf"""
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

attempts = 0


class Handler(BaseHTTPRequestHandler):
    def log_message(self, message, *args):
        pass

    def _reply(self, status, body=b"", retry_after=None):
        self.send_response(status)
        if retry_after is not None:
            self.send_header("Retry-After", retry_after)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        global attempts
        if self.path == "/ready":
            self._reply(204)
            return
        if self.path != "/service":
            self._reply(404)
            return
        attempts += 1
        with open(sys.argv[3], "a") as handle:
            handle.write(str(time.monotonic()) + "\n")
        if attempts == 1:
            self._reply(503, retry_after="1")
            return
        self._reply(200, b"{expected}")


if sys.argv[1] == "--delta":
    with open(sys.argv[2]) as handle:
        values = [float(value) for value in handle.read().split()]
    if len(values) < 2:
        print("MISSING")
    else:
        print(values[1] - values[0])
else:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    with open(sys.argv[2], "w") as handle:
        handle.write(str(server.server_port) + "\n")
    server.serve_forever()
"""
        command = rf"""
set -u
tmp=$(mktemp -d)
pid=""
trap '[ -z "$pid" ] || kill "$pid" 2>/dev/null || true;
rm -rf "$tmp"' EXIT
cat <<'PY' > "$tmp/server.py"
{server_script}
PY
if ! test -s "$tmp/server.py"; then
    echo FIXTURE_UNREADY
    echo SERVER_ERROR_BEGIN
    echo helper-file-empty
    echo SERVER_ERROR_END
    exit 0
fi
if ! python3 -m py_compile "$tmp/server.py" 2>"$tmp/compile.err"; then
    echo FIXTURE_UNREADY
    echo SERVER_ERROR_BEGIN
    cat "$tmp/compile.err"
    echo SERVER_ERROR_END
    exit 0
fi
python3 "$tmp/server.py" serve "$tmp/port" "$tmp/times" \
    2>"$tmp/server.err" &
pid=$!
ready=0
i=0
while [ "$i" -lt 50 ]; do
    if test -s "$tmp/port"; then
        port=$(cat "$tmp/port")
        if python3 -c '
import socket
import sys
sock = socket.create_connection(("127.0.0.1", int(sys.argv[1])), 0.2)
sock.sendall(b"GET /ready HTTP/1.0\r\n\r\n")
assert sock.recv(1)
' "$port" 2>/dev/null; then
            ready=1
            break
        fi
    fi
    i=$((i + 1))
    sleep 0.1
done
if [ "$ready" -ne 1 ]; then
    echo FIXTURE_UNREADY
    echo SERVER_ERROR_BEGIN
    cat "$tmp/server.err"
    echo SERVER_ERROR_END
    exit 0
fi
echo CURL_VERSION_BEGIN
curl -V
echo CURL_VERSION_END
set +e
status=$(curl --retry {retry_count} --silent --show-error \
    --output "$tmp/body" --write-out '%{{http_code}}' \
    "http://127.0.0.1:$port/service")
curl_rc=$?
set -e
kill "$pid" 2>/dev/null || true
wait "$pid" 2>/dev/null || true
pid=""
count=$(wc -l < "$tmp/times" 2>/dev/null || echo MISSING)
delta=$(python3 "$tmp/server.py" --delta "$tmp/times" \
    2>/dev/null || echo MISSING)
echo CURL_RC_BEGIN
echo "$curl_rc"
echo CURL_RC_END
echo STATUS_BEGIN
echo "$status"
echo STATUS_END
echo REQUEST_COUNT_BEGIN
echo "$count"
echo REQUEST_COUNT_END
echo RETRY_DELTA_BEGIN
echo "$delta"
echo RETRY_DELTA_END
echo BODY_BEGIN
if test -f "$tmp/body"; then
    cat "$tmp/body"
else
    echo MISSING
fi
echo
echo BODY_END
echo SERVER_ERROR_BEGIN
cat "$tmp/server.err"
echo SERVER_ERROR_END
"""
        result = node.execute(command, shell=True)
        text = combined_output(result)
        if "FIXTURE_UNREADY" in text:
            raise SkippedException(
                f"loopback HTTP fixture did not become healthy: {text}"
            )
        assert_that(result.exit_code).described_as(
            f"fixture orchestration must complete: {text}"
        ).is_equal_to(0)
        version = section(text, "CURL_VERSION_BEGIN", "CURL_VERSION_END")
        assert_that(version).described_as(
            f"curl version evidence was: {version}"
        ).contains("curl")
        curl_rc = section(text, "CURL_RC_BEGIN", "CURL_RC_END").strip()
        assert_that(curl_rc).described_as(
            f"curl exit code was {curl_rc}, expected 0; output: {text}"
        ).is_equal_to("0")
        status = section(text, "STATUS_BEGIN", "STATUS_END").strip()
        assert_that(status).described_as(
            f"final HTTP status was {status}, expected 200; output: {text}"
        ).is_equal_to("200")
        count_text = section(text, "REQUEST_COUNT_BEGIN", "REQUEST_COUNT_END").strip()
        assert_that(count_text).described_as(
            f"request count was {count_text}; output: {text}"
        ).is_equal_to(f"{expected_attempts}")
        delta_text = section(text, "RETRY_DELTA_BEGIN", "RETRY_DELTA_END").strip()
        assert_that(delta_text).described_as(
            f"retry delay evidence was {delta_text}; output: {text}"
        ).is_not_equal_to("MISSING")
        delta = float(delta_text)
        assert_that(delta).described_as(
            f"retry delay was {delta} seconds, expected at least 0.8"
        ).is_greater_than_or_equal_to(0.8)
        body = section(text, "BODY_BEGIN", "BODY_END").strip()
        assert_that(body).described_as(
            f"successful response body was {body!r}, expected {expected!r}"
        ).is_equal_to(expected)

    @TestCaseMetadata(
        description="""
            Verifies that curl --json sends the supplied JSON text in a POST request to
            a loopback endpoint. The endpoint records the request method, body,
            Content-Type, and Accept headers so each behavior is asserted independently.

            Corpus obligation: pkg:curl/send-json-post
        """,
        priority=3,
        tags=["ai-generated"],
    )
    def verify_send_json_post(self, node: Node, log: Logger) -> None:
        if node.os.information.version < "4.0.0":
            raise SkippedException(
                "this case is derived from an Azure Linux 4.0 corpus and was verified"
                " only on Azure Linux 4.0.0 guests; this node reports "
                f"{node.os.information.version}"
            )

        payload = '{"kind":"azure-linux-curl"}'
        server = r"""
import socket
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

if sys.argv[1] == "probe":
    with socket.create_connection(
        ("127.0.0.1", int(sys.argv[2])), timeout=1
    ):
        pass
    raise SystemExit(0)

report_path = Path(sys.argv[1])
port_path = Path(sys.argv[2])

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        report = (
            "METHOD=POST\n"
            + "CONTENT_TYPE="
            + self.headers.get("Content-Type", "MISSING")
            + "\nACCEPT="
            + self.headers.get("Accept", "MISSING")
            + "\nBODY="
            + body
            + "\n"
        )
        report_path.write_text(report, encoding="utf-8")
        self.send_response(204)
        self.end_headers()

    def log_message(self, message, *args):
        pass

server = HTTPServer(("127.0.0.1", 0), Handler)
port_path.write_text(str(server.server_port), encoding="utf-8")
server.serve_forever()
"""
        command = rf"""
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cat <<'PY' > "$tmp/server.py"
{server}
PY
if ! test -s "$tmp/server.py"; then
    echo FIXTURE_NOT_READY
    echo SERVER_DIAGNOSTIC_BEGIN
    echo materialized-server-helper-is-empty
    echo SERVER_DIAGNOSTIC_END
    exit 0
fi
if ! python3 -m py_compile "$tmp/server.py" 2>"$tmp/compile.err"; then
    echo FIXTURE_NOT_READY
    echo SERVER_DIAGNOSTIC_BEGIN
    cat "$tmp/compile.err"
    echo SERVER_DIAGNOSTIC_END
    exit 0
fi
python3 "$tmp/server.py" "$tmp/report" "$tmp/port" \
    >"$tmp/server.out" 2>"$tmp/server.err" &
pid=$!
trap 'kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; \
rm -rf "$tmp"' EXIT
ready=0
i=0
while [ "$i" -lt 50 ]; do
    if test -s "$tmp/port"; then
        port=$(cat "$tmp/port")
        if python3 "$tmp/server.py" probe "$port" 2>/dev/null; then
            ready=1
            break
        fi
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
        break
    fi
    i=$((i + 1))
    sleep 0.1
done
if [ "$ready" -ne 1 ]; then
    echo FIXTURE_NOT_READY
    echo SERVER_DIAGNOSTIC_BEGIN
    cat "$tmp/server.err" 2>/dev/null || echo MISSING
    echo SERVER_DIAGNOSTIC_END
    exit 0
fi
set +e
curl --silent --show-error --max-time 10 \
    --json '{payload}' "http://127.0.0.1:$port/submit" \
    >"$tmp/curl.out" 2>"$tmp/curl.err"
curl_rc=$?
set -e
echo CURL_RC_BEGIN
echo "$curl_rc"
echo CURL_RC_END
echo REPORT_BEGIN
cat "$tmp/report" 2>/dev/null || echo MISSING
echo REPORT_END
echo CURL_OUTPUT_BEGIN
cat "$tmp/curl.out" 2>/dev/null || true
cat "$tmp/curl.err" 2>/dev/null || true
echo CURL_OUTPUT_END
echo SERVER_DIAGNOSTIC_BEGIN
cat "$tmp/server.err" 2>/dev/null || true
echo SERVER_DIAGNOSTIC_END
"""
        result = node.execute(command, shell=True)
        text = combined_output(result)
        (
            assert_that(result.exit_code)
            .described_as(
                f"guest harness rc was {result.exit_code}, expected 0; output: {text}"
            )
            .is_equal_to(0)
        )
        if "FIXTURE_NOT_READY" in text:
            raise SkippedException(
                f"loopback fixture did not become ready; observed output: {text}"
            )
        curl_rc = section(text, "CURL_RC_BEGIN", "CURL_RC_END").strip()
        report = section_lines(text, "REPORT_BEGIN", "REPORT_END")
        (
            assert_that(curl_rc)
            .described_as(f"curl exit code was {curl_rc}, expected 0; output: {text}")
            .is_equal_to("0")
        )
        (
            assert_that(report)
            .described_as(f"report had {len(report)} lines, expected 4: {report}")
            .is_length(4)
        )
        (
            assert_that(report)
            .described_as(f"POST method evidence was absent; observed report: {report}")
            .contains("METHOD=POST")
        )
        (
            assert_that(report)
            .described_as(
                f"Content-Type was not application/json; observed report: {report}"
            )
            .contains("CONTENT_TYPE=application/json")
        )
        (
            assert_that(report)
            .described_as(f"Accept was not application/json; observed report: {report}")
            .contains("ACCEPT=application/json")
        )
        (
            assert_that(report)
            .described_as(f"body differed from {payload}; observed report: {report}")
            .contains(f"BODY={payload}")
        )

    @TestCaseMetadata(
        description="""
            Verifies that curl submits text and file parts with --form in a
            multipart/form-data POST. A loopback HTTP endpoint parses the request and
            reports the media type, text value, uploaded filename, and uploaded content.

            Corpus obligation: pkg:curl/submit-multipart-form
        """,
        priority=3,
        tags=["ai-generated"],
    )
    def verify_submit_multipart_form(self, node: Node, log: Logger) -> None:
        if node.os.information.version < "4.0.0":
            raise SkippedException(
                "this case is derived from an Azure Linux 4.0 corpus and was verified"
                " only on Azure Linux 4.0.0 guests; this node reports "
                f"{node.os.information.version}"
            )

        text_field = "description"
        text_value = "azure-linux-curl-form"
        file_field = "attachment"
        file_name = "upload.txt"
        file_value = "multipart-file-content"
        server_script = rf"""
import sys
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, HTTPServer

port_path = sys.argv[1]
evidence_path = sys.argv[2]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, pattern, *args):
        return

    def do_GET(self):
        self.send_response(204)
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        content_type = self.headers.get("Content-Type", "")
        prefix = b"Content-Type: " + content_type.encode("utf-8")
        prefix += b"\r\nMIME-Version: 1.0\r\n\r\n"
        message = BytesParser(policy=default).parsebytes(prefix + body)
        text_seen = "MISSING"
        file_seen = "MISSING"
        filename_seen = "MISSING"
        if message.is_multipart():
            for part in message.iter_parts():
                name = part.get_param(
                    "name", header="content-disposition"
                )
                payload = part.get_payload(decode=True) or b""
                value = payload.decode("utf-8", errors="replace")
                if name == {text_field!r}:
                    text_seen = value
                if name == {file_field!r}:
                    file_seen = value
                    filename_seen = part.get_filename() or "MISSING"
        lines = [
            "MEDIA=" + message.get_content_type(),
            "TEXT=" + text_seen,
            "FILE_NAME=" + filename_seen,
            "FILE_BODY=" + file_seen,
        ]
        with open(evidence_path, "w", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + "\n")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"accepted")


server = HTTPServer(("127.0.0.1", 0), Handler)
with open(port_path, "w", encoding="utf-8") as stream:
    stream.write(str(server.server_port) + "\n")
server.serve_forever()
"""
        command = f"""
tmp=$(mktemp -d)
pid=""
cleanup() {{
    if [ -n "$pid" ]; then
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    fi
    rm -rf "$tmp"
}}
trap cleanup EXIT
cat <<'PY' > "$tmp/server.py"
{server_script}
PY
if ! test -s "$tmp/server.py"; then
    echo FIXTURE_STATUS_BEGIN
    echo NOT_READY
    echo FIXTURE_STATUS_END
    echo SERVER_LOG_BEGIN
    echo "server helper is empty"
    echo SERVER_LOG_END
    exit 0
fi
if ! python3 -m py_compile "$tmp/server.py" 2>"$tmp/compile.err"; then
    echo FIXTURE_STATUS_BEGIN
    echo NOT_READY
    echo FIXTURE_STATUS_END
    echo SERVER_LOG_BEGIN
    cat "$tmp/compile.err"
    echo SERVER_LOG_END
    exit 0
fi
python3 "$tmp/server.py" "$tmp/port" "$tmp/evidence" \
    >"$tmp/server.out" 2>"$tmp/server.err" &
pid=$!
ready=0
port=""
for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if test -s "$tmp/port"; then
        port=$(cat "$tmp/port")
        if curl --silent --output /dev/null \
            "http://127.0.0.1:$port/ready"; then
            ready=1
            break
        fi
    fi
    sleep 0.1
done
if [ "$ready" -ne 1 ]; then
    echo FIXTURE_STATUS_BEGIN
    echo NOT_READY
    echo FIXTURE_STATUS_END
    echo SERVER_LOG_BEGIN
    cat "$tmp/server.out" "$tmp/server.err" 2>/dev/null || true
    echo SERVER_LOG_END
    exit 0
fi
echo FIXTURE_STATUS_BEGIN
echo READY
echo FIXTURE_STATUS_END
printf '%s' '{file_value}' > "$tmp/{file_name}"
curl --silent --show-error --output "$tmp/response" \
    --form '{text_field}={text_value}' \
    --form "{file_field}=@$tmp/{file_name}" \
    "http://127.0.0.1:$port/submit" 2>"$tmp/curl.err"
curl_rc=$?
echo CURL_RC_BEGIN
echo "$curl_rc"
echo CURL_RC_END
echo EVIDENCE_BEGIN
if test -s "$tmp/evidence"; then
    cat "$tmp/evidence"
else
    echo MEDIA=MISSING
    echo TEXT=MISSING
    echo FILE_NAME=MISSING
    echo FILE_BODY=MISSING
fi
echo EVIDENCE_END
echo CURL_LOG_BEGIN
cat "$tmp/curl.err" 2>/dev/null || true
echo CURL_LOG_END
echo SERVER_LOG_BEGIN
cat "$tmp/server.out" "$tmp/server.err" 2>/dev/null || true
echo SERVER_LOG_END
"""
        result = node.execute(command, shell=True)
        text = combined_output(result)
        fixture_status = section(
            text, "FIXTURE_STATUS_BEGIN", "FIXTURE_STATUS_END"
        ).strip()
        server_log = section(text, "SERVER_LOG_BEGIN", "SERVER_LOG_END")
        if fixture_status == "NOT_READY":
            raise SkippedException(
                f"multipart fixture did not become ready: {server_log}"
            )
        assert_that(result.exit_code).described_as(
            f"guest multipart script failed with output: {text}"
        ).is_equal_to(0)
        assert_that(fixture_status).described_as(
            f"fixture status was {fixture_status}; server log: {server_log}"
        ).is_equal_to("READY")
        curl_rc = section(text, "CURL_RC_BEGIN", "CURL_RC_END").strip()
        curl_log = section(text, "CURL_LOG_BEGIN", "CURL_LOG_END")
        assert_that(curl_rc).described_as(
            f"curl returned {curl_rc}; diagnostic: {curl_log}"
        ).is_equal_to("0")
        evidence = section_lines(text, "EVIDENCE_BEGIN", "EVIDENCE_END")
        assert_that(evidence).described_as(
            f"multipart media evidence was {evidence}"
        ).contains("MEDIA=multipart/form-data")
        assert_that(evidence).described_as(
            f"multipart text-part evidence was {evidence}"
        ).contains(f"TEXT={text_value}")
        assert_that(evidence).described_as(
            f"multipart filename evidence was {evidence}"
        ).contains(f"FILE_NAME={file_name}")
        assert_that(evidence).described_as(
            f"multipart file-part evidence was {evidence}"
        ).contains(f"FILE_BODY={file_value}")

    @TestCaseMetadata(
        description="""
            Verifies that curl uploads a local file to a loopback HTTP endpoint with
            --upload-file. The server records the request path and body, and the case
            confirms that the received bytes exactly match the source file.

            Corpus obligation: pkg:curl/upload-local-file
        """,
        priority=3,
        tags=["ai-generated"],
    )
    def verify_upload_local_file(self, node: Node, log: Logger) -> None:
        if node.os.information.version < "4.0.0":
            raise SkippedException(
                "this case is derived from an Azure Linux 4.0 corpus and was verified"
                " only on Azure Linux 4.0.0 guests; this node reports "
                f"{node.os.information.version}"
            )

        endpoint_path = "/upload-target"
        helper = rf"""
import http.server
import pathlib
import socket
import sys

if sys.argv[1] == "probe":
    sock = socket.create_connection(
        ("127.0.0.1", int(sys.argv[2])), timeout=1
    )
    sock.close()
    sys.exit(0)

root = pathlib.Path(sys.argv[2])


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _reply(self, code):
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_PUT(self):
        (root / "request_path").write_text(self.path)
        if self.path != "{endpoint_path}":
            self._reply(404)
            return
        length_text = self.headers.get("Content-Length")
        if length_text is None:
            self._reply(411)
            return
        length = int(length_text)
        data = self.rfile.read(length)
        (root / "received.bin").write_bytes(data)
        self._reply(204)

    def log_message(self, message, *args):
        return


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
(root / "port").write_text(str(server.server_port) + "\n")
server.serve_forever()
"""
        command = rf"""
tmp=$(mktemp -d /tmp/curl-upload.XXXXXX)
server_pid=
helper_ok=1
ready=0
cat <<'PY' > "$tmp/server.py"
{helper}
PY
test -s "$tmp/server.py" || helper_ok=0
python3 -m py_compile "$tmp/server.py" \
    >"$tmp/compile.log" 2>&1 || helper_ok=0
printf '%s\n' \
    'curl upload payload: first line' \
    'curl upload payload: second line' >"$tmp/source.bin"
if [ "$helper_ok" -eq 1 ]; then
    python3 "$tmp/server.py" serve "$tmp" \
        >"$tmp/server.out" 2>"$tmp/server.err" &
    server_pid=$!
    attempt=0
    while [ "$attempt" -lt 50 ]; do
        if [ -s "$tmp/port" ]; then
            port=$(cat "$tmp/port")
            if python3 "$tmp/server.py" probe "$port" \
                >/dev/null 2>&1; then
                ready=1
                break
            fi
        fi
        sleep 0.1
        attempt=$((attempt + 1))
    done
fi
echo FIXTURE_BEGIN
echo "HELPER_OK=$helper_ok"
echo "READY=$ready"
echo SERVER_LOG_BEGIN
tail -n 20 "$tmp/compile.log" 2>/dev/null || true
tail -n 20 "$tmp/server.err" 2>/dev/null || true
echo SERVER_LOG_END
echo FIXTURE_END
curl_rc=NOT_RUN
received=MISSING
request_path=MISSING
bytes_match=no
source_size=$(wc -c <"$tmp/source.bin" 2>/dev/null || echo MISSING)
received_size=MISSING
if [ "$ready" -eq 1 ]; then
    url="http://127.0.0.1:$port{endpoint_path}"
    curl --silent --show-error --upload-file "$tmp/source.bin" "$url" \
        >"$tmp/curl.log" 2>&1
    curl_rc=$?
    if [ -f "$tmp/received.bin" ]; then
        received=present
        received_size=$(wc -c <"$tmp/received.bin" 2>/dev/null || echo MISSING)
        if cmp -s "$tmp/source.bin" "$tmp/received.bin"; then
            bytes_match=yes
        fi
    fi
    request_path=$(cat "$tmp/request_path" 2>/dev/null || echo MISSING)
fi
echo UPLOAD_BEGIN
echo "CURL_RC=$curl_rc"
echo "RECEIVED=$received"
echo "REQUEST_PATH=$request_path"
echo "SOURCE_SIZE=$source_size"
echo "RECEIVED_SIZE=$received_size"
echo "BYTES_MATCH=$bytes_match"
echo CURL_LOG_BEGIN
tail -n 20 "$tmp/curl.log" 2>/dev/null || true
echo CURL_LOG_END
echo UPLOAD_END
if [ -n "$server_pid" ]; then
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
fi
rm -rf "$tmp"
exit 0
"""
        result = node.execute(command, shell=True)
        text = combined_output(result)
        assert_that(result.exit_code).described_as(
            f"upload fixture script failed with output: {text}"
        ).is_equal_to(0)
        fixture = section(text, "FIXTURE_BEGIN", "FIXTURE_END")
        fixture_lines = section_lines(text, "FIXTURE_BEGIN", "FIXTURE_END")
        if "READY=1" not in fixture_lines:
            raise SkippedException(
                f"loopback upload fixture did not become ready: {fixture}"
            )
        assert_that(fixture_lines).described_as(
            f"fixture evidence was: {fixture}"
        ).contains("HELPER_OK=1")
        upload = section(text, "UPLOAD_BEGIN", "UPLOAD_END")
        upload_lines = section_lines(text, "UPLOAD_BEGIN", "UPLOAD_END")
        assert_that(upload_lines).described_as(
            f"curl upload evidence was: {upload}"
        ).contains("CURL_RC=0")
        assert_that(upload_lines).described_as(
            f"endpoint receipt evidence was: {upload}"
        ).contains("RECEIVED=present")
        assert_that(upload_lines).described_as(
            f"request path evidence was: {upload}"
        ).contains(f"REQUEST_PATH={endpoint_path}")
        assert_that(upload_lines).described_as(
            f"uploaded-byte comparison evidence was: {upload}"
        ).contains("BYTES_MATCH=yes")
