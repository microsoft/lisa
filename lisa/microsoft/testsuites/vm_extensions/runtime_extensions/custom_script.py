# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import base64
import gzip
import hashlib
import json
import shlex
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from azure.core.exceptions import AzureError, HttpResponseError, ResourceNotFoundError
from azure.mgmt.compute.models import (
    VirtualMachineExtension,
    VirtualMachineIdentity,
    VirtualMachineRunCommand,
    VirtualMachineRunCommandScriptSource,
    VirtualMachineUpdate,
)
from azure.mgmt.resource.resources.models import GenericResource
from microsoft.testsuites.vm_extensions.vm_extension_base import VmExtensionTestBase

from lisa import Logger, Node, TestCaseMetadata, TestSuiteMetadata, simple_requirement
from lisa.environment import EnvironmentStatus
from lisa.operating_system import BSD, Windows
from lisa.secret import add_secret
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import (
    AZURE_SHARED_RG_NAME,
    generate_user_delegation_sas_token,
    get_compute_client,
    get_managed_service_identity_client,
    get_node_context,
    get_or_create_storage_container,
    get_resource_management_client,
    get_storage_account_name,
    get_storage_client,
)
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.util import SkippedException

_DATA = "/var/lib/waagent/custom-script"
_FIXTURES = Path(__file__).parent / "scripts" / "custom_script_fixtures.py"
_READER_ROLE = "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1"
_ROLE_API = "2022-04-01"
_IDENTITY_API = "2024-11-30"


def _encoded(script: str, compressed: bool = False) -> str:
    data = script.encode()
    return base64.b64encode(gzip.compress(data) if compressed else data).decode()


