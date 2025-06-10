import os
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, List, Optional, Set, Type, cast
from urllib.parse import quote

from azure.identity import (
    CertificateCredential,
    ClientSecretCredential,
    DefaultAzureCredential,
)
from azure.mgmt.storage import StorageManagementClient
from marshmallow import validate
from msrestazure.azure_cloud import AZURE_PUBLIC_CLOUD  # type: ignore
from pathvalidate import sanitize_filepath
from retry import retry

from lisa import messages, notifier, schema
from lisa.environment import EnvironmentMessage, EnvironmentStatus
from lisa.platform_ import PlatformMessage, PlatformStatus
from lisa.sut_orchestrator.azure.common import (
    AZURE_SHARED_RG_NAME,
    check_or_create_resource_group,
    check_or_create_storage_account,
    generate_user_delegation_sas_token,
    get_or_create_storage_container,
)
from lisa.sut_orchestrator.azure.credential import (
    AzureCredential,
    AzureCredentialSchema,
)
from lisa.testsuite import TestResultMessage, TestStatus
from lisa.util import (
    LisaException,
    constants,
    field_metadata,
    hookimpl,
    plugin_manager,
    subclasses,
)

from .common import get_cross_tenant_credential

DEFAULT_CONTAINER_NAME = "lisa-logs"
DEFAULT_NAME = "default"
DEFAULT_LOCATION = "westus2"
AZURE_STORAGE_ACCOUNT_PREFIX = (
    "https://ms.portal.azure.com/#blade/"
    "Microsoft_Azure_Storage/ContainerMenuBlade/overview/storageAccountId"
)


@dataclass
class LsgStorageSchema(schema.Notifier):
    use_typed_credential: bool = False
    azure_credential: Optional[AzureCredentialSchema] = None

    subscription_id: str = field(
        default="",
        metadata=field_metadata(
            validate=validate.Regexp(constants.GUID_REGEXP),
        ),
    )
    client_id: str = field(
        default="",
        metadata=field_metadata(
            validate=validate.Regexp(constants.GUID_REGEXP),
        ),
    )
    client_secret: str = ""
    tenant_id: str = field(
        default="",
        metadata=field_metadata(
            validate=validate.Regexp(constants.GUID_REGEXP),
        ),
    )
    msi_client_id: str = field(
        default="",
        metadata=field_metadata(
            validate=validate.Regexp(constants.GUID_REGEXP),
        ),
    )
    enterprise_app_client_id: str = field(
        default="",
        metadata=field_metadata(
            validate=validate.Regexp(constants.GUID_REGEXP),
        ),
    )
    resource_group: str = ""
    storage_account_name: str = ""
    container_name: str = ""

    use_sas_url: bool = False
    sas_token_expired_hours: int = 2


