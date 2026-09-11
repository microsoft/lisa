# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Release-gate tests for curl on Azure Linux.

Each case verifies one reviewed behaviour obligation directly against the
node under test. Generated from a reviewed behaviour corpus (IR).
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
from lisa.operating_system import CBLMariner
from lisa.tools import Cat, Mkdir, Rm, Tee
from lisa.util import LisaException, SkippedException, UnsupportedDistroException


@TestSuiteMetadata(
    area="packages",
    category="functional",
    description="Release-gate tests for curl on Azure Linux.",
    tags=["ai-generated"],
    owner="azurelinux",
    requirement=simple_requirement(supported_os=[CBLMariner]),
    maturity="preview",
)
class CurlSuite(TestSuite):
    """Release-gate behaviour tests for curl."""

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        """Prepare the guest this suite's material was verified on."""
        self.arranged = []
        node: Node = kwargs["node"]
        if not isinstance(node.os, CBLMariner) or node.os.information.version < "4.0.0":
            raise SkippedException(
                UnsupportedDistroException(
                    node.os,
                    "This suite is supported only on Azure Linux 4.0.0 or later.",
                )
            )
        node.os.install_packages(
            [
                "curl",
                "python3",
            ]
        )
        node.tools[Tee].write_to_file(
            (
                "import sys\n"
                "from http.server import BaseHTTPRequestHandler\n"
                "from http.server import ThreadingHTTPServer\n"
                "\n"
                "SEEN = {}\n"
                "\n"
                'RANGE_BODY = "0123456789abcdefghijklmnopqrstuvwxyz"\n'
                "\n"
                "\n"
                "class Origin(BaseHTTPRequestHandler):\n"
                '    protocol_version = "HTTP/1.1"\n'
                "\n"
                "    def log_message(self, fmt, *args):\n"
                "        return\n"
                "\n"
                "    def reply(self, code, body, extra=None):\n"
                "        raw = body.encode()\n"
                "        self.send_response(code)\n"
                "        for key, value in (extra or {}).items():\n"
                "            self.send_header(key, value)\n"
                '        self.send_header("Content-Type", "text/plain")\n'
                '        self.send_header("Content-Length", str(len(raw)))\n'
                "        self.end_headers()\n"
                '        if self.command != "HEAD":\n'
                "            self.wfile.write(raw)\n"
                "\n"
                "    def route(self):\n"
                "        path = self.path\n"
                '        extra = {"X-Origin": "azl"}\n'
                '        if path.startswith("http://"):\n'
                '            extra["Via"] = "azl-origin"\n'
                '            rest = path.split("/", 3)\n'
                '            path = "/" + (rest[3] if len(rest) > 3 else "")\n'
                '        if path.startswith("/status/"):\n'
                '            code = path.rsplit("/", 1)[-1]\n'
                "            if code.isdigit():\n"
                '                self.reply(int(code), "status\\n", extra)\n'
                "                return\n"
                '        if path.startswith("/auth"):\n'
                '            if not self.headers.get("Authorization"):\n'
                '                challenge = "Basic realm=azl"\n'
                '                extra["WWW-Authenticate"] = challenge\n'
                '                self.reply(401, "denied\\n", extra)\n'
                "                return\n"
                '            self.reply(200, "welcome", extra)\n'
                "            return\n"
                '        if path.startswith("/flaky"):\n'
                '            count = SEEN.get("flaky", 0) + 1\n'
                '            SEEN["flaky"] = count\n'
                "            if count < 2:\n"
                '                extra["Retry-After"] = "1"\n'
                '                self.reply(429, "later", extra)\n'
                "                return\n"
                '            self.reply(200, "recovered", extra)\n'
                "            return\n"
                '        if path.startswith("/range"):\n'
                "            self.serve_range(extra)\n"
                "            return\n"
                '        if path.startswith("/redirect"):\n'
                '            extra["Location"] = "/"\n'
                '            self.reply(302, "moved\\n", extra)\n'
                "            return\n"
                '        self.reply(200, "hello", extra)\n'
                "\n"
                "    def serve_range(self, extra):\n"
                "        raw = RANGE_BODY.encode()\n"
                "        total = len(raw)\n"
                '        extra["Accept-Ranges"] = "bytes"\n'
                '        spec = self.headers.get("Range", "")\n'
                '        if not spec.startswith("bytes="):\n'
                "            self.reply(200, RANGE_BODY, extra)\n"
                "            return\n"
                '        bounds = spec[6:].split("-", 1)\n'
                "        first = bounds[0]\n"
                '        last = bounds[1] if len(bounds) > 1 else ""\n'
                "        if not first.isdigit():\n"
                "            self.reply(200, RANGE_BODY, extra)\n"
                "            return\n"
                "        start = int(first)\n"
                "        end = int(last) if last.isdigit() else total - 1\n"
                "        if start >= total or end < start:\n"
                "            self.reply(200, RANGE_BODY, extra)\n"
                "            return\n"
                "        if end >= total:\n"
                "            end = total - 1\n"
                '        extra["Content-Range"] = "bytes %d-%d/%d" % (\n'
                "            start,\n"
                "            end,\n"
                "            total,\n"
                "        )\n"
                "        self.reply(206, RANGE_BODY[start:end + 1], extra)\n"
                "\n"
                "    def do_GET(self):\n"
                "        self.route()\n"
                "\n"
                "    def do_HEAD(self):\n"
                "        self.route()\n"
                "\n"
                "    def absorb(self):\n"
                '        size = int(self.headers.get("Content-Length", "0"))\n'
                '        raw = self.rfile.read(size) if size else b""\n'
                '        extra = {"X-Origin": "azl"}\n'
                '        if self.path.startswith("/echo"):\n'
                '            text = raw.decode("utf-8", "replace")\n'
                "            self.reply(200, text, extra)\n"
                "            return\n"
                '        self.reply(200, "received", extra)\n'
                "\n"
                "    def do_POST(self):\n"
                "        self.absorb()\n"
                "\n"
                "    def do_PUT(self):\n"
                "        self.absorb()\n"
                "\n"
                "\n"
                "port = int(sys.argv[1])\n"
                "\n"
                "\n"
                "class Server(ThreadingHTTPServer):\n"
                "    daemon_threads = True\n"
                "\n"
                "    def handle_error(self, request, client_address):\n"
                "        return\n"
                "\n"
                "\n"
                'server = Server(("127.0.0.1", port), Origin)\n'
                "server.serve_forever()\n"
            ),
            node.get_pure_path("/tmp/azl-http-origin.py"),
            append=False,
            sudo=False,
        )
        started = node.execute_async("python3 /tmp/azl-http-origin.py 18080")
        self.arranged.append(started)
        ready = False
        for _ in range(30):
            probe = node.execute("curl -sf http://127.0.0.1:18080/")
            if probe.exit_code == 0:
                ready = True
                break
        if not ready:
            raise LisaException("the loopback-origin arrangement never answered")

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        """Take down everything this suite arranged, whatever the verdict was."""
        for process in self.arranged:
            process.kill()
        self.arranged = []

    @TestCaseMetadata(
        description=(
            "Verifies the curl behaviour: Supply credentials for server\n"
            "authentication to retrieve a known protected response.\n"
            "\n"
            "Corpus obligation: pkg:curl/authenticate-server-request\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        # Bounds a hang only: measured cases finish in under 20 seconds.
        timeout=1800,
        tags=["ai-generated"],
    )
    def verify_authenticate_server_request(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:curl/authenticate-server-request."""
        log.info("Verifying obligation pkg:curl/authenticate-server-request")
        result = node.execute(
            "curl --user azl:secret http://127.0.0.1:18080/auth",
            no_debug_log=True,
        )
        combined_output = f"{result.stdout}\n{result.stderr}"
        assert_that(result.exit_code).described_as(
            "authenticated transfer completes successfully"
        ).is_equal_to(0)
        assert_that(combined_output).described_as(
            "valid server credentials retrieve the protected response"
        ).contains("welcome")

    @TestCaseMetadata(
        description=(
            "Verifies the curl behaviour: Save a known response body to a\n"
            "caller-selected file instead of standard output.\n"
            "\n"
            "Corpus obligation: pkg:curl/download-to-named-file\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        # Bounds a hang only: measured cases finish in under 20 seconds.
        timeout=1800,
        tags=["ai-generated"],
    )
    def verify_download_to_named_file(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:curl/download-to-named-file."""
        log.info("Verifying obligation pkg:curl/download-to-named-file")
        work_dir = node.get_pure_path(
            f"/tmp/lisa-curl-download-to-named-file-{node.name}"
        )
        destination = work_dir / "response.txt"
        node.tools[Rm].remove_directory(str(work_dir))
        node.tools[Mkdir].create_directory(str(work_dir))
        try:
            result = node.execute(
                ("curl --output response.txt http://127.0.0.1:18080"),
                shell=False,
                cwd=work_dir,
                expected_exit_code=0,
            )
            saved = node.tools[Cat].read(str(destination), force_run=True)
            combined_output = f"{result.stdout}\n{result.stderr}"
            assert_that(saved).described_as(
                "caller-selected file contains the known response body"
            ).is_equal_to("hello")
            assert_that(combined_output).described_as(
                "response body is withheld from command output when saved to a file"
            ).does_not_contain("hello")

            contrast = node.execute(
                "curl http://127.0.0.1:18080",
                shell=False,
                cwd=work_dir,
                expected_exit_code=0,
            )
            contrast_output = f"{contrast.stdout}\n{contrast.stderr}"
            assert_that(contrast_output).described_as(
                "known response body is observable without output redirection"
            ).contains("hello")
        finally:
            node.tools[Rm].remove_directory(str(work_dir))

    @TestCaseMetadata(
        description=(
            "Verifies the curl behaviour: Return a failure instead of an HTTP\n"
            "error body for a non-authentication error response.\n"
            "\n"
            "Corpus obligation: pkg:curl/fail-on-http-error\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        # Bounds a hang only: measured cases finish in under 20 seconds.
        timeout=1800,
        tags=["ai-generated"],
    )
    def verify_fail_on_http_error(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:curl/fail-on-http-error."""
        log.info("Verifying obligation pkg:curl/fail-on-http-error")
        fail_result = node.execute("curl --fail http://127.0.0.1:18080/status/404")
        fail_output = f"{fail_result.stdout}{fail_result.stderr}"
        assert_that(fail_result.exit_code).described_as(
            "curl --fail returns the HTTP error exit code"
        ).is_equal_to(22)
        assert_that(fail_output).described_as(
            "curl --fail suppresses the HTTP error response body"
        ).does_not_contain("status")
        plain_result = node.execute("curl http://127.0.0.1:18080/status/404")
        plain_output = f"{plain_result.stdout}{plain_result.stderr}"
        assert_that(plain_result.exit_code).described_as(
            "curl without --fail accepts the HTTP response"
        ).is_equal_to(0)
        assert_that(plain_output).described_as(
            "the arranged HTTP error response body is observable without --fail"
        ).contains("status")

    @TestCaseMetadata(
        description=(
            "Verifies the curl behaviour: Follow a redirect response to\n"
            "retrieve the final resource.\n"
            "\n"
            "Corpus obligation: pkg:curl/follow-http-redirect\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        # Bounds a hang only: measured cases finish in under 20 seconds.
        timeout=1800,
        tags=["ai-generated"],
    )
    def verify_follow_http_redirect(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:curl/follow-http-redirect."""
        log.info("Verifying obligation pkg:curl/follow-http-redirect")
        result = node.execute(
            "curl --location http://127.0.0.1:18080/redirect",
            shell=False,
        )
        output = f"{result.stdout}\n{result.stderr}"
        assert_that(result.exit_code).described_as(
            "redirect retrieval completes successfully"
        ).is_equal_to(0)
        assert_that(output).described_as(
            "redirect retrieval returns the known final response"
        ).contains("hello")

    @TestCaseMetadata(
        description=(
            "Verifies the curl behaviour: Route a request through an\n"
            "explicitly specified controlled proxy.\n"
            "\n"
            "Corpus obligation: pkg:curl/request-through-proxy\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        # Bounds a hang only: measured cases finish in under 20 seconds.
        timeout=1800,
        tags=["ai-generated"],
    )
    def verify_request_through_proxy(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:curl/request-through-proxy."""
        log.info("Verifying obligation pkg:curl/request-through-proxy")
        result = node.execute(
            (
                'curl --silent --show-error --include --noproxy "" '
                "--proxy http://127.0.0.1:18080 "
                "http://127.0.0.1:18080"
            ),
            shell=False,
        )
        combined_output = f"{result.stdout}\n{result.stderr}"
        assert_that(result.exit_code).described_as(
            "curl completes the request through the explicit proxy"
        ).is_equal_to(0)
        assert_that(combined_output).described_as(
            "proxy response carries the evidenced proxy marker header"
        ).contains("Via")
        assert_that(combined_output).described_as(
            "proxy response carries the evidenced proxy marker value"
        ).contains("azl-origin")
        assert_that(combined_output).described_as(
            "curl returns the known origin response"
        ).contains("hello")

    @TestCaseMetadata(
        description=(
            "Verifies the curl behaviour: Resume a local partial destination\n"
            "from a range-capable remote resource.\n"
            "\n"
            "Corpus obligation: pkg:curl/resume-partial-download\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        # Bounds a hang only: measured cases finish in under 20 seconds.
        timeout=1800,
        tags=["ai-generated"],
    )
    def verify_resume_partial_download(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:curl/resume-partial-download."""
        log.info("Verifying obligation pkg:curl/resume-partial-download")
        workspace = node.get_pure_path(
            f"/tmp/lisa-{node.name}-curl-resume-partial-download"
        )
        node.tools[Mkdir].create_directory(str(workspace))
        try:
            node.execute(
                (
                    "curl --silent --show-error --fail --range 0-9 "
                    "--output resumed.bin http://127.0.0.1:18080/range"
                ),
                cwd=workspace,
                expected_exit_code=0,
            )
            prefix = node.tools[Cat].read(
                str(workspace / "resumed.bin"), force_run=True
            )
            assert_that(prefix).described_as(
                "resume destination starts with the known remote prefix"
            ).is_equal_to("0123456789")

            node.execute(
                (
                    "curl --silent --show-error --fail --continue-at - "
                    "--output resumed.bin http://127.0.0.1:18080/range"
                ),
                cwd=workspace,
                expected_exit_code=0,
            )
            completed = node.tools[Cat].read(
                str(workspace / "resumed.bin"), force_run=True
            )
            assert_that(completed).described_as(
                "resumed destination equals the complete remote content"
            ).is_equal_to("0123456789abcdefghijklmnopqrstuvwxyz")

            node.execute(
                (
                    "curl --silent --show-error --fail --range 1-10 "
                    "--output contrast.bin http://127.0.0.1:18080/range"
                ),
                cwd=workspace,
                expected_exit_code=0,
            )
            contrasting_prefix = node.tools[Cat].read(
                str(workspace / "contrast.bin"), force_run=True
            )
            assert_that(contrasting_prefix).described_as(
                "contrast destination has a distinct ten-byte local prefix"
            ).is_equal_to("123456789a")

            node.execute(
                (
                    "curl --silent --show-error --fail --continue-at - "
                    "--output contrast.bin http://127.0.0.1:18080/range"
                ),
                cwd=workspace,
                expected_exit_code=0,
            )
            contrasting_result = node.tools[Cat].read(
                str(workspace / "contrast.bin"), force_run=True
            )
            assert_that(contrasting_result).described_as(
                "resume preserves the existing prefix and appends from its offset"
            ).is_equal_to("123456789aabcdefghijklmnopqrstuvwxyz")
            assert_that(contrasting_result).described_as(
                "an incorrect local prefix does not become the known remote content"
            ).is_not_equal_to("0123456789abcdefghijklmnopqrstuvwxyz")
        finally:
            node.tools[Rm].remove_directory(str(workspace))

    @TestCaseMetadata(
        description=(
            "Verifies the curl behaviour: Request and display HTTP response\n"
            "headers without transferring the body.\n"
            "\n"
            "Corpus obligation: pkg:curl/retrieve-response-headers\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        # Bounds a hang only: measured cases finish in under 20 seconds.
        timeout=1800,
        tags=["ai-generated"],
    )
    def verify_retrieve_response_headers(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:curl/retrieve-response-headers."""
        log.info("Verifying obligation pkg:curl/retrieve-response-headers")
        head = node.execute("curl --head http://127.0.0.1:18080")
        head_output = f"{head.stdout}\n{head.stderr}"
        assert_that(head_output).described_as(
            "HEAD output displays the known response header name"
        ).contains("X-Origin")
        assert_that(head_output).described_as(
            "HEAD output displays the known response header value"
        ).contains("azl")
        assert_that(head_output).described_as(
            "HEAD output does not transfer the response body"
        ).does_not_contain("hello")
        get = node.execute("curl http://127.0.0.1:18080")
        get_output = f"{get.stdout}\n{get.stderr}"
        assert_that(get_output).described_as(
            "ordinary retrieval shows the response body is available"
        ).contains("hello")

    @TestCaseMetadata(
        description=(
            "Verifies the curl behaviour: Retry a transient HTTP failure and\n"
            "honor its Retry-After delay before success.\n"
            "\n"
            "Corpus obligation: pkg:curl/retry-transient-http-response\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        # Bounds a hang only: measured cases finish in under 20 seconds.
        timeout=1800,
        tags=["ai-generated"],
    )
    def verify_retry_transient_http_response(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:curl/retry-transient-http-response."""
        log.info("Verifying obligation pkg:curl/retry-transient-http-response")
        result = node.execute(("curl --retry 1 --include http://127.0.0.1:18080/flaky"))
        output = f"{result.stdout}\n{result.stderr}"
        assert_that(result.exit_code).described_as(
            "curl completes successfully after retrying the transient response"
        ).is_equal_to(0)
        assert_that(output).described_as(
            "curl observes the transient HTTP 429 response before recovery"
        ).contains("429")
        assert_that(output).described_as(
            "curl receives the Retry-After instruction for the transient response"
        ).contains("Retry-After")
        assert_that(output).described_as(
            "curl returns the successful response after the permitted retry"
        ).contains("recovered")

    @TestCaseMetadata(
        description=(
            "Verifies the curl behaviour: Send specified JSON text as an HTTP\n"
            "POST request with JSON media headers.\n"
            "\n"
            "Corpus obligation: pkg:curl/send-json-post\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        # Bounds a hang only: measured cases finish in under 20 seconds.
        timeout=1800,
        tags=["ai-generated"],
    )
    def verify_send_json_post(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:curl/send-json-post."""
        log.info("Verifying obligation pkg:curl/send-json-post")
        json_text = "{}"
        body_result = node.execute(
            "curl --silent --show-error --json {} http://127.0.0.1:18080/echo"
        )
        assert_that(body_result.exit_code).described_as(
            "curl completes the JSON POST request"
        ).is_equal_to(0)
        body_output = f"{body_result.stdout}\n{body_result.stderr}"
        assert_that(body_output.strip()).described_as(
            "endpoint echo proves receipt of the specified JSON body"
        ).is_equal_to(json_text)
        trace_result = node.execute(
            "curl --silent --show-error --verbose --json {} http://127.0.0.1:18080/echo"
        )
        assert_that(trace_result.exit_code).described_as(
            "curl completes the observable JSON POST request"
        ).is_equal_to(0)
        trace_output = f"{trace_result.stdout}\n{trace_result.stderr}"
        assert_that(trace_output).described_as(
            "request is POST and carries both JSON media headers"
        ).contains(
            "POST /echo",
            "Content-Type: application/json",
            "Accept: application/json",
        )

    @TestCaseMetadata(
        description=(
            "Verifies the curl behaviour: Submit text and file parts in an\n"
            "HTTP multipart form request.\n"
            "\n"
            "Corpus obligation: pkg:curl/submit-multipart-form\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        # Bounds a hang only: measured cases finish in under 20 seconds.
        timeout=1800,
        tags=["ai-generated"],
    )
    def verify_submit_multipart_form(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:curl/submit-multipart-form."""
        log.info("Verifying obligation pkg:curl/submit-multipart-form")
        fixture = node.get_pure_path("/tmp/lisa-curl-form-file-part.txt")
        try:
            node.tools[Tee].write_to_file("AZL_FILE_PART_91", fixture)
            result = node.execute(
                (
                    "curl --silent --show-error "
                    "--form text=AZL_TEXT_PART_73 "
                    "--form upload=@/tmp/lisa-curl-form-file-part.txt "
                    "http://127.0.0.1:18080/echo"
                )
            )
            output = f"{result.stdout}\n{result.stderr}"
            assert_that(result.exit_code).described_as(
                "curl completed the multipart submission"
            ).is_equal_to(0)
            text_disposition = 'Content-Disposition: form-data; name="text"'
            file_disposition = (
                'Content-Disposition: form-data; name="upload"; '
                'filename="lisa-curl-form-file-part.txt"'
            )
            assert_that(output).described_as(
                "echoed request is multipart form data with both named parts"
            ).contains(
                text_disposition,
                file_disposition,
                "AZL_TEXT_PART_73",
                "AZL_FILE_PART_91",
            )
        finally:
            node.tools[Rm].remove_file(str(fixture))

    @TestCaseMetadata(
        description=(
            "Verifies the curl behaviour: Upload known local bytes to an HTTP\n"
            "PUT endpoint.\n"
            "\n"
            "Corpus obligation: pkg:curl/upload-local-file\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        # Bounds a hang only: measured cases finish in under 20 seconds.
        timeout=1800,
        tags=["ai-generated"],
    )
    def verify_upload_local_file(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:curl/upload-local-file."""
        log.info("Verifying obligation pkg:curl/upload-local-file")
        work_dir = node.get_pure_path(f"/tmp/lisa-curl-upload-local-file-{node.name}")
        upload_file = work_dir / "upload.txt"
        payload = "azure-linux-curl-upload-marker"
        node.tools[Mkdir].create_directory(str(work_dir))
        try:
            node.tools[Tee].write_to_file(payload, upload_file)
            result = node.execute(
                (
                    "curl --silent --show-error --upload-file upload.txt "
                    "http://127.0.0.1:18080/echo"
                ),
                cwd=work_dir,
            )
            combined = f"{result.stdout}\n{result.stderr}"
            assert_that(result.exit_code).described_as(
                "curl completes the HTTP PUT upload successfully"
            ).is_equal_to(0)
            assert_that(combined.strip()).described_as(
                "HTTP PUT endpoint receives exactly the uploaded file content"
            ).is_equal_to(payload)
        finally:
            node.tools[Rm].remove_directory(str(work_dir))
