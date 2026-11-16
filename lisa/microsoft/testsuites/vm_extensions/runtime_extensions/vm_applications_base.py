# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import base64
import hashlib
import io
import json
import shlex
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from azure.core import PipelineClient
from azure.core.exceptions import (
    AzureError,
    HttpResponseError,
    ResourceExistsError,
    ResourceNotFoundError,
)
from azure.core.pipeline.policies import BearerTokenCredentialPolicy, RetryPolicy
from azure.core.rest import HttpRequest
from azure.mgmt.compute.models import (
    VirtualMachineRunCommand,
    VirtualMachineRunCommandScriptSource,
)
from azure.mgmt.resource.resources.models import (
    Deployment,
    DeploymentProperties,
    GenericResource,
)

from lisa import Logger, Node, TestSuite
from lisa.secret import add_secret
from lisa.sut_orchestrator.azure.common import (
    AZURE_SHARED_RG_NAME,
    generate_user_delegation_sas_token,
    get_compute_client,
    get_node_context,
    get_or_create_storage_container,
    get_resource_management_client,
    get_storage_account_name,
)
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.util import SkippedException

_HERE = Path(__file__).parent
_VM_API = "2025-04-01"
_GALLERY_API = "2024-03-03"
_STORAGE_API = "2023-01-01"
# Bump when changing publishing metadata or the command bootstrap contract.
_FIXTURE_SCHEMA = 2
_READY: Set[Tuple[str, str, str, str]] = set()
_DEFAULT_CONFIG = b"LISA default configuration\r\n\x00\x01\xff"
_OVERRIDE_CONFIG = b"LISA override configuration\n\x00\x02\xfe"
_VERSIONS = {
    "a": ("1.0.0", "2.0.0", "3.0.0", "4.0.0", "5.0.0"),
    "b": ("1.0.0",),
    "c": ("1.0.0",),
    "d": ("1.0.0",),
    "other": ("1.0.0",),
}


def _encoded(value: Dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(value, ensure_ascii=True).encode()).decode()


def _page_bytes(value: bytes) -> bytes:
    return value + bytes(512 - len(value) % 512)


def _package(script: bytes, filename: str) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        info = zipfile.ZipInfo(filename, date_time=(1980, 1, 1, 0, 0, 0))
        info.external_attr = 0o100600 << 16
        archive.writestr(info, script)
    return _page_bytes(stream.getvalue())


def _events(snapshot: Dict[str, Any]) -> List[Tuple[str, str, str, str]]:
    return [
        (event["app"], event["op"], event["version"], event["result"])
        for event in snapshot["events"]
    ]


