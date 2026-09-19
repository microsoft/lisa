# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Release-gate tests for curl on Azure Linux.

Each case verifies one reviewed behaviour obligation directly against the
node under test. Generated from a reviewed behaviour corpus (IR).

Every case declares the same timeout of 120 seconds.
Bounds a hang only: the slowest measured case finishes in 17.32 seconds.
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
from lisa.tools import Cat, Mkdir, Rm, Stat, Tee
from lisa.util import SkippedException, UnsupportedDistroException, check_till_timeout


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

        def _loopback_origin_ready_0() -> bool:
            """Return whether the loopback-origin arrangement answers yet."""
            if not started.is_running():
                log.info("the loopback-origin arrangement stopped before it answered")
                return False
            return node.execute("curl -sf http://127.0.0.1:18080/").exit_code == 0

        check_till_timeout(
            _loopback_origin_ready_0,
            "the loopback-origin arrangement never answered its readiness probe",
            timeout=60,
            interval=1,
        )

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        """Take down everything this suite arranged, whatever the verdict was."""
        node: Node = kwargs["node"]
        for process in self.arranged:
            process.kill()
            process.wait_result(timeout=30, raise_on_timeout=False)
        survivors = [process for process in self.arranged if process.is_running()]
        self.arranged = []
        if survivors:
            log.error(
                "an arranged process survived teardown and is still "
                "listening; the next case reports it as an arrangement "
                "that stopped before it answered"
            )
        node.tools[Rm].remove_file(str(node.get_pure_path("/tmp/azl-http-origin.py")))

    @TestCaseMetadata(
        description=(
            "Supply credentials for server authentication to retrieve a known\n"
            "protected response.\n"
            "\n"
            "Corpus obligation: pkg:curl/authenticate-server-request\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        timeout=120,
        requirement=simple_requirement(supported_os=[CBLMariner]),
    )
    def verify_authenticate_server_request(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:curl/authenticate-server-request."""
        log.info("Verifying obligation pkg:curl/authenticate-server-request")
        result = node.execute(
            "curl --user azl:secret http://127.0.0.1:18080/auth",
            shell=False,
            expected_exit_code=0,
            expected_exit_code_failure_message="curl authentication request failed",
        )
        combined_output = f"{result.stdout}\n{result.stderr}"
        (
            assert_that(combined_output)
            .described_as("valid server credentials retrieve the protected response")
            .contains("welcome")
        )

    @TestCaseMetadata(
        description=(
            "Save a known response body to a caller-selected file instead of\n"
            "standard output.\n"
            "\n"
            "Corpus obligation: pkg:curl/download-to-named-file\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        timeout=120,
        requirement=simple_requirement(supported_os=[CBLMariner]),
    )
    def verify_download_to_named_file(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:curl/download-to-named-file."""
        log.info("Verifying obligation pkg:curl/download-to-named-file")
        scratch = node.get_pure_path(
            f"/tmp/lisa-curl-download-to-named-file-{node.name}"
        )
        node.tools[Mkdir].create_directory(str(scratch))
        try:
            destination = scratch / "named-response"
            output_result = node.execute(
                "curl --output named-response http://127.0.0.1:18080",
                cwd=scratch,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "curl failed to save the response to the named file"
                ),
            )
            saved_body = node.tools[Cat].read(str(destination))
            output_text = output_result.stdout + output_result.stderr
            (
                assert_that(saved_body)
                .described_as("named destination contains the response body")
                .is_equal_to("hello")
            )
            (
                assert_that(output_text)
                .described_as("response body is not written to standard output")
                .does_not_contain("hello")
            )
            contrast = node.execute(
                "curl http://127.0.0.1:18080",
                cwd=scratch,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "curl failed to return the response without an output file"
                ),
            )
            contrast_text = contrast.stdout + contrast.stderr
            (
                assert_that(contrast_text)
                .described_as("response body is available without a named output file")
                .contains("hello")
            )
        finally:
            node.tools[Rm].remove_directory(str(scratch))

    @TestCaseMetadata(
        description=(
            "Return a failure instead of an HTTP error body for a non-\n"
            "authentication error response.\n"
            "\n"
            "Corpus obligation: pkg:curl/fail-on-http-error\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        timeout=120,
        requirement=simple_requirement(supported_os=[CBLMariner]),
    )
    def verify_fail_on_http_error(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:curl/fail-on-http-error."""
        log.info("Verifying obligation pkg:curl/fail-on-http-error")
        failed_404 = node.execute(
            "curl --fail http://127.0.0.1:18080/status/404",
            expected_exit_code=22,
            expected_exit_code_failure_message=(
                "curl --fail did not return exit code 22 for HTTP 404"
            ),
        )
        failed_500 = node.execute(
            "curl --fail http://127.0.0.1:18080/status/500",
            expected_exit_code=22,
            expected_exit_code_failure_message=(
                "curl --fail did not return exit code 22 for HTTP 500"
            ),
        )
        assert_that(f"{failed_404.stdout}{failed_404.stderr}").described_as(
            "curl --fail suppresses the HTTP 404 response body"
        ).does_not_contain("status")
        assert_that(f"{failed_500.stdout}{failed_500.stderr}").described_as(
            "curl --fail suppresses the HTTP 500 response body"
        ).does_not_contain("status")
        plain_404 = node.execute(
            "curl http://127.0.0.1:18080/status/404",
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "curl without --fail did not return normally for HTTP 404"
            ),
        )
        plain_500 = node.execute(
            "curl http://127.0.0.1:18080/status/500",
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "curl without --fail did not return normally for HTTP 500"
            ),
        )
        assert_that(f"{plain_404.stdout}{plain_404.stderr}").described_as(
            "the HTTP 404 response body is observable without --fail"
        ).contains("status")
        assert_that(f"{plain_500.stdout}{plain_500.stderr}").described_as(
            "the HTTP 500 response body is observable without --fail"
        ).contains("status")

    @TestCaseMetadata(
        description=(
            "Follow a redirect response to retrieve the final resource.\n"
            "\n"
            "Corpus obligation: pkg:curl/follow-http-redirect\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        timeout=120,
        requirement=simple_requirement(supported_os=[CBLMariner]),
    )
    def verify_follow_http_redirect(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:curl/follow-http-redirect."""
        log.info("Verifying obligation pkg:curl/follow-http-redirect")
        result = node.execute(
            (
                "curl --silent --show-error --location --verbose "
                "--noproxy 127.0.0.1 http://127.0.0.1:18080/redirect"
            ),
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "curl did not follow the redirect successfully"
            ),
        )
        output = f"{result.stdout}\n{result.stderr}"
        request_lines = [
            line for line in output.splitlines() if line.startswith("> GET ")
        ]
        assert_that(request_lines).described_as(
            "curl follows the redirect with a second HTTP request"
        ).is_length(2)
        assert_that(output).described_as(
            "curl returns the arranged final response body"
        ).contains("hello")

    @TestCaseMetadata(
        description=(
            "Route a request through an explicitly specified controlled\n"
            "proxy.\n"
            "\n"
            "Corpus obligation: pkg:curl/request-through-proxy\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        timeout=120,
        requirement=simple_requirement(supported_os=[CBLMariner]),
    )
    def verify_request_through_proxy(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:curl/request-through-proxy."""
        log.info("Verifying obligation pkg:curl/request-through-proxy")
        result = node.execute(
            "curl --noproxy '' --verbose --proxy http://127.0.0.1:18080 "
            "http://127.0.0.1:18080",
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "curl should retrieve the origin response through the explicit proxy"
            ),
        )
        output = result.stdout + result.stderr
        assert_that(output).described_as(
            "explicit proxy receives the origin request"
        ).contains("Via: azl-origin")
        assert_that(output).described_as(
            "curl returns the origin response through the explicit proxy"
        ).contains("hello")

    @TestCaseMetadata(
        description=(
            "Resume a local partial destination from a range-capable remote\n"
            "resource.\n"
            "\n"
            "Corpus obligation: pkg:curl/resume-partial-download\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        timeout=120,
        requirement=simple_requirement(supported_os=[CBLMariner]),
    )
    def verify_resume_partial_download(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:curl/resume-partial-download."""
        log.info("Verifying obligation pkg:curl/resume-partial-download")
        workdir = node.get_pure_path(
            f"/tmp/lisa-curl-resume-partial-download-{node.name}"
        )
        destination = workdir / "destination"
        node.tools[Mkdir].create_directory(str(workdir))
        try:
            node.execute(
                (
                    "curl --fail --silent --show-error --range 0-9 "
                    "--output destination http://127.0.0.1:18080/range"
                ),
                cwd=workdir,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "curl did not create the partial download"
                ),
            )
            partial = node.tools[Cat].read(str(destination))
            assert_that(partial).described_as(
                "partial destination contains the known remote prefix"
            ).is_equal_to("0123456789")
            assert_that(partial).described_as(
                "partial destination is incomplete before resume"
            ).is_not_equal_to("0123456789abcdefghijklmnopqrstuvwxyz")

            node.execute(
                (
                    "curl --fail --silent --show-error --continue-at - "
                    "--output destination http://127.0.0.1:18080/range"
                ),
                cwd=workdir,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "curl did not resume the partial download"
                ),
            )
            completed = node.tools[Cat].read(str(destination), force_run=True)
            assert_that(completed).described_as(
                "resumed destination equals the known remote content"
            ).is_equal_to("0123456789abcdefghijklmnopqrstuvwxyz")
        finally:
            node.tools[Rm].remove_directory(str(workdir))

    @TestCaseMetadata(
        description=(
            "Request and display HTTP response headers without transferring\n"
            "the body.\n"
            "\n"
            "Corpus obligation: pkg:curl/retrieve-response-headers\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        timeout=120,
        requirement=simple_requirement(supported_os=[CBLMariner]),
    )
    def verify_retrieve_response_headers(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:curl/retrieve-response-headers."""
        log.info("Verifying obligation pkg:curl/retrieve-response-headers")
        head_result = node.execute(
            "curl --verbose --head http://127.0.0.1:18080",
            expected_exit_code=0,
            expected_exit_code_failure_message="curl HEAD request should succeed",
        )
        head_output = head_result.stdout + head_result.stderr
        assert_that(head_output).described_as(
            "curl sends the HTTP HEAD method"
        ).contains("HEAD / HTTP/")
        assert_that(head_output).described_as(
            "HEAD output displays the known response header"
        ).contains("X-Origin: azl")
        assert_that(head_output).described_as(
            "HEAD output omits the response body"
        ).does_not_contain("hello")
        get_result = node.execute(
            "curl http://127.0.0.1:18080",
            expected_exit_code=0,
            expected_exit_code_failure_message="curl GET contrast should succeed",
        )
        get_output = get_result.stdout + get_result.stderr
        assert_that(get_output).described_as(
            "the response body omitted by HEAD is available with GET"
        ).contains("hello")

    @TestCaseMetadata(
        description=(
            "Retry a transient HTTP failure and honor its Retry-After delay\n"
            "before success.\n"
            "\n"
            "Corpus obligation: pkg:curl/retry-transient-http-response\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        timeout=120,
        requirement=simple_requirement(supported_os=[CBLMariner]),
    )
    def verify_retry_transient_http_response(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:curl/retry-transient-http-response."""
        log.info("Verifying obligation pkg:curl/retry-transient-http-response")
        result = node.execute(
            ("curl --verbose --retry 1 http://127.0.0.1:18080/flaky"),
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "curl did not recover from the transient HTTP response"
            ),
        )
        output = f"{result.stdout}\n{result.stderr}"
        status_lines = [
            line
            for line in output.splitlines()
            if line.startswith("< HTTP/") and " 429" in line
        ]
        assert_that(status_lines).described_as(
            "curl observes the single transient HTTP 429 response"
        ).is_length(1)
        retry_headers = [
            line for line in output.splitlines() if line.startswith("< Retry-After:")
        ]
        assert_that(retry_headers).described_as(
            "the transient response supplies the Retry-After instruction"
        ).is_not_empty()
        request_lines = [
            line
            for line in output.splitlines()
            if line.startswith("> GET /flaky HTTP/")
        ]
        assert_that(request_lines).described_as(
            "curl retries the request after the transient response"
        ).is_length(2)
        assert_that(output).described_as(
            "curl returns the successful response after retrying"
        ).contains("recovered")

    @TestCaseMetadata(
        description=(
            "Send specified JSON text as an HTTP POST request with JSON media\n"
            "headers.\n"
            "\n"
            "Corpus obligation: pkg:curl/send-json-post\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        timeout=120,
        requirement=simple_requirement(supported_os=[CBLMariner]),
    )
    def verify_send_json_post(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:curl/send-json-post."""
        log.info("Verifying obligation pkg:curl/send-json-post")
        result = node.execute(
            'curl --verbose --json \'{"message":"azure-linux"}\' '
            "http://127.0.0.1:18080/echo",
            expected_exit_code=0,
            expected_exit_code_failure_message="curl failed to send the JSON request",
        )
        output = f"{result.stdout}\n{result.stderr}"
        assert_that(output).described_as(
            "curl sends the request as HTTP POST"
        ).contains("POST /echo HTTP/")
        assert_that(output).described_as(
            "curl sends the JSON Content-Type header"
        ).contains("Content-Type: application/json")
        assert_that(output).described_as("curl sends the JSON Accept header").contains(
            "Accept: application/json"
        )
        assert_that(output).described_as(
            "the endpoint receives and echoes the specified JSON body"
        ).contains('{"message":"azure-linux"}')

    @TestCaseMetadata(
        description=(
            "Submit text and file parts in an HTTP multipart form request.\n"
            "\n"
            "Corpus obligation: pkg:curl/submit-multipart-form\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        timeout=120,
        requirement=simple_requirement(supported_os=[CBLMariner]),
    )
    def verify_submit_multipart_form(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:curl/submit-multipart-form."""
        log.info("Verifying obligation pkg:curl/submit-multipart-form")
        scratch = node.get_pure_path(
            f"/tmp/lisa-curl-submit-multipart-form-{node.name}"
        )
        node.tools[Mkdir].create_directory(str(scratch))
        try:
            fixture = scratch / "fixture.txt"
            node.tools[Tee].write_to_file(
                "FILE_PART_MARKER", fixture, append=False, sudo=False
            )
            result = node.execute(
                (
                    "curl --verbose --form text=TEXT_PART_MARKER "
                    "--form file=@fixture.txt http://127.0.0.1:18080/echo"
                ),
                cwd=scratch,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "curl failed to submit the multipart form"
                ),
            )
            output = f"{result.stdout}\n{result.stderr}"
            assert_that(output).described_as(
                "multipart form is submitted with an HTTP POST"
            ).contains("POST /echo HTTP/")
            assert_that(output).described_as(
                "request declares a multipart form body"
            ).contains("Content-Type: multipart/form-data;")
            assert_that(output).described_as(
                "multipart body contains the named text part"
            ).contains('name="text"')
            assert_that(output).described_as(
                "multipart body contains the text part value"
            ).contains("TEXT_PART_MARKER")
            assert_that(output).described_as(
                "multipart body contains the named file part"
            ).contains('name="file"; filename="fixture.txt"')
            assert_that(output).described_as(
                "multipart body contains the file fixture value"
            ).contains("FILE_PART_MARKER")
        finally:
            node.tools[Rm].remove_directory(str(scratch))

    @TestCaseMetadata(
        description=(
            "Upload known local bytes to an HTTP PUT endpoint.\n"
            "\n"
            "Corpus obligation: pkg:curl/upload-local-file\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        timeout=120,
        requirement=simple_requirement(supported_os=[CBLMariner]),
    )
    def verify_upload_local_file(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:curl/upload-local-file."""
        log.info("Verifying obligation pkg:curl/upload-local-file")
        scratch = node.get_pure_path(f"/tmp/lisa-curl-upload-local-file-{node.name}")
        node.tools[Mkdir].create_directory(str(scratch))
        try:
            payload = "curl-upload-local-file-marker"
            upload = scratch / "upload.txt"
            receipt = scratch / "receipt.txt"
            node.tools[Tee].write_to_file(
                value=payload,
                file=upload,
                append=False,
                sudo=False,
            )
            result = node.execute(
                (
                    "curl --verbose --upload-file upload.txt "
                    "--output receipt.txt http://127.0.0.1:18080/echo"
                ),
                cwd=scratch,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "curl failed to upload the local file to the PUT endpoint"
                ),
            )
            transcript = f"{result.stdout}{result.stderr}"
            assert_that(transcript).described_as(
                "curl sends the upload to the endpoint with HTTP PUT"
            ).contains("PUT /echo HTTP/")
            source_content = node.tools[Cat].read(str(upload))
            receipt_content = node.tools[Cat].read(str(receipt))
            source_size = node.tools[Stat].get_total_size(str(upload))
            receipt_size = node.tools[Stat].get_total_size(str(receipt))
            assert_that(source_content).described_as(
                "the controlled local file contains the known upload payload"
            ).is_equal_to(payload)
            assert_that(source_size).described_as(
                "the controlled local file includes its known terminating newline"
            ).is_equal_to(len(payload) + 1)
            assert_that(receipt_content).described_as(
                "the endpoint receives the local file content without alteration"
            ).is_equal_to(source_content)
            assert_that(receipt_size).described_as(
                "the endpoint receives exactly the complete local file byte count"
            ).is_equal_to(source_size)
        finally:
            node.tools[Rm].remove_directory(str(scratch))
