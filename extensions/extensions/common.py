import json
from typing import Any, Dict, List, Set

from azure.identity import ClientAssertionCredential, ManagedIdentityCredential

from lisa.messages import TestResultMessageBase
from lisa.util import hookspec, plugin_manager
from lisa.util.logger import Logger

from .triage import Triage


class TestPassCacheStatus:
    NOT_STARTED: str = "NotStarted"
    RUNNING: str = "Running"
    DONE: str = "Done"


class LsgExtensionHookSpec:
    @hookspec
    def get_test_run_log_location(self) -> str:
        raise NotImplementedError

    @hookspec
    def get_test_run_id(self) -> int:
        raise NotImplementedError

    @hookspec
    def get_test_result_db_id(self, result_id: str) -> int:
        raise NotImplementedError


if not plugin_manager.is_registered(LsgExtensionHookSpec):
    plugin_manager.add_hookspecs(LsgExtensionHookSpec)


_ignored_fields: Set[str] = set(
    [
        "area",
        "category",
        "tags",
        "description",
        "priority",
        "owner",
        "name",
        "environment",
        "hardware_platform",
        "kernel_version",
        "lis_version",
        "host_version",
        "location",
        "platform",
        "image",
        "vmsize",
        "wala_version",
        "wala_distro",
        "distro_version",
        "vm_generation",
        "storage_log_path",
    ]
)


def get_extra_information(message: TestResultMessageBase) -> Dict[str, str]:
    # return extra fields, which can be saved separately.
    return {
        key: value
        for key, value in message.information.items()
        if key not in _ignored_fields
    }


def get_test_run_log_location(log: Logger) -> str:
    url = ""
    try:
        storage_account_url = plugin_manager.hook.get_test_run_log_location()
        assert len(storage_account_url) > 0
        url = storage_account_url[-1]
    except Exception as e:
        log.debug(e)
    return url


def get_triage_from_file(
    file_path: str, test_project_name: str, test_pass_name: str, log: Logger
) -> Triage:
    log.debug(f"Loading triage rules from {file_path}")
    with open(file_path) as f:
        data: List[Dict[str, Any]] = json.load(f)

    return Triage(
        test_project_name=test_project_name,
        test_pass_name=test_pass_name,
        failures=data,
    )


def get_case_ids_from_file(file_path: str, log: Logger) -> Dict[str, Any]:
    log.debug(f"Loading test cases from {file_path}")
    with open(file_path) as f:
        data: List[Dict[str, Any]] = json.load(f)

    case_ids = {
        str(case.get("name")): case.get("id")
        for case in data
        if case.get("name") and case.get("id")
    }
    return case_ids


def get_cross_tenant_credential(
    msi_client_id: str, enterprise_app_client_id: str, tenant_id: str
) -> ClientAssertionCredential:
    AUDIENCE = "api://AzureADTokenExchange"

    def _get_managed_identity_token(msi_client_id: str, audience: str) -> str:
        credential = ManagedIdentityCredential(client_id=msi_client_id)
        return credential.get_token(audience).token  # type: ignore

    credential = ClientAssertionCredential(
        tenant_id=tenant_id,
        client_id=enterprise_app_client_id,
        func=lambda: _get_managed_identity_token(msi_client_id, AUDIENCE),
    )
    return credential