class LsgStorage(notifier.Notifier):
    """
    It's a storage notifier, which uploads run logs to a storage account.
    """

    @classmethod
    def type_name(cls) -> str:
        return "lsgstorage"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return LsgStorageSchema

    @staticmethod
    def get_default_storage_account_name(
        subscription_id: str,
    ) -> str:
        return f"lisalogs{subscription_id[-8:]}"

    @hookimpl
    def get_test_run_log_location(self) -> str:
        return self._get_remote_root_url()

    @hookimpl
    def update_test_result_message(self, message: TestResultMessage) -> None:
        base_url = self._get_remote_root_url()
        if message.log_file:
            # 1. The file cannot be opened directly in the web UI, so display to
            #    the parent path. The path should be url encoded, for example,
            #    '/' should be changed to '%2f'.
            # 2. The web UI cannot show a file directly, so get parent folder
            #    here.
            if not self.runbook.use_sas_url:
                parent_log_path = "/".join(message.log_file.split("/")[:-1])
                sub_path = quote(f"/{parent_log_path}", safe="")
                log_file = f"{base_url}{sub_path}"
            else:
                remote_file_relative_path = PurePosixPath(
                    self._remote_relative_root_path.joinpath(message.log_file)
                )
                sub_path = quote(f"/{message.log_file}", safe="")
                sas_token = generate_user_delegation_sas_token(
                    container_name=self._container_name,
                    credential=self._credential,
                    cloud=AZURE_PUBLIC_CLOUD,
                    account_name=self._storage_account_name,
                    blob_name=str(remote_file_relative_path),
                    expired_hours=self.runbook.sas_token_expired_hours,
                )
                log_file = f"{base_url}{sub_path}?{sas_token}"
        else:
            log_file = base_url
        message.information["storage_log_path"] = log_file

    def __init__(self, runbook: schema.TypedSchema) -> None:
        super().__init__(runbook=runbook)
        self._is_lazy_initialized = False
        self._credential: Any = None

        runbook = cast(LsgStorageSchema, self.runbook)
        assert runbook.subscription_id

        self._subscription_id = runbook.subscription_id
        self._client_id = runbook.client_id
        self._client_secret = runbook.client_secret
        self._tenant_id = runbook.tenant_id
        self._msi_client_id = runbook.msi_client_id
        self._enterprise_app_client_id = runbook.enterprise_app_client_id

        if runbook.resource_group:
            self._resource_group = runbook.resource_group
        else:
            self._resource_group = AZURE_SHARED_RG_NAME
        if runbook.storage_account_name:
            self._storage_account_name = runbook.storage_account_name
        else:
            self._storage_account_name = LsgStorage.get_default_storage_account_name(
                self._subscription_id
            )
        self._container_name = (
            runbook.container_name if runbook.container_name else DEFAULT_CONTAINER_NAME
        )
        self._remote_root_url: str = ""
        self._uploaded_files: Set[Path] = set()

    @retry(tries=60, delay=5)
    def _lazy_initialize(self) -> None:
        if self._is_lazy_initialized:
            return

        # RUN_LOCAL_LOG_PATH path is of the form
        # <repo_root>\runtime\log\<date>\<timestamp>
        # root_path_relative_container path is of the form
        # <test_project>_<test_pass>\<date>\<timestamp> Example: If
        # RUN_LOCAL_LOG_PATH is
        # D:\lsg-lisa\runtime\log\20210406\20210406-032550-027 then
        # root_path_relative_container is
        # default_default\20210406\20210406-032550-027
        self._root_path_absolute_local: Path = Path(constants.RUN_LOCAL_LOG_PATH)
        self._root_path_relative_local: Path = (
            self._root_path_absolute_local.relative_to(
                self._root_path_absolute_local.parent.parent
            )
        )

        cert_path = os.environ.get("AZURE_CLIENT_CERTIFICATE_PATH", "")
        if self.runbook.use_typed_credential:
            self._log.info("Authenticating using cert")
            cred_factory = subclasses.Factory[AzureCredential](AzureCredential)
            azure_cred_instance = cred_factory.create_by_runbook(
                runbook=self.runbook.azure_credential
            )
            self._credential = azure_cred_instance.get_credential(self._log)
        elif cert_path:
            self._client_id = os.environ.get("AZURE_CLIENT_ID", "")
            self._tenant_id = os.environ.get("LISA_storage_tenant_id", "")
            self._log.info(f"Authenticating using cert: {cert_path}...")
            self._credential = CertificateCredential(
                tenant_id=self._tenant_id,
                client_id=self._client_id,
                certificate_path=cert_path,
            )
        elif self._client_id:
            assert (
                self._tenant_id
            ), "tenant id shouldn't be none if client id is specified"
            assert (
                self._client_secret
            ), "client secret shouldn't be none if client id is specified"
            self._log.info("Authenticating using ClientSecretCredential...")
            self._credential = ClientSecretCredential(
                client_id=self._client_id,
                client_secret=self._client_secret,
                tenant_id=self._tenant_id,
            )
        # msi_client_id, enterprise_app_client_id and tenant_id are required for
        # Cross-Tenant auth scenario. Tenant_Id is the tenant where the resource exists
        elif self._msi_client_id and self._enterprise_app_client_id and self._tenant_id:
            self._log.info("Authenticating using ClientAssertionCredential...")
            self._credential = get_cross_tenant_credential(
                msi_client_id=self._msi_client_id,
                enterprise_app_client_id=self._enterprise_app_client_id,
                tenant_id=self._tenant_id,
            )
        else:
            self._log.info("Authenticating using DefaultAzureCredential...")
            self._credential = DefaultAzureCredential()

        check_or_create_resource_group(
            self._credential,
            self._subscription_id,
            AZURE_PUBLIC_CLOUD,
            self._resource_group,
            DEFAULT_LOCATION,
            self._log,
        )

        check_or_create_storage_account(
            self._credential,
            self._subscription_id,
            AZURE_PUBLIC_CLOUD,
            self._storage_account_name,
            self._resource_group,
            DEFAULT_LOCATION,
            self._log,
        )
        self._container_client = get_or_create_storage_container(
            credential=self._credential,
            cloud=AZURE_PUBLIC_CLOUD,
            account_name=self._storage_account_name,
            container_name=self._container_name,
        )

        plugin_manager.register(self)

        default_remote_relative_root_path: Path = (
            Path(f"{self._test_project_name}_{self._test_pass_name}")
            / self._root_path_relative_local
        )
        self._remote_relative_root_path: Path = self._generate_remote_root_path(
            default_remote_relative_root_path
        )
        self._is_lazy_initialized = True

    def finalize(self) -> None:
        """
        All test done. notifier should release resource,
        or do finalize work, like save to a file.

        Even failed, this method will be called.
        """
        # Initialize if Azure platform failed to start and `INITIALIZED` message
        # was not received
        self._lazy_initialize()

        # Upload the rest log files to storage account
        for root, _, files in os.walk(constants.RUN_LOCAL_LOG_PATH):
            for file in files:
                self._upload_file(Path(root) / file)

    def _subscribed_message_type(self) -> List[Type[messages.MessageBase]]:
        return [
            messages.TestRunMessage,
            PlatformMessage,
            TestResultMessage,
            EnvironmentMessage,
        ]

    def _received_message(self, message: messages.MessageBase) -> None:
        if isinstance(message, messages.TestRunMessage):
            if message.status == messages.TestRunStatus.INITIALIZING:
                self._test_project_name = (
                    message.test_project if message.test_project else DEFAULT_NAME
                )
                self._test_pass_name = (
                    message.test_pass if message.test_pass else DEFAULT_NAME
                )
        elif isinstance(message, PlatformMessage):
            if message.status == PlatformStatus.INITIALIZED:
                self._lazy_initialize()
        elif isinstance(message, EnvironmentMessage):
            self._process_environment_message(message)
        elif isinstance(message, TestResultMessage):
            self._process_test_result(message)
        else:
            raise LisaException("Received unsubscribed message type")

    def _process_test_result(self, message: TestResultMessage) -> None:
        # upload as soon as possible for troubleshooting.
        if message.log_file and message.status in [
            TestStatus.PASSED,
            TestStatus.FAILED,
            TestStatus.SKIPPED,
            TestStatus.ATTEMPTED,
        ]:
            self._upload_file(constants.RUN_LOCAL_LOG_PATH / message.log_file)

    def _process_environment_message(self, message: EnvironmentMessage) -> None:
        self._lazy_initialize()
        if message.status == EnvironmentStatus.Deleted:
            log_folder = constants.RUN_LOCAL_LOG_PATH / message.log_folder
            for root, _, files in os.walk(log_folder):
                for file in files:
                    self._upload_file(Path(root) / file)

    @retry(tries=60, delay=5)
    def _upload_file(self, local_file_path: Path) -> None:
        # Example: If file_path_absolute_local is
        # D:\lsg-lisa\runtime\log\20210406\20210406-032550-027\lisa.html
        # then file_path_relative_container is
        # default_default\20210406\20210406-032550-027\lisa.html
        local_absolute_file_path = local_file_path.absolute()
        local_relative_file_path = local_absolute_file_path.relative_to(
            constants.RUN_LOCAL_LOG_PATH
        )

        # The file is uploaded already, skip.
        if local_absolute_file_path in self._uploaded_files:
            return

        self._log.debug(f"Uploading file {local_absolute_file_path} to storage account")
        remote_file_path = self._remote_relative_root_path / local_relative_file_path
        with local_absolute_file_path.open("rb") as data:
            self._container_client.upload_blob(
                name=str(remote_file_path),
                data=data,
                overwrite=True,
            )

        self._uploaded_files.add(local_absolute_file_path)

    def _generate_remote_root_path(self, default_path: Path) -> Path:
        times = 0
        # Check if blobs exists on container path
        # try 10 times, to avoid conflict folder name.
        established_path = default_path
        while times < 10:
            exists = False
            blobs_iter = self._container_client.list_blobs(
                name_starts_with=str(sanitize_filepath(established_path))
            )
            for _ in blobs_iter:
                exists = True
                break
            if not exists:
                break
            times += 1
            # use a new path, if it exists.
            established_path = Path(f"{default_path}_{times}")
        if exists:
            raise LisaException(
                f"Path {default_path} already exists on"
                f" account_name: {self._storage_account_name}"
                f"and container_name:{self._container_name}"
            )
        return established_path

    def _get_remote_root_url(self) -> str:
        if self._remote_root_url:
            return self._remote_root_url

        storage_client = StorageManagementClient(
            self._credential, self._subscription_id
        )
        storage_account = storage_client.storage_accounts.get_properties(
            self._resource_group, self._storage_account_name
        )
        id_format = quote(storage_account.id, safe="")
        sanitized_path = (
            f"{self._container_name}/"
            f"{sanitize_filepath(str(self._remote_relative_root_path))}"
        )
        path_format = quote(sanitized_path, safe="")
        if not self.runbook.use_sas_url:
            self._remote_root_url = (
                f"{AZURE_STORAGE_ACCOUNT_PREFIX}/{id_format}/path/{path_format}"
            )
        else:
            prefix = f"https://{self._storage_account_name}.blob.core.windows.net"
            self._remote_root_url = f"{prefix}/{path_format}"

        return self._remote_root_url