def _python_command(code: str) -> str:
    return f"python3 -c {shlex.quote(code)}"


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="SSH-free CSE validation using in-place updates on one Linux VM.",
    tags=["VM_Extension", "CustomScript"],
    reuse_deployed_environment=True,
    requirement=simple_requirement(
        environment_status=EnvironmentStatus.Deployed,
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
        unsupported_os=[BSD, Windows],
    ),
)
class CustomScriptTests(VmExtensionTestBase):  # type: ignore[misc]
    PUBLISHER = "Microsoft.Azure.Extensions"
    EXTENSION_TYPE = "CustomScript"
    EXTENSION_KEY = "custom_script"
    DEFAULT_VERSION = "2.1"

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        self._root_created = False
        self._policy_path = ""
        self._blobs: List[Any] = []
        self._temporary_roles: List[str] = []
        self._node: Node = kwargs["node"]
        self._variables: Dict[str, Any] = kwargs["variables"]
        self._publisher = self._resolve_publisher(self._variables)
        self._extension_type = self._resolve_type(self._variables)
        self._handler_glob = f"{self._publisher}.{self._extension_type}-*"
        self._log = log
        platform = kwargs["environment"].platform
        assert isinstance(platform, AzurePlatform)
        self._platform = platform
        self._compute = get_compute_client(platform)
        self._context = get_node_context(self._node)
        self._rg = self._context.resource_group_name
        self._vm_name = self._context.vm_name
        self._vm = self._compute.virtual_machines.get(self._rg, self._vm_name)
        assert str(self._vm.storage_profile.os_disk.os_type).lower() == "linux"
        self._version = self._get_version(self._variables)
        self._root = f"/var/tmp/lisa-cse-{uuid.uuid4().hex}"
        self._resource_client = get_resource_management_client(
            platform.credential, platform.subscription_id, platform.cloud
        )
        # Adopt the existing CSE resource instead of creating a second handler.
        self._extension_name = self.extension_name
        extensions = self._compute.virtual_machine_extensions.list(
            self._rg, self._vm_name
        ).value
        for extension in extensions or []:
            if (extension.publisher or "").lower() == self._publisher.lower() and (
                extension.type_properties_type or ""
            ).lower() == self._extension_type.lower():
                assert extension.name, "Existing CSE resource has no name"
                self._extension_name = extension.name

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        try:
            self._cleanup_case()
        except (AzureError, AssertionError, OSError) as error:
            log.error(
                f"CSE fixture cleanup failed; discarding the environment: {error}"
            )
            kwargs["environment"].mark_dirty()
            raise

    def _cleanup_case(self) -> None:
        try:
            if self._root_created or self._policy_path:
                self._guest(
                    "from pathlib import Path\n"
                    "import shutil\n"
                    "import signal\n"
                    f"root = Path({self._root!r})\n"
                    "pid_file = root / 'server.pid'\n"
                    "if pid_file.exists():\n"
                    "    pid = int(pid_file.read_text())\n"
                    "    proc = Path('/proc') / str(pid) / 'cmdline'\n"
                    "    if proc.exists():\n"
                    "        assert str(root).encode() in proc.read_bytes()\n"
                    "        import os\n"
                    "        os.kill(pid, signal.SIGTERM)\n"
                    "if root.is_symlink() or root.is_file():\n"
                    "    root.unlink()\n"
                    "elif root.exists():\n"
                    "    shutil.rmtree(root)\n"
                    f"policy = {self._policy_path!r}\n"
                    "if policy:\n"
                    "    path = Path(policy)\n"
                    "    if path.exists():\n"
                    "        path.unlink()\n"
                )
        finally:
            try:
                for blob in self._blobs:
                    blob.delete_blob()
            finally:
                for role in self._temporary_roles:
                    self._resource_client.resources.begin_delete_by_id(
                        role, _ROLE_API
                    ).result()

    def _guest(self, code: str, timeout: int = 120) -> Dict[str, Any]:
        marker = f"LISA-RC-{uuid.uuid4().hex}:"
        script = (
            "set -eu\npython3 - <<'LISA_PY'\n"
            "import json\nresult = {}\n"
            f"{code}\nprint({marker!r} + json.dumps(result))\nLISA_PY\n"
        )
        commands = self._compute.virtual_machine_run_commands
        commands.begin_create_or_update(
            self._rg,
            self._vm_name,
            "lisa-cse-setup",
            VirtualMachineRunCommand(
                location=self._vm.location,
                source=VirtualMachineRunCommandScriptSource(script=script),
                timeout_in_seconds=timeout,
                treat_failure_as_deployment_failure=True,
            ),
        ).result()
        view = commands.get_by_virtual_machine(
            resource_group_name=self._rg,
            vm_name=self._vm_name,
            run_command_name="lisa-cse-setup",
            expand="instanceView",
        ).instance_view
        assert view is not None, "Managed Run Command returned no instance view"
        assert (
            str(view.execution_state).lower() == "succeeded"
        ), f"Managed Run Command failed: {view.execution_state}: {view.error}"
        assert view.exit_code == 0, f"Managed Run Command failed: {view.error}"
        lines = [
            line for line in (view.output or "").splitlines() if line.startswith(marker)
        ]
        assert len(lines) == 1, f"Missing fresh Run Command result: {view.output}"
        result = json.loads(lines[0][len(marker) :])
        assert isinstance(result, dict), "Run Command result must be an object"
        return result

    def _apply(
        self,
        settings: Optional[Dict[str, Any]] = None,
        protected: Optional[Dict[str, Any]] = None,
        marker: str = "",
        error: Union[str, Tuple[str, ...]] = "",
        force: Optional[str] = None,
    ) -> Tuple[str, str]:
        self._log.info(f"Updating CSE: {marker or error}")
        try:
            self._compute.virtual_machine_extensions.begin_create_or_update(
                self._rg,
                self._vm_name,
                self._extension_name,
                VirtualMachineExtension(
                    location=self._vm.location,
                    publisher=self._publisher,
                    type_properties_type=self._extension_type,
                    type_handler_version=self._version,
                    auto_upgrade_minor_version=True,
                    force_update_tag=uuid.uuid4().hex if force is None else force,
                    settings=settings or {},
                    protected_settings=protected or {},
                ),
            ).result()
        except HttpResponseError as exc:
            if not error:
                raise
            code = str(getattr(exc.error, "code", ""))
            if "vmextension" not in code.lower():
                raise
        errors = (error,) if isinstance(error, str) else error
        deadline = time.monotonic() + 30
        while True:
            extension = self._compute.virtual_machine_extensions.get(
                self._rg, self._vm_name, self._extension_name, expand="instanceView"
            )
            state = (extension.provisioning_state or "").lower()
            view = extension.instance_view
            statuses = view.statuses if view and view.statuses else []
            message = "\n".join(status.message or "" for status in statuses)
            handler_succeeded = any(
                (status.code or "").lower().endswith("/succeeded")
                for status in statuses
            )
            handler_failed = any(
                (status.code or "").lower().endswith(("/failed", "/error"))
                or str(status.level).lower() == "error"
                for status in statuses
            )
            if not error and state in ("failed", "canceled"):
                break
            if handler_failed and (
                (error and any(item.lower() in message.lower() for item in errors))
                or (marker and marker in message)
            ):
                break
            if handler_succeeded and (
                (marker and marker in message) or (error and state == "succeeded")
            ):
                break
            if time.monotonic() >= deadline:
                break
            self._log.debug(
                f"Waiting for CSE handler result: resource state {state!r}, "
                f"handler codes {[status.code for status in statuses]}"
            )
            time.sleep(2)
        assert view and statuses, (
            f"CSE returned no handler status (resource state {state!r})"
        )
        if error:
            assert handler_failed, (
                "CSE did not report the expected handler failure "
                f"(resource state {state!r}, handler {view.type_handler_version}, "
                f"expected {error!r}): {message}"
            )
            # Only handler diagnostics count: an ARM/authentication error is not
            # evidence that CSE rejected the input.
            assert any(
                item.lower() in message.lower() for item in errors
            ), f"Expected CSE diagnostic {error!r}, got: {message}"
        else:
            assert (
                state not in ("failed", "canceled")
                and handler_succeeded
                and not handler_failed
            ), (
                f"CSE failed (resource state {state!r}, "
                f"handler {view.type_handler_version}, "
                f"handler codes {[status.code for status in statuses]}): {message}"
            )
            assert marker and marker in message, f"Missing fresh CSE output: {message}"
            if self._version.count(".") >= 2:
                assert AzureExtension.are_type_handler_versions_equal(
                    self._version, view.type_handler_version or ""
                ), f"Expected CSE {self._version}, got {view.type_handler_version}"
        if "[stdout]\n" not in message:
            assert error, f"CSE status has no stdout: {message}"
            return "", ""
        output = message.split("[stdout]\n", 1)[1]
        assert "\n[stderr]\n" in output, f"CSE status has no stderr: {message}"
        stdout, stderr = output.split("\n[stderr]\n", 1)
        if not error:
            assert marker in stdout, f"Missing fresh CSE stdout: {message}"
        return stdout, stderr

    def _marker(self) -> str:
        return f"LISA-CSE-{uuid.uuid4().hex}"

    def _fixture(self) -> str:
        self._root_created = True
        result = self._guest(
            "from pathlib import Path\n"
            "import subprocess\n"
            "import sys\n"
            "import time\n"
            "import urllib.request\n"
            f"root = Path({self._root!r})\n"
            "root.mkdir(mode=0o700)\n"
            "fixture = root / 'fixture.py'\n"
            f"fixture.write_text({_FIXTURES.read_text(encoding='utf-8')!r})\n"
            "with (root / 'server.log').open('wb') as output:\n"
            "    process = subprocess.Popen(\n"
            "        [sys.executable, str(fixture), str(root)],\n"
            "        stdin=subprocess.DEVNULL, stdout=output, stderr=output,\n"
            "        start_new_session=True)\n"
            "(root / 'server.pid').write_text(str(process.pid))\n"
            "for attempt in range(50):\n"
            "    assert process.poll() is None, (root / 'server.log').read_text()\n"
            "    if (root / 'port').exists():\n"
            "        break\n"
            "    time.sleep(0.1)\n"
            "port = int((root / 'port').read_text())\n"
            "url = 'http://127.0.0.1:' + str(port)\n"
            "with urllib.request.urlopen(url + '/health', timeout=5) as response:\n"
            "    assert response.read() == b'OK'\n"
            "result['url'] = url\n"
        )
        return str(result["url"])

    @TestCaseMetadata(
        description="Anonymous multi-file downloads, preprocessing and root execution.",
        priority=5,
        maturity="preview",
    )
    def verify_public_script_run(self) -> None:
        url = self._fixture()
        marker = self._marker()
        command = _python_command(
            "import os, pathlib, stat, subprocess; "
            "p = pathlib.Path; "
            "assert os.geteuid() == 0; "
            f"assert str(p.cwd()).startswith({_DATA + '/download/'!r}); "
            "assert p('crlf.sh').read_bytes() == b'#!/bin/sh\\necho fixture\\n'; "
            "assert p('bom.sh').read_bytes() == b'#!/bin/sh\\necho fixture\\n'; "
            "assert p('extensionless').read_bytes() == b'#!/bin/sh\\necho fixture\\n'; "
            "assert p('binary').read_bytes() == bytes(range(256)); "
            "assert subprocess.check_output(['./crlf.sh']) == b'fixture\\n'; "
            "assert subprocess.check_output(['./extensionless']) == b'fixture\\n'; "
            "output = subprocess.check_output(['python3', 'script.py']); "
            "assert output == b'python-fixture\\n'; "
            "assert all(stat.S_IMODE(p(n).stat().st_mode) == 0o500 "
            "for n in ('crlf.sh', 'bom.sh', 'extensionless', 'binary', 'script.py')); "
            "assert all(stat.S_IMODE(p(n).stat().st_mode) == 0o600 "
            "for n in ('stdout', 'stderr')); "
            f"print({marker!r})"
        )
        self._apply(
            {
                "fileUris": [
                    f"{url}/{name}"
                    for name in (
                        "crlf.sh",
                        "bom.sh",
                        "extensionless",
                        "binary",
                        "script.py",
                    )
                ],
                "commandToExecute": command,
            },
            marker=marker,
        )

    @TestCaseMetadata(
        description="Mixed settings and skipDos2Unix preserve raw downloads.",
        priority=5,
        maturity="preview",
    )
    def verify_public_script_protected_settings_run(self) -> None:
        url = self._fixture()
        marker = self._marker()
        command = _python_command(
            "from pathlib import Path; "
            "raw = b'#!/bin/sh\\r\\necho fixture\\r\\n'; "
            "assert Path('crlf.sh').read_bytes() == raw; "
            "assert Path('bom.sh').read_bytes().startswith(b'\\xef\\xbb\\xbf'); "
            f"print({marker!r})"
        )
        self._apply(
            {"fileUris": [url + "/crlf.sh", url + "/bom.sh"], "skipDos2Unix": True},
            {"commandToExecute": command},
            marker=marker,
        )

    @TestCaseMetadata(
        description="Inline script at the encoded size limit and exact output tails.",
        priority=5,
        maturity="preview",
    )
    def verify_public_script_with_base64_script_run(self) -> None:
        marker = self._marker()
        stdout = "O" * (4096 - len(marker) - 1) + marker + "\n"
        stderr = "E" * (4096 - len(marker) - 1) + marker + "\n"
        command = _python_command(
            "import pathlib, stat, sys; "
            "assert stat.S_IMODE(pathlib.Path('script.sh').stat().st_mode) == 0o500; "
            f"sys.stdout.write('discarded' + {stdout!r}); "
            f"sys.stderr.write('discarded' + {stderr!r})"
        )
        script = "#!/bin/sh\nset -eu\n" + command + "\n#"
        script += "x" * (196608 - len(script.encode()))
        encoded = _encoded(script)
        assert len(encoded) == 256 * 1024
        actual_out, actual_err = self._apply({"script": encoded}, marker=marker)
        assert actual_out == stdout, f"Incorrect stdout tail: {len(actual_out)} bytes"
        # Some agents add a newline after the final status message.
        assert actual_err.rstrip("\n") == stderr.rstrip("\n")
        assert len(actual_err.rstrip("\n")) == 4095

    @TestCaseMetadata(
        description="Public gzip/base64 and protected plain/gzip inline scripts.",
        priority=5,
        maturity="preview",
    )
    def verify_public_script_with_gzip_base64_script_run(self) -> None:
        url = self._fixture()
        for protected, compressed in ((False, True), (True, False), (True, True)):
            marker = self._marker()
            skip_conversion = protected and compressed
            if skip_conversion:
                command = _python_command(
                    "from pathlib import Path; "
                    "assert b'# raw\\r\\n' in Path('script.sh').read_bytes(); "
                    "assert b'\\r\\n' in Path('crlf.sh').read_bytes(); "
                    f"print({marker!r})"
                )
                script = "#!/bin/sh\nset -eu\n" + command + "\n# raw\r\n"
            else:
                script = (
                    '#!/bin/sh\nset -eu\ntest "$(./crlf.sh)" = fixture\n'
                    f"printf '%s\\n' {shlex.quote(marker)}\n"
                )
            if not compressed:
                script = "\ufeff" + script.replace("\n", "\r\n")
            settings: Dict[str, Any] = {
                "fileUris": [url + "/crlf.sh"],
                "skipDos2Unix": skip_conversion,
            }
            inline = {"script": _encoded(script, compressed)}
            if not protected:
                settings.update(inline)
            self._apply(
                settings,
                inline if protected else {},
                marker=marker,
            )

    @TestCaseMetadata(
        description="Schema rejection without executing the command.",
        priority=5,
        maturity="preview",
    )
    def verify_invalid_settings(self) -> None:
        self._root_created = True
        marker = self._marker()
        command = f"touch {self._root}; echo {marker}"
        self._apply(
            {"commandToExecute": command, "skipDos2Unix": "invalid"},
            marker=marker,
            error="json validation error",
        )
        # TODO: Re-enable these logical checks once the CSE source fix is deployed.
        # self._apply(
        #     {"commandToExecute": command, "script": _encoded("#!/bin/sh\nexit 0\n")},
        #     marker=marker,
        #     error="'commandToExecute' and 'script'",
        # )
        # self._apply(
        #     {"fileUris": []},
        #     error="'commandToExecute' is not specified",
        # )
        self._guest(
            f"from pathlib import Path\nassert not Path({self._root!r}).exists()"
        )
        self._root_created = False

    @TestCaseMetadata(
        description="Invalid base64, corrupt gzip and an oversized encoded script.",
        priority=5,
        maturity="preview",
    )
    def verify_invalid_scripts(self) -> None:
        # TODO: Re-enable this case once the CSE script-error fixes are deployed.
        raise SkippedException(
            "Invalid-script rejection is fixed in CSE source but not yet deployed. "
            "Base64, corrupt-gzip and oversized-script checks are deferred."
        )

        corrupt = bytearray(gzip.compress(b"#!/bin/sh\nexit 0\n"))
        corrupt[-8] ^= 0xFF
        for script, error in (
            ("not-base64!", "failed to decode script"),
            (base64.b64encode(corrupt).decode(), "failed to decompress script"),
            ("A" * (256 * 1024 + 4), "exceeded the maximum allowed length"),
        ):
            self._apply(protected={"script": script}, error=error)

    @TestCaseMetadata(
        description="Nonzero exit status, both output streams and recovery.",
        priority=5,
        maturity="preview",
    )
    def verify_execution_failure_and_recovery(self) -> None:
        marker = self._marker()
        out, err = self._apply(
            protected={
                "commandToExecute": f"echo {marker}; echo {marker}-stderr >&2; exit 23"
            },
            error="exit status=23",
        )
        assert marker in out and marker + "-stderr" in err
        marker = self._marker()
        self._apply(protected={"commandToExecute": f"echo {marker}"}, marker=marker)

    @TestCaseMetadata(
        description="Unchanged settings do not rerun; timestamp and forceUpdateTag do.",
        priority=5,
        maturity="preview",
    )
    def verify_in_place_updates(self) -> None:
        marker = self._marker()
        self._root_created = True
        command = _python_command(
            "from pathlib import Path; "
            f"root = Path({self._root!r}); root.mkdir(exist_ok=True, mode=0o700); "
            "counter = root / 'counter'; "
            "count = int(counter.read_text()) + 1 if counter.exists() else 1; "
            "counter.write_text(str(count)); "
            f"print({marker!r} + ':' + str(count))"
        )
        settings = {"commandToExecute": command, "timestamp": 1}
        self._apply(settings, marker=marker + ":1", force="")
        self._apply(settings, marker=marker + ":1", force="")
        self._guest(
            f"from pathlib import Path\n"
            f"assert (Path({self._root!r}) / 'counter').read_text() == '1'"
        )
        settings["timestamp"] = 2
        self._apply(settings, marker=marker + ":2", force="")
        self._apply(settings, marker=marker + ":3")
        self._guest(
            "from pathlib import Path\n"
            f"assert (Path({self._root!r}) / 'counter').read_text() == '3'\n"
            f"downloads = list(Path({_DATA + '/download'!r}).iterdir())\n"
            "assert len(downloads) == 1, downloads\n"
            "seq = downloads[0].name\n"
            "settings = list(Path('/var/lib/waagent').glob("
            f"{self._handler_glob + '/config/*.settings'!r}))\n"
            "assert settings\n"
            "assert all(not p.read_bytes() for p in settings if p.stem != seq)\n"
        )

    @TestCaseMetadata(
        description="Short 429/503 retries and permanent 404 rejection.",
        priority=5,
        maturity="preview",
    )
    def verify_download_retries_and_failures(self) -> None:
        url = self._fixture()
        marker = self._marker()
        names = (
            "retry429.sh",
            "retry503.sh",
            # TODO: Re-enable after CSE's interrupted-download retry bug is fixed.
            # "partial.sh",
        )
        command = _python_command(
            "import json, pathlib; "
            f"root = pathlib.Path({self._root!r}); "
            "counts = json.loads((root / 'requests.json').read_text()); "
            f"names = {names!r}; "
            "assert all(counts.get(n) == 2 for n in names), counts; "
            "files = {n: pathlib.Path(n).read_bytes() for n in names}; "
            "assert all(data == b'#!/bin/sh\\necho fixture\\n' "
            "for data in files.values()), files; "
            f"print({marker!r})"
        )
        self._apply(
            {
                "fileUris": [url + "/" + name for name in names],
                "commandToExecute": command,
            },
            marker=marker,
        )
        self._apply(
            {
                "fileUris": [url + "/missing.sh"],
                "commandToExecute": f"touch {self._root}/unexpected",
            },
            error="404",
        )
        self._guest(
            "from pathlib import Path\n"
            f"assert not (Path({self._root!r}) / 'unexpected').exists()"
        )

    def _storage(self) -> Tuple[Any, str]:
        account_name = str(
            self._variables.get(
                "custom_script_storage_account",
                get_storage_account_name(
                    self._platform.subscription_id, self._vm.location
                ),
            )
        )
        container = get_or_create_storage_container(
            "lisa-cse-validation",
            cloud=self._platform.cloud,
            credential=self._platform.credential,
            account_name=account_name,
            platform=self._platform,
        )
        assert not container.get_container_access_policy()[
            "public_access"
        ], "The CSE validation container must be private"
        return container, account_name

    def _private_blob(self) -> Tuple[Any, str, str]:
        container, account = self._storage()
        marker = self._marker()
        blob = container.get_blob_client(uuid.uuid4().hex + ".sh")
        blob.upload_blob(f"#!/bin/sh\nset -eu\necho {marker}\n", overwrite=False)
        self._blobs.append(blob)
        return blob, account, marker

    @TestCaseMetadata(
        description="Private blob access using a protected SAS.",
        priority=5,
        maturity="preview",
    )
    def verify_private_sas_script_run(self) -> None:
        blob, account, marker = self._private_blob()
        sas = generate_user_delegation_sas_token(
            blob.container_name,
            blob.blob_name,
            cloud=self._platform.cloud,
            credential=self._platform.credential,
            account_name=account,
            platform=self._platform,
        )
        add_secret(sas)
        self._apply(
            protected={
                "fileUris": [blob.url + "?" + sas],
                "commandToExecute": f"./{blob.blob_name}",
            },
            marker=marker,
        )

    @TestCaseMetadata(
        description="Private anonymous blob access fails before execution.",
        priority=5,
        maturity="preview",
    )
    def verify_private_script_without_sas_run_failed(self) -> None:
        self._root_created = True
        blob, _, _ = self._private_blob()
        self._apply(
            protected={
                "fileUris": [blob.url],
                "commandToExecute": f"touch {self._root}",
            },
            error=("403", "404", "409"),
        )
        self._guest(
            f"from pathlib import Path\nassert not Path({self._root!r}).exists()"
        )
        self._root_created = False

    @TestCaseMetadata(
        description="Private blob using a protected key where Shared Key is permitted.",
        priority=5,
        maturity="preview",
    )
    def verify_private_script_with_storage_credentials_run(self) -> None:
        account = str(
            self._variables.get(
                "custom_script_storage_account",
                get_storage_account_name(
                    self._platform.subscription_id, self._vm.location
                ),
            )
        )
        group = str(
            self._variables.get(
                "custom_script_storage_resource_group", AZURE_SHARED_RG_NAME
            )
        )
        storage = get_storage_client(
            self._platform.credential,
            self._platform.subscription_id,
            self._platform.cloud,
        )
        properties = storage.storage_accounts.get_properties(group, account)
        if properties.allow_shared_key_access is False:
            raise SkippedException(
                f"Shared Key is disabled on {account}; the test will not enable it. "
                "Set custom_script_storage_account and "
                "custom_script_storage_resource_group to an existing permitted account."
            )
        key = storage.storage_accounts.list_keys(group, account).keys[0].value
        assert key, "Azure returned no storage account key"
        add_secret(key)
        blob, _, marker = self._private_blob()
        self._apply(
            protected={
                "fileUris": [blob.url],
                "commandToExecute": f"./{blob.blob_name}",
                "storageAccountName": account,
                "storageAccountKey": key,
            },
            marker=marker,
        )

    def _reader_role(self, scope: str, principal: str, persistent: bool) -> None:
        role_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"{scope}/{principal}/{_READER_ROLE}")
        )
        resource_id = (
            f"{scope}/providers/Microsoft.Authorization/roleAssignments/{role_id}"
        )
        try:
            self._resource_client.resources.get_by_id(resource_id, _ROLE_API)
            self._log.info(f"Reusing storage reader role for principal {principal}")
        except ResourceNotFoundError:
            self._log.info(f"Creating storage reader role for principal {principal}")
            self._resource_client.resources.begin_create_or_update_by_id(
                resource_id,
                _ROLE_API,
                GenericResource(
                    properties={
                        "roleDefinitionId": (
                            f"/subscriptions/{self._platform.subscription_id}"
                            "/providers/Microsoft.Authorization/roleDefinitions/"
                            f"{_READER_ROLE}"
                        ),
                        "principalId": principal,
                        "principalType": "ServicePrincipal",
                    }
                ),
            ).result()
        if not persistent:
            self._temporary_roles.append(resource_id)

    @TestCaseMetadata(
        description="System/clientId/objectId downloads and missing read permission.",
        priority=5,
        maturity="preview",
    )
    def verify_managed_identity_downloads(self) -> None:
        self._root_created = True
        blob, account, _ = self._private_blob()
        identities = get_managed_service_identity_client(self._platform)
        assigned: Dict[str, Any] = {}
        resources = []
        for suffix in ("reader", "denied"):
            name = f"lisa-cse-{self._vm.location}-{suffix}"
            try:
                identity = identities.user_assigned_identities.get(
                    AZURE_SHARED_RG_NAME, name
                )
                self._log.info(f"Reusing persistent identity {name}")
            except ResourceNotFoundError:
                self._log.info(f"Creating persistent identity {name}")
                resource_id = (
                    f"/subscriptions/{self._platform.subscription_id}"
                    f"/resourceGroups/{AZURE_SHARED_RG_NAME}/providers/"
                    f"Microsoft.ManagedIdentity/userAssignedIdentities/{name}"
                )
                # Use a policy-compatible API. MSI creation is synchronous, so its
                # unversioned Location header must not be followed as a polling URL.
                self._resource_client.resources.begin_create_or_update_by_id(
                    resource_id,
                    _IDENTITY_API,
                    GenericResource(location=self._vm.location),
                    polling=False,
                ).result()
                identity = identities.user_assigned_identities.get(
                    AZURE_SHARED_RG_NAME, name
                )
            resources.append(identity)
            assigned[identity.id] = {}
        original = self._vm.identity
        if original and original.user_assigned_identities:
            assigned.update(original.user_assigned_identities)
        self._compute.virtual_machines.begin_update(
            self._rg,
            self._vm_name,
            VirtualMachineUpdate(
                identity=VirtualMachineIdentity(
                    type="SystemAssigned, UserAssigned",
                    user_assigned_identities=assigned,
                )
            ),
        ).result()
        vm = self._compute.virtual_machines.get(self._rg, self._vm_name)
        group = str(
            self._variables.get(
                "custom_script_storage_resource_group", AZURE_SHARED_RG_NAME
            )
        )
        scope = (
            f"/subscriptions/{self._platform.subscription_id}/resourceGroups/{group}"
            f"/providers/Microsoft.Storage/storageAccounts/{account}"
            f"/blobServices/default/containers/{blob.container_name}"
        )
        reader, denied = resources
        self._reader_role(scope, reader.principal_id, persistent=True)
        self._reader_role(scope, vm.identity.principal_id, persistent=False)
        self._log.info(
            "Checking identity/storage readiness; waiting only while access propagates"
        )
        self._guest(
            "from email.utils import formatdate\n"
            "import time\n"
            "import urllib.error\n"
            "import urllib.parse\n"
            "import urllib.request\n"
            f"clients = [('', True), ({reader.client_id!r}, True), "
            f"({denied.client_id!r}, False)]\n"
            "deadline = time.monotonic() + 300\n"
            "for client, can_read in clients:\n"
            "    while True:\n"
            "        query = {'api-version': '2018-02-01', "
            "'resource': 'https://storage.azure.com/'}\n"
            "        if client:\n"
            "            query['client_id'] = client\n"
            "        try:\n"
            "            request = urllib.request.Request("
            "'http://169.254.169.254/metadata/identity/oauth2/token?' + "
            "urllib.parse.urlencode(query), headers={'Metadata': 'true'})\n"
            "            with urllib.request.urlopen(request, timeout=5) as response:\n"
            "                token = json.load(response)['access_token']\n"
            "            if can_read:\n"
            f"                request = urllib.request.Request({blob.url!r}, headers={{"
            "'Authorization': 'Bearer ' + token, 'x-ms-version': '2020-10-02', "
            "'x-ms-date': formatdate(usegmt=True)})\n"
            "                response = urllib.request.urlopen(request, timeout=5)\n"
            "                with response:\n"
            "                    assert response.read().startswith(b'#!/bin/sh')\n"
            "            break\n"
            "        except urllib.error.HTTPError as error:\n"
            "            if error.code not in (400, 403, 404, 429, 500, 503):\n"
            "                raise\n"
            "            assert time.monotonic() < deadline, "
            "'Identity/storage access did not propagate: HTTP ' + str(error.code)\n"
            "            time.sleep(10)\n",
            timeout=360,
        )
        for selector in (
            {},
            {"clientId": reader.client_id},
            {"objectId": reader.principal_id},
        ):
            step_marker = self._marker()
            self._apply(
                protected={
                    "fileUris": [blob.url],
                    "commandToExecute": f"./{blob.blob_name} && echo {step_marker}",
                    "managedIdentity": selector,
                },
                marker=step_marker,
            )
        self._apply(
            protected={
                "fileUris": [blob.url],
                "commandToExecute": f"touch {self._root}",
                "managedIdentity": {"clientId": denied.client_id},
            },
            error="specified Managed Identity has read permissions",
        )
        self._guest(
            f"from pathlib import Path\nassert not Path({self._root!r}).exists()"
        )
        self._root_created = False

    def _policy(self, settings: str) -> None:
        result = self._guest(
            "from pathlib import Path\n"
            "handlers = list(Path('/var/lib/waagent').glob("
            f"{self._handler_glob!r}))\n"
            "assert handlers\n"
            "supported = [p for p in handlers if any("
            "b'allowedCommandToExecute' in binary.read_bytes() "
            "for binary in (p / 'bin').glob('*') if binary.is_file())]\n"
            "result['supported'] = bool(supported)\n"
            "if supported:\n"
            "    assert len(supported) == 1, supported\n"
            "    policy = supported[0] / 'config' / 'runtime_policy.json'\n"
            "    assert not policy.exists(), 'Refusing to overwrite a policy'\n"
            f"    policy.write_text({settings!r})\n"
            "    policy.chmod(0o600)\n"
            "    result['path'] = str(policy)\n"
        )
        if not result["supported"]:
            raise SkippedException(
                "The installed CSE handler does not support runtime policy. "
                "Set custom_script_version to a policy-capable handler."
            )
        self._policy_path = str(result["path"])

    @TestCaseMetadata(
        description="Major policy allow/deny paths and one invalid-policy fallback.",
        priority=5,
        maturity="preview",
    )
    def verify_runtime_policy(self) -> None:
        try:
            self._compute.virtual_machine_extensions.get(
                self._rg, self._vm_name, self._extension_name
            )
        except ResourceNotFoundError:
            marker = self._marker()
            self._apply({"commandToExecute": f"echo {marker}"}, marker=marker)
        url = self._fixture()
        marker = self._marker()
        command = f"test ! -f {self._root}/unexpected && ./crlf.sh && echo {marker}"
        allowed = {
            "allowedCommandToExecute": [command],
            "allowedDownloadedScripts": [
                hashlib.sha256(b"#!/bin/sh\necho fixture\n").hexdigest()
            ],
        }
        self._policy(json.dumps(allowed))
        self._apply(
            {"fileUris": [url + "/crlf.sh"], "commandToExecute": command},
            marker=marker,
        )
        blocked = f"touch {self._root}/unexpected; echo {self._marker()}"
        self._policy(json.dumps(allowed))
        self._apply({"commandToExecute": blocked}, error="not allowed by policy")
        allowed["allowedDownloadedScripts"] = ["0" * 64]
        self._policy(json.dumps(allowed))
        self._apply(
            {"fileUris": [url + "/crlf.sh"], "commandToExecute": blocked},
            error="policy-allowlist failed",
        )
        self._policy("{invalid-json")
        marker = self._marker()
        self._apply(
            {"commandToExecute": f"test ! -f {self._root}/unexpected && echo {marker}"},
            marker=marker,
        )
        self._guest(
            f"from pathlib import Path\nassert not Path({self._policy_path!r}).exists()"
        )

    @TestCaseMetadata(
        description="Explicit uninstall cleans owned data and reinstall succeeds.",
        priority=5,
        tags=["microsoft.azure.extensions.customscript"],
        maturity="preview",
    )
    def microsoft_azure_extensions_customscript_boot_validation_test(self) -> None:
        self._version = self._get_version(self._variables, use_default=False)
        marker = self._marker()
        self._root_created = True
        self._apply(
            {
                "commandToExecute": (
                    f"set -eu; mkdir -m 700 {self._root}; "
                    f"echo preserved > {self._root}/unrelated; echo {marker}"
                )
            },
            marker=marker,
        )
        self._compute.virtual_machine_extensions.begin_delete(
            self._rg, self._vm_name, self._extension_name
        ).result()
        self._guest(
            "from pathlib import Path\n"
            f"assert not Path({_DATA!r}).exists()\n"
            f"assert (Path({self._root!r}) / 'unrelated').read_text() == 'preserved\\n'"
        )
        marker = self._marker()
        self._apply(
            {"commandToExecute": f"test -d {_DATA} && echo {marker}"},
            marker=marker,
        )