class VmApplicationsBase(TestSuite):
    PUBLISHER = "Microsoft.CPlat.Core"
    EXTENSION_KEY = "vm_applications"
    EXTENSION_TYPE = ""
    SUPPORTS_DELETE = False
    OS_TYPE = ""

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        self._configured = False
        self._profile_started = False
        self._log = log
        self._variables: Dict[str, Any] = kwargs["variables"]
        platform = kwargs["environment"].platform
        assert isinstance(platform, AzurePlatform)
        self._platform = platform
        self._compute = get_compute_client(platform)
        node: Node = kwargs["node"]
        context = get_node_context(node)
        self._rg = context.resource_group_name
        self._vm_name = context.vm_name
        vm = self._compute.virtual_machines.get(self._rg, self._vm_name)
        assert (
            vm.id and vm.location and vm.storage_profile and vm.storage_profile.os_disk
        )
        assert str(vm.storage_profile.os_disk.os_type).lower() == self.OS_TYPE.lower()
        self._vm_id = vm.id
        self._location = vm.location
        self._resources = get_resource_management_client(
            platform.credential, platform.subscription_id, platform.cloud
        )
        endpoint = platform.cloud.endpoints.resource_manager.rstrip("/")
        self._rest = PipelineClient(
            base_url=endpoint,
            policies=[
                RetryPolicy(),
                BearerTokenCredentialPolicy(
                    platform.credential, endpoint + "/.default"
                ),
            ],
        )
        self._endpoint = endpoint
        self._run = uuid.uuid4().hex
        self._control_data: Dict[str, Any] = {
            "vm_id": self._vm_id,
            "run": self._run,
            "failures": {},
            "configuration": {},
            "requires": {},
            "reboot": {},
            "mutate": [],
            "parameters": {
                "LISA_REQUIRED": "literal ' \" $ ; & \u2603",
                "LISA_OPTIONAL": "default-value",
            },
        }
        suffix = "ps1" if self.OS_TYPE == "Windows" else "py"
        self._script = (
            _HERE / "scripts" / f"vm_applications_fixture.{suffix}"
        ).read_text(encoding="utf-8")
        self._payload = _package(self._script.encode(), f"fixture.{suffix}")
        digest = hashlib.sha256(
            self._payload + str(_FIXTURE_SCHEMA).encode() + _DEFAULT_CONFIG
        ).hexdigest()
        self._digest = digest
        self._names = {
            alias: f"lisa-vmapps-{self.OS_TYPE.lower()}-{alias}-{digest[:8]}"
            for alias in _VERSIONS
        }
        self._gallery_rg = str(
            self._variables.get("vm_applications_gallery_resource_group")
            or AZURE_SHARED_RG_NAME
        )
        gallery = str(
            self._variables.get("vm_applications_gallery_name")
            or (f"lisavmapps{self._location[:8]}" f"{platform.subscription_id[-8:]}")
        )
        self._gallery_id = (
            f"/subscriptions/{platform.subscription_id}"
            f"/resourceGroups/{self._gallery_rg}"
            f"/providers/Microsoft.Compute/galleries/{gallery}"
        )
        self._gallery = gallery
        existing = self._read(self._vm_id)["properties"].get("applicationProfile") or {}
        applications = existing.get("galleryApplications") or []
        if any(
            "/applications/lisa-vmapps-" not in app.get("packageReferenceId", "")
            for app in applications
        ):
            raise SkippedException(
                "VM application tests require a dedicated VM without customer "
                "applications; existing applications will not be overwritten."
            )
        self._configure()
        if applications:
            self._apply([])
            self._run = uuid.uuid4().hex
            self._configure(run=self._run)
        self._publish()

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        try:
            if self._configured:
                if self._control_data["failures"]:
                    self._configure(failures={})
                if self._profile_started:
                    self._apply([])
                self._guest("cleanup")
        except (AzureError, AssertionError, OSError, ValueError) as error:
            log.error(f"VM application cleanup failed; discarding the VM: {error}")
            kwargs["environment"].mark_dirty()
            raise
        finally:
            if hasattr(self, "_rest"):
                self._rest.close()

    def _read(
        self, resource_id: str, api: str = _VM_API, expand: str = ""
    ) -> Dict[str, Any]:
        params = {"api-version": api}
        if expand:
            params["$expand"] = expand
        request = HttpRequest("GET", self._endpoint + resource_id, params=params)
        with self._rest.send_request(
            request, connection_timeout=30, read_timeout=60
        ) as response:
            response.raise_for_status()
            result = response.json()
        assert isinstance(result, dict), "ARM response must be an object"
        return result

    def _deploy(self, template: str, parameters: Dict[str, Any]) -> None:
        self._resources.deployments.begin_create_or_update(
            self._gallery_rg,
            "lisa-vmapps-" + uuid.uuid4().hex[:16],
            Deployment(
                properties=DeploymentProperties(
                    mode="Incremental",
                    template=json.loads(
                        (_HERE / "templates" / template).read_text(encoding="utf-8")
                    ),
                    parameters={
                        name: {"value": value} for name, value in parameters.items()
                    },
                )
            ),
        ).result()

    def _storage(self) -> Any:
        account = str(
            self._variables.get("vm_applications_storage_account")
            or get_storage_account_name(self._platform.subscription_id, self._location)
        )
        group = str(
            self._variables.get("vm_applications_storage_resource_group")
            or AZURE_SHARED_RG_NAME
        )
        account_id = (
            f"/subscriptions/{self._platform.subscription_id}"
            f"/resourceGroups/{group}/providers/Microsoft.Storage/storageAccounts/"
            f"{account}"
        )
        created = False
        try:
            self._resources.resources.get_by_id(account_id, _STORAGE_API)
        except ResourceNotFoundError:
            assert group == self._gallery_rg, (
                "Create the configured storage account first when its resource "
                "group differs from the gallery resource group."
            )
            self._deploy(
                "vm_applications_storage.json",
                {"location": self._location, "storageAccountName": account},
            )
            created = True
        deadline = time.monotonic() + 300
        while True:
            try:
                container = get_or_create_storage_container(
                    "lisa-vmapplications",
                    cloud=self._platform.cloud,
                    credential=self._platform.credential,
                    account_name=account,
                    platform=self._platform,
                )
                assert not container.get_container_access_policy()[
                    "public_access"
                ], "VM application fixture storage must be private"
                self._account = account
                return container
            except HttpResponseError as error:
                if (
                    not created
                    or error.status_code != 403
                    or time.monotonic() >= deadline
                ):
                    raise
                self._log.debug("Waiting for new fixture storage RBAC propagation")
                time.sleep(5)

    def _stage(self, container: Any, name: str, data: bytes, page: bool) -> str:
        blob = container.get_blob_client(
            f"{self.OS_TYPE.lower()}/{self._digest}/{name}"
        )
        checksum = hashlib.sha256(data).hexdigest()
        try:
            blob.upload_blob(
                data,
                blob_type="PageBlob" if page else "BlockBlob",
                overwrite=False,
                metadata={"lisa_sha256": checksum},
            )
        except ResourceExistsError:
            properties = blob.get_blob_properties()
            assert properties.size == len(data), "Existing fixture blob has wrong size"
            assert (
                properties.metadata.get("lisa_sha256") == checksum
            ), "Existing fixture blob has different content"
        sas = str(
            generate_user_delegation_sas_token(
                container.container_name,
                blob.blob_name,
                cloud=self._platform.cloud,
                credential=self._platform.credential,
                account_name=self._account,
                expired_hours=24,
                platform=self._platform,
            )
        )
        add_secret(sas)
        return f"{blob.url}?{sas}"

    def _files(self, alias: str) -> Tuple[str, str, Optional[str]]:
        name = self._names[alias]
        package = "payload data.zip" if alias == "c" else name
        config = "settings data.json" if alias == "c" else name + "_config"
        if self.OS_TYPE == "Windows" and alias == "c":
            package = "payload-data.zip"
            config = "settings-data.json"
        checksum = (
            hashlib.sha256(_page_bytes(_DEFAULT_CONFIG)).hexdigest()
            if alias in ("a", "c")
            else None
        )
        return package, config, checksum

    def _command(
        self, operation: str, alias: str, version: str, action: str = ""
    ) -> str:
        package, config, checksum = self._files(alias)
        data = _encoded(
            {
                "app": alias,
                "name": self._names[alias],
                "version": version,
                "package": package,
                "config": config,
                "config_sha256": checksum,
                "sha256": hashlib.sha256(self._payload).hexdigest(),
                "action": action,
            }
        )
        if self.OS_TYPE == "Linux":
            bootstrap = (
                "import sys,zipfile;"
                "exec(compile(zipfile.ZipFile(sys.argv[1]).read('fixture.py'),"
                "'fixture.py','exec'))"
            )
            return (
                f"python3 -c {shlex.quote(bootstrap)} {shlex.quote(package)} "
                f"{operation} {data}"
            )
        filename = package.replace("'", "''")
        bootstrap = (
            "Add-Type -AssemblyName System.IO.Compression.FileSystem;"
            "$z=[IO.Compression.ZipFile]::OpenRead("
            f"(Join-Path (Get-Location) '{filename}'));"
            "try{$r=New-Object IO.StreamReader($z.GetEntry('fixture.ps1').Open());"
            "try{$s=$r.ReadToEnd()}finally{$r.Dispose()}}finally{$z.Dispose()};"
            f"& ([scriptblock]::Create($s)) -Operation '{operation}' -Data '{data}'"
        )
        encoded = base64.b64encode(bootstrap.encode("utf-16-le")).decode()
        return (
            "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass "
            f"-EncodedCommand {encoded}"
        )

    def _version_properties(
        self, alias: str, version: str, package_uri: str, config_uri: str
    ) -> Dict[str, Any]:
        actions = {
            operation: self._command(operation, alias, version)
            for operation in ("install", "remove", "update")
        }
        if alias == "a" and version == "3.0.0":
            del actions["update"]
        package, config, checksum = self._files(alias)
        source = {"mediaLink": package_uri}
        if checksum is not None:
            source["defaultConfigurationLink"] = config_uri
        publishing: Dict[str, Any] = {
            "source": source,
            "manageActions": actions,
            "replicaCount": 1,
            "targetRegions": [{"name": self._location, "regionalReplicaCount": 1}],
            "settings": {
                "scriptBehaviorAfterReboot": (
                    "Rerun" if alias == "a" and version == "5.0.0" else "None"
                )
            },
            "customActions": [
                {
                    "name": action,
                    "script": self._command("action", alias, version, action),
                    "parameters": [
                        {"name": "LISA_REQUIRED", "type": "String", "required": True},
                        {
                            "name": "LISA_OPTIONAL",
                            "type": "String",
                            "required": False,
                            "defaultValue": "default-value",
                        },
                    ],
                }
                for action in ("check", "fail", "recover")
            ],
        }
        if alias == "c":
            publishing["settings"].update(
                {"packageFileName": package, "configFileName": config}
            )
        return {"publishingProfile": publishing}

    def _publish(self) -> None:
        container = self._storage()
        self._override_uri = self._stage(
            container, "override.bin", _OVERRIDE_CONFIG, False
        )
        key = (
            self._platform.subscription_id,
            self._gallery_id,
            self.OS_TYPE,
            self._digest,
        )
        if key in _READY:
            return
        missing: List[Tuple[str, str]] = []
        for alias, versions in _VERSIONS.items():
            for version in versions:
                try:
                    resource = self._resources.resources.get_by_id(
                        self._reference(alias, version), _GALLERY_API
                    )
                except ResourceNotFoundError:
                    missing.append((alias, version))
                else:
                    assert (resource.tags or {}).get(
                        "lisa_fixture"
                    ) == self._digest, (
                        "Existing gallery fixture does not match this test build"
                    )
        if missing:
            package_uri = self._stage(container, "package.zip", self._payload, True)
            config_uri = self._stage(
                container, "default.bin", _page_bytes(_DEFAULT_CONFIG), True
            )
            self._log.info(
                f"Publishing {len(missing)} immutable {self.OS_TYPE} VM application "
                f"versions in {self._gallery_rg}/{self._gallery}"
            )
            self._deploy(
                "vm_applications_gallery.json",
                {
                    "location": self._location,
                    "galleryName": self._gallery,
                    "fixtureDigest": self._digest,
                    "applications": [
                        {
                            "name": self._names[alias],
                            "osType": (
                                ("Linux" if self.OS_TYPE == "Windows" else "Windows")
                                if alias == "other"
                                else self.OS_TYPE
                            ),
                        }
                        for alias in _VERSIONS
                    ],
                    "versions": {
                        "items": [
                            {
                                "application": self._names[alias],
                                "version": version,
                                "properties": self._version_properties(
                                    alias, version, package_uri, config_uri
                                ),
                            }
                            for alias, version in missing
                        ]
                    },
                },
            )
        deadline = time.monotonic() + 1200
        pending = [
            self._reference(alias, version)
            for alias, versions in _VERSIONS.items()
            for version in versions
        ]
        while pending:
            remaining = []
            for resource_id in pending:
                properties = self._read(resource_id, _GALLERY_API, "ReplicationStatus")[
                    "properties"
                ]
                state = properties.get("provisioningState", "")
                replication = properties.get("replicationStatus") or {}
                aggregated = replication.get("aggregatedState", "")
                assert (
                    state != "Failed" and aggregated != "Failed"
                ), f"Gallery fixture replication failed: {resource_id}"
                if state != "Succeeded" or aggregated != "Completed":
                    remaining.append(resource_id)
            pending = remaining
            if pending:
                assert (
                    time.monotonic() < deadline
                ), f"Gallery fixtures did not finish regional replication: {pending}"
                time.sleep(5)
        _READY.add(key)

    def _reference(self, alias: str, version: str = "1.0.0") -> str:
        return (
            f"{self._gallery_id}/applications/{self._names[alias]}/versions/{version}"
        )

    def _entry(
        self, alias: str, version: str = "1.0.0", **properties: Any
    ) -> Dict[str, Any]:
        return {
            "packageReferenceId": self._reference(alias, version),
            "treatFailureAsDeploymentFailure": True,
            **properties,
        }

    def _guest(self, operation: str, **properties: Any) -> Dict[str, Any]:
        marker = f"LISA-VMAPPS-RC-{uuid.uuid4().hex}:"
        data = _encoded({**self._control_data, **properties, "marker": marker})
        if self.OS_TYPE == "Windows":
            script = (
                "$ErrorActionPreference='Stop'\n& {\n"
                f"{self._script}\n}} -Operation '{operation}' -Data '{data}'"
            )
        else:
            script = (
                f"set -eu\npython3 - {operation} {data} <<'LISA_VM_APPS'\n"
                f"{self._script}\nLISA_VM_APPS\n"
            )
        commands = self._compute.virtual_machine_run_commands
        commands.begin_create_or_update(
            self._rg,
            self._vm_name,
            "lisa-vmapps-validation",
            VirtualMachineRunCommand(
                location=self._location,
                source=VirtualMachineRunCommandScriptSource(script=script),
                timeout_in_seconds=120,
                treat_failure_as_deployment_failure=True,
            ),
        ).result()
        command = commands.get_by_virtual_machine(
            resource_group_name=self._rg,
            vm_name=self._vm_name,
            run_command_name="lisa-vmapps-validation",
            expand="instanceView",
        )
        view = command.instance_view
        assert (
            view and str(view.execution_state).lower() == "succeeded"
        ), f"Managed Run Command failed: {view}"
        assert view.exit_code == 0, f"Managed Run Command failed: {view.error}"
        lines = [
            line for line in (view.output or "").splitlines() if line.startswith(marker)
        ]
        assert len(lines) == 1, f"Missing fresh Run Command output: {view.output}"
        result = json.loads(lines[0][len(marker) :])
        assert isinstance(result, dict), "Run Command must return an object"
        return result

    def _configure(self, **properties: Any) -> None:
        self._control_data.update(properties)
        self._configured = True
        self._guest("configure")

    def _snapshot(self) -> Dict[str, Any]:
        result = self._guest("inspect")
        assert isinstance(result.get("events"), list), "Missing fixture audit events"
        assert result["run"] == self._run, "Stale application audit events"
        assert (
            result["unrelated"]
            == hashlib.sha256(b"LISA VMApplications unrelated file\n").hexdigest()
        ), "Application operations changed the unrelated sentinel file"
        return result

    def _apply(
        self,
        applications: List[Dict[str, Any]],
        outcomes: Optional[Dict[str, str]] = None,
        deployment_failure: bool = False,
        current_versions: Optional[Dict[str, str]] = None,
    ) -> None:
        self._profile_started = True
        self._log.info(
            f"Applying {len(applications)} applications to the existing "
            f"{self.OS_TYPE} VM"
        )
        try:
            self._resources.resources.begin_update_by_id(
                self._vm_id,
                _VM_API,
                GenericResource(
                    location=self._location,
                    properties={
                        "applicationProfile": {"galleryApplications": applications}
                    },
                ),
            ).result()
        except HttpResponseError as error:
            code = str(getattr(error.error, "code", "")).lower()
            message = str(error).lower()
            if (
                not deployment_failure
                or not any(name in code for name in ("vmextension", "vmapplication"))
                or not any(
                    name and name.lower() in message
                    for name in ("VMAppExtension", self.EXTENSION_TYPE)
                )
            ):
                raise
            self._log.info(
                f"Observed expected VM Applications deployment failure ({code})"
            )
        else:
            assert (
                not deployment_failure
            ), "Expected the CRP VM update operation to fail, but it succeeded"
        self._wait_view(
            applications, outcomes or {}, deployment_failure, current_versions
        )

    def _wait_view(
        self,
        applications: List[Dict[str, Any]],
        outcomes: Dict[str, str],
        deployment_failure: bool = False,
        current_versions: Optional[Dict[str, str]] = None,
    ) -> None:
        desired: Dict[str, str] = {}
        manually_managed: Set[str] = set()
        for app in applications:
            reference = app["packageReferenceId"]
            name = reference.split("/applications/")[1].split("/")[0]
            if app.get("manuallyManaged"):
                manually_managed.add(name)
            else:
                desired[name] = reference.rsplit("/", 1)[1]
        deadline = time.monotonic() + 90
        while True:
            vm = self._read(self._vm_id, expand="instanceView")
            properties = vm["properties"]
            state = properties.get("provisioningState", "").lower()
            view = properties.get("instanceView") or {}
            results = {app["name"]: app for app in view.get("vmApplications") or []}
            matches = set(desired) <= set(results) <= set(desired) | manually_managed
            for name in manually_managed.intersection(results):
                result = results[name]
                matches = matches and not (
                    result.get("version")
                    or result.get("result")
                    or result.get("actionsPerformed")
                )
            for alias, name in self._names.items():
                if name in desired:
                    result = results.get(name, {})
                    matches = matches and (
                        result.get("version")
                        == (current_versions or {}).get(alias, desired[name])
                        and outcomes.get(alias, "success").lower()
                        in str(result.get("result", "")).lower()
                    )
            if matches:
                if not deployment_failure:
                    assert state not in (
                        "failed",
                        "canceled",
                    ), f"Unexpected deployment failure: {results}"
                self._last_view = results
                return
            assert time.monotonic() < deadline, (
                f"Application instance view did not converge: "
                f"desired={desired}, results={results}, VM state={state}"
            )
            time.sleep(3)

    def _child(
        self, alias: str, properties: Dict[str, Any], patch: bool = False
    ) -> None:
        self._profile_started = True
        resource_id = f"{self._vm_id}/vmApplications/{self._names[alias]}"
        operation = (
            self._resources.resources.begin_update_by_id
            if patch
            else self._resources.resources.begin_create_or_update_by_id
        )
        operation(
            resource_id,
            _VM_API,
            GenericResource(location=self._location, properties=properties),
        ).result()

    def _action(
        self, name: str = "check", identifier: Optional[str] = None
    ) -> Dict[str, Any]:
        action: Dict[str, Any] = {
            "name": name,
            "parameters": [
                {
                    "name": "LISA_REQUIRED",
                    "value": self._control_data["parameters"]["LISA_REQUIRED"],
                }
            ],
        }
        if identifier is not None:
            action["uniqueIdentifier"] = identifier
        return action

    def _reject(self, applications: List[Dict[str, Any]], diagnostic: str) -> None:
        before = self._read(self._vm_id)["properties"].get("applicationProfile")
        try:
            self._resources.resources.begin_update_by_id(
                self._vm_id,
                _VM_API,
                GenericResource(
                    properties={
                        "applicationProfile": {"galleryApplications": applications}
                    }
                ),
            ).result()
        except HttpResponseError as error:
            assert error.status_code in (400, 404, 409), str(error)
            assert (
                diagnostic.lower() in str(error).lower()
            ), f"Unexpected CRP rejection: {error}"
        else:
            raise AssertionError(f"CRP accepted invalid input: {diagnostic}")
        assert self._read(self._vm_id)["properties"].get("applicationProfile") == before

    def _assert_events(
        self, expected: List[Tuple[str, str, str, str]], ordered: bool = True
    ) -> Dict[str, Any]:
        snapshot = self._snapshot()
        actual = _events(snapshot)
        if ordered:
            assert actual == expected, f"Unexpected application executions: {actual}"
        else:
            assert sorted(actual) == sorted(
                expected
            ), f"Unexpected application executions: {actual}"
        return snapshot

    def _assert_action_status(
        self, snapshot: Dict[str, Any], alias: str, operation: str, result: str
    ) -> None:
        status = snapshot["status"]
        assert status is not None, "No VM application handler status was found"
        assert any(
            item["name"] == self._names[alias]
            and item["op"].lower() == operation.lower()
            and item["result"] == result
            for item in status["actions"]
        ), f"Missing {alias}/{operation}/{result} handler result: {status}"

    def _verify_installation_and_configuration(self) -> None:
        self._log.info(
            "Phase: installation, default/custom files and manual management"
        )
        self._configure(
            configuration={"a": hashlib.sha256(_OVERRIDE_CONFIG).hexdigest()}
        )
        b, c = self._entry("b"), self._entry("c")
        manual = self._entry("d", manuallyManaged=True)
        applications = [
            self._entry("a", configurationReference=self._override_uri),
            b,
            c,
            manual,
        ]
        self._apply(applications)
        snapshot = self._assert_events(
            [
                ("a", "install", "1.0.0", "success"),
                ("b", "install", "1.0.0", "success"),
                ("c", "install", "1.0.0", "success"),
            ],
            ordered=False,
        )
        assert set(snapshot["states"]) == {"a", "b", "c"}
        status = snapshot["status"]
        assert status and status["handler"] == self.EXTENSION_TYPE
        self._log.info(
            f"CRP selected {status['handler']} handler version {status['version']}"
        )

        self._log.info("Phase: invalid CRP profiles leave applications unchanged")
        self._verify_crp_validation(applications)
        self._assert_events(_events(snapshot))

    def _verify_application_lifecycle(self) -> None:
        self._log.info("Phase: lifecycle installation")
        a = self._entry("a")
        self._apply([a])
        expected = [("a", "install", "1.0.0", "success")]
        self._assert_events(expected)

        self._log.info(
            "Phase: unchanged app stays idle during no-op and companion updates"
        )
        self._apply([a])
        b = self._entry("b", order=2)
        self._apply([self._entry("a", order=1), b])
        expected = expected + [("b", "install", "1.0.0", "success")]
        self._assert_events(expected)

        self._log.info("Phase: native application update")
        self._apply([self._entry("a", "2.0.0", order=1), b])
        expected = expected + [("a", "update", "2.0.0", "success")]
        self._assert_events(expected)

        self._log.info("Phase: explicit application downgrade")
        self._apply([self._entry("a", order=1), b])
        expected = expected + [("a", "update", "1.0.0", "success")]
        self._assert_events(expected)

        self._log.info("Phase: replacement without an update command")
        self._apply([self._entry("a", "3.0.0", order=1), b])
        self._assert_events(
            expected
            + [
                ("a", "remove", "1.0.0", "success"),
                ("a", "install", "3.0.0", "success"),
            ]
        )

    def _verify_ordered_operations(self) -> None:
        self._apply([self._entry("d"), self._entry("a")])
        self._configure(requires={"b": ["a"], "c": ["b"]})
        self._apply(
            [
                self._entry("c", order=30),
                self._entry("a", "2.0.0", order=10),
                self._entry("b", order=20),
            ]
        )
        snapshot = self._snapshot()
        assert sorted(_events(snapshot)[:2]) == sorted(
            [
                ("d", "install", "1.0.0", "success"),
                ("a", "install", "1.0.0", "success"),
            ]
        )
        assert _events(snapshot)[2:] == [
            ("d", "remove", "1.0.0", "success"),
            ("a", "update", "2.0.0", "success"),
            ("b", "install", "1.0.0", "success"),
            ("c", "install", "1.0.0", "success"),
        ]

    def _verify_ordered_failure_and_recovery(self) -> None:
        self._log.info(
            "Phase: failure skips higher orders, not peers or unordered apps"
        )
        self._configure(failures={"a.install": True})
        a = self._entry("a", order=1, treatFailureAsDeploymentFailure=False)
        b, d = self._entry("b", order=1), self._entry("d")
        self._apply(
            [a, b, self._entry("c", order=2), d],
            outcomes={"a": "failed", "c": "skipped"},
        )
        snapshot = self._assert_events(
            [
                ("a", "install", "1.0.0", "failed"),
                ("b", "install", "1.0.0", "success"),
                ("d", "install", "1.0.0", "success"),
            ],
            ordered=False,
        )
        expected = _events(snapshot)

        self._log.info("Phase: skipped-entry cleanup runs no remove or retry commands")
        self._apply([a, b, d], outcomes={"a": "failed"})
        self._assert_events(expected)

        self._log.info("Phase: good version recovers and permits a new installation")
        self._configure(failures={})
        self._apply(
            [
                self._entry("a", "2.0.0", order=1),
                b,
                self._entry("c", order=2),
                d,
            ]
        )
        snapshot = self._assert_events(
            expected
            + [
                ("a", "update", "2.0.0", "success"),
                ("c", "install", "1.0.0", "success"),
            ]
        )
        assert set(snapshot["states"]) == {"a", "b", "c", "d"}

    def _verify_failure_policy(self) -> None:
        expected = []
        for fail_deployment in (False, True):
            self._log.info(
                f"Phase: install failure with deployment failure {fail_deployment}"
            )
            self._configure(failures={"a.install": True})
            self._apply(
                [self._entry("a", treatFailureAsDeploymentFailure=fail_deployment)],
                outcomes={"a": "failed"},
                deployment_failure=fail_deployment,
            )
            expected.append(("a", "install", "1.0.0", "failed"))
            self._assert_events(expected)
            self._configure(failures={})
            self._apply([])
            expected.append(("a", "remove", "1.0.0", "success"))
            self._log.info("Phase: successful installation before update failure")
            self._apply(
                [self._entry("a", treatFailureAsDeploymentFailure=fail_deployment)]
            )
            expected.append(("a", "install", "1.0.0", "success"))
            self._assert_events(expected)
            self._log.info(
                f"Phase: update failure with deployment failure {fail_deployment}"
            )
            self._configure(failures={"a.update": True})
            self._apply(
                [
                    self._entry(
                        "a", "2.0.0", treatFailureAsDeploymentFailure=fail_deployment
                    )
                ],
                outcomes={"a": "failed"},
                deployment_failure=fail_deployment,
            )
            expected.append(("a", "update", "2.0.0", "failed"))
            self._assert_events(expected)
            self._configure(failures={})
            self._apply([])
            expected.append(("a", "remove", "2.0.0", "success"))
        self._assert_events(expected)

    def _verify_replace_failure(self) -> None:
        self._apply([self._entry("a")])
        self._configure(failures={"a.remove": True})
        self._apply(
            [self._entry("a", "3.0.0", treatFailureAsDeploymentFailure=False)],
            outcomes={"a": "failed"},
            current_versions={"a": "1.0.0"},
        )
        snapshot = self._snapshot()
        events = _events(snapshot)
        assert events[:1] == [
            ("a", "install", "1.0.0", "success")
        ], f"Unexpected application executions: {events}"
        assert events[1:] and all(
            event == ("a", "remove", "1.0.0", "failed") for event in events[1:]
        ), f"Replacement ran despite failed old-version removal: {events}"
        assert set(snapshot["states"]) == {"a"}
        assert snapshot["states"]["a"]["version"] == "1.0.0"

    def _verify_removal_and_reuse(self) -> None:
        self._log.info("Phase: install two apps and modify one app's cached files")
        self._configure(mutate=["a"])
        self._apply([self._entry("a", order=1), self._entry("b", order=2)])

        self._log.info("Phase: modified-cache removal preserves the other app")
        self._apply([self._entry("b")])
        expected = [
            ("a", "install", "1.0.0", "success"),
            ("b", "install", "1.0.0", "success"),
            ("a", "remove", "1.0.0", "success"),
        ]
        snapshot = self._assert_events(expected)
        assert set(snapshot["states"]) == {"b"}
        assert not snapshot["present"]["a"]
        assert snapshot["present"]["b"]

        self._log.info("Phase: normal removal clears all application data")
        self._apply([])
        expected = expected + [("b", "remove", "1.0.0", "success")]
        snapshot = self._assert_events(expected)
        assert not snapshot["states"]
        assert not any(snapshot["present"].values())

        self._log.info("Phase: reinstall on the same handler after cleanup")
        self._apply([self._entry("a")])
        self._assert_events(expected + [("a", "install", "1.0.0", "success")])

    def _verify_custom_action(self) -> None:
        self._apply(
            [
                self._entry(
                    "a", customActions=[self._action(identifier=uuid.uuid4().hex)]
                )
            ]
        )
        self._apply(
            [
                self._entry(
                    "a", customActions=[self._action(identifier=uuid.uuid4().hex)]
                )
            ]
        )
        self._assert_events(
            [
                ("a", "install", "1.0.0", "success"),
                ("a", "action", "1.0.0", "success"),
                ("a", "action", "1.0.0", "success"),
            ]
        )

    def _verify_remove_failure(self) -> None:
        self._apply([self._entry("a", order=1), self._entry("b", order=2)])
        self._configure(failures={"a.remove": True})
        self._apply([self._entry("b"), self._entry("c")])
        snapshot = self._assert_events(
            [
                ("a", "install", "1.0.0", "success"),
                ("b", "install", "1.0.0", "success"),
                ("a", "remove", "1.0.0", "failed"),
                ("c", "install", "1.0.0", "success"),
            ]
        )
        self._assert_action_status(snapshot, "a", "Remove", "FAILED")

    def _verify_custom_action_replay(self) -> None:
        action = self._action(identifier=uuid.uuid4().hex)
        self._apply([self._entry("a", customActions=[action])])
        self._apply([self._entry("a", customActions=[action]), self._entry("b")])
        self._apply(
            [
                self._entry(
                    "a", customActions=[self._action(identifier=uuid.uuid4().hex)]
                ),
                self._entry("b"),
            ]
        )
        self._apply(
            [self._entry("a", customActions=[self._action()]), self._entry("b")]
        )
        self._assert_events(
            [
                ("a", "install", "1.0.0", "success"),
                ("a", "action", "1.0.0", "success"),
                ("b", "install", "1.0.0", "success"),
                ("a", "action", "1.0.0", "success"),
                ("a", "action", "1.0.0", "success"),
            ]
        )

    def _verify_custom_action_failure(self) -> None:
        self._apply([self._entry("a")])
        self._apply(
            [self._entry("a", customActions=[self._action("fail", uuid.uuid4().hex)])]
        )
        snapshot = self._snapshot()
        self._assert_action_status(snapshot, "a", "fail", "FAILED")
        self._apply(
            [
                self._entry(
                    "a", customActions=[self._action("recover", uuid.uuid4().hex)]
                )
            ]
        )
        self._assert_events(
            [
                ("a", "install", "1.0.0", "success"),
                ("a", "action", "1.0.0", "failed"),
                ("a", "action", "1.0.0", "success"),
            ]
        )

    def _verify_child_resource_operations(self) -> None:
        a = self._entry("a")
        self._child("a", a)
        self._child("b", self._entry("b"))
        self._wait_view([a, self._entry("b")], {})
        resource_id = f"{self._vm_id}/vmApplications/{self._names['a']}"
        self._child("a", self._entry("a", "2.0.0"), patch=True)
        self._wait_view([self._entry("a", "2.0.0"), self._entry("b")], {})
        child = self._read(resource_id, expand="instanceView")
        assert child["properties"]["instanceView"]["version"] == "2.0.0"
        collection = self._read(f"{self._vm_id}/vmApplications")
        assert {item["name"] for item in collection["value"]} == {
            self._names["a"],
            self._names["b"],
        }
        self._resources.resources.begin_update_by_id(
            resource_id, _VM_API, GenericResource(tags={"lisa": self._run})
        ).result()
        assert self._read(resource_id)["tags"]["lisa"] == self._run
        self._resources.resources.begin_delete_by_id(resource_id, _VM_API).result()
        self._wait_view([self._entry("b")], {})
        self._assert_events(
            [
                ("a", "install", "1.0.0", "success"),
                ("b", "install", "1.0.0", "success"),
                ("a", "update", "2.0.0", "success"),
                ("a", "remove", "2.0.0", "success"),
            ]
        )

    def _verify_crp_validation(self, applications: List[Dict[str, Any]]) -> None:
        self._reject(applications + [self._entry("other")], self._names["other"])
        self._reject(applications + [applications[0]], "same packageReferenceId")
        self._reject(applications + [{}], "packageReferenceId")
        invalid = self._entry("b")
        invalid["packageReferenceId"] = "not-a-resource-id"
        self._reject(applications + [invalid], "not-a-resource-id")
        without_b = [
            app
            for app in applications
            if app["packageReferenceId"] != self._entry("b")["packageReferenceId"]
        ]
        self._reject(
            without_b
            + [self._entry("b", configurationReference="http://example.invalid/x")],
            "configurationReference",
        )

    def _verify_custom_action_validation(self) -> None:
        a = self._entry("a")
        self._apply([a])
        self._reject(
            [self._entry("a", customActions=[self._action("not-defined")])],
            "not-defined",
        )
        missing = {"name": "check", "parameters": []}
        self._reject([self._entry("a", customActions=[missing])], "LISA_REQUIRED")
        unknown = self._action()
        unknown["parameters"].append({"name": "UNKNOWN", "value": "x"})
        self._reject([self._entry("a", customActions=[unknown])], "UNKNOWN")
        duplicate = self._action()
        duplicate["parameters"].append({"name": "LISA_REQUIRED", "value": "duplicate"})
        self._reject([self._entry("a", customActions=[duplicate])], "LISA_REQUIRED")
        self._assert_events([("a", "install", "1.0.0", "success")])

    def _verify_restart_persistence(self) -> None:
        self._apply([self._entry("a")])
        before = self._snapshot()["boot"]
        self._compute.virtual_machines.begin_restart(self._rg, self._vm_name).result()
        self._apply([self._entry("a"), self._entry("b")])
        snapshot = self._assert_events(
            [
                ("a", "install", "1.0.0", "success"),
                ("b", "install", "1.0.0", "success"),
            ]
        )
        assert snapshot["boot"] != before, "The VM did not reboot"

    def _verify_reboot(self, rerun: bool) -> None:
        before = self._snapshot()["boot"]
        self._configure(reboot={"a": "install"})
        version = "5.0.0" if rerun else "4.0.0"
        self._apply(
            [self._entry("a", version)],
            outcomes={"a": "success" if rerun else "reboot"},
        )
        expected = [("a", "install", version, "reboot")]
        if rerun:
            expected.append(("a", "install", version, "success"))
        snapshot = self._assert_events(expected)
        assert snapshot["boot"] != before, "The VM did not reboot"
