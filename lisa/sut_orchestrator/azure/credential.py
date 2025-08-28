import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Type, cast

from azure.identity import (
    AzureCliCredential,
    CertificateCredential,
    ClientAssertionCredential,
    ClientSecretCredential,
    DefaultAzureCredential,
    ManagedIdentityCredential,
    WorkloadIdentityCredential,
)
from dataclasses_json import dataclass_json
from msrestazure.azure_cloud import AZURE_PUBLIC_CLOUD, Cloud

from lisa import schema, secret
from lisa.util import subclasses
from lisa.util.logger import Logger

from .common import get_static_access_token


class AzureCredentialType(str, Enum):
    DefaultAzureCredential = "default"
    CertificateCredential = "certificate"
    ClientAssertionCredential = "assertion"
    ClientSecretCredential = "secret"
    WorkloadIdentityCredential = "workloadidentity"
    TokenCredential = "token"
    AzCliCredential = "azcli"


@dataclass_json()
@dataclass
class AzureCredentialSchema(schema.TypedSchema, schema.ExtendableSchemaMixin):
    type: str = AzureCredentialType.DefaultAzureCredential
    tenant_id: str = ""
    client_id: str = ""
    allow_all_tenants: bool = True


@dataclass_json()
@dataclass
class CertCredentialSchema(AzureCredentialSchema):
    cert_path: str = ""
    client_send_cert_chain = "false"


@dataclass_json()
@dataclass
class ClientAssertionCredentialSchema(AzureCredentialSchema):
    msi_client_id: str = ""
    enterprise_app_client_id: str = ""


@dataclass_json()
@dataclass
class ClientSecretCredentialSchema(AzureCredentialSchema):
    # for ClientSecretCredential, will be deprecated due to Security WAVE
    client_secret: str = ""

    def __post_init__(self) -> None:
        assert self.client_secret, "client_secret shouldn't be empty"
        secret.add_secret(self.client_secret)


@dataclass_json()
@dataclass
class TokenCredentialSchema(AzureCredentialSchema):
    token: str = ""

    def __post_init__(self) -> None:
        assert self.token, "token shouldn't be empty"
        secret.add_secret(self.token)


class AzureCredential(subclasses.BaseClassWithRunbookMixin):
    """
    Base Class for creating azure credential based on runbook Schema
    """

    @classmethod
    def type_name(cls) -> str:
        raise NotImplementedError()

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        raise NotImplementedError()

    def __init__(
        self,
        runbook: AzureCredentialSchema,
        logger: Logger,
        cloud: Cloud = AZURE_PUBLIC_CLOUD,
    ) -> None:
        super().__init__(runbook=runbook)
        self._log = logger

        if runbook.type:
            self._credential_type = runbook.type
        else:
            self._credential_type = AzureCredentialType.DefaultAzureCredential  # CodeQL [SM05139] Okay use of DefaultAzureCredential as it is only used in development # noqa E501

        self._log.debug(f"Credential type: {self._credential_type}")
        self._cloud = cloud

        # parameters overwrite seq: env var <- runbook <- cmd
        self._tenant_id = os.environ.get("AZURE_TENANT_ID", "")
        self._client_id = os.environ.get("AZURE_CLIENT_ID", "")
        self._allow_all_tenants = False

        assert runbook, "azure_credential shouldn't be empty"
        if runbook.tenant_id:
            self._tenant_id = runbook.tenant_id
            self._log.debug(f"Use defined tenant id: {self._tenant_id}")
        if runbook.client_id:
            self._client_id = runbook.client_id
            self._log.debug(f"Use defined client id: {self._client_id}")

        self._allow_all_tenants = runbook.allow_all_tenants

    def _set_auth_env_variables(self) -> None:
        if self._tenant_id:
            os.environ["AZURE_TENANT_ID"] = self._tenant_id
        if self._client_id:
            os.environ["AZURE_CLIENT_ID"] = self._client_id

    def __hash__(self) -> int:
        return hash(self._get_key())

    def get_credential(self) -> Any:
        raise NotImplementedError()

    def _get_key(self) -> str:
        return f"{self._credential_type}_{self._client_id}_{self._tenant_id}"


class AzureDefaultCredential(AzureCredential):
    """
    Class to create DefaultAzureCredential based on runbook Schema. Because the
    subclass factory doesn't instance the base class, so create a subclass to be
    instanced.
    """

    @classmethod
    def type_name(cls) -> str:
        return AzureCredentialType.DefaultAzureCredential

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return AzureCredentialSchema

    def __init__(
        self,
        runbook: AzureCredentialSchema,
        logger: Logger,
        cloud: Cloud = AZURE_PUBLIC_CLOUD,
    ) -> None:
        super().__init__(runbook, logger=logger, cloud=cloud)
        self._set_auth_env_variables()

    def __hash__(self) -> int:
        return hash(self._get_key())

    def get_credential(self) -> Any:
        """
        return AzureCredential with related schema
        """
        additional_tenants = ["*"] if self._allow_all_tenants else None
        return DefaultAzureCredential(
            cloud=self._cloud,
            additionally_allowed_tenants=additional_tenants,
        )

    def _get_key(self) -> str:
        return f"{self._credential_type}_{self._client_id}_{self._tenant_id}"


class AzureWorkloadIdentityCredential(AzureCredential):
    """
    Class to create azure WorkloadIdentityCredential
    """

    @classmethod
    def type_name(cls) -> str:
        return AzureCredentialType.WorkloadIdentityCredential

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return AzureCredentialSchema

    def get_credential(self) -> Any:
        self._log.info("Authenticating Using WorkloadIdentityCredential")
        additional_tenants = ["*"] if self._allow_all_tenants else None
        return WorkloadIdentityCredential(
            tenant_id=self._tenant_id,
            client_id=self._client_id,
            additionally_allowed_tenants=additional_tenants,
        )


class AzureCertificateCredential(AzureCredential):
    """
    Class to create azure credential based on runbook AzureCredentialSchema.
    """

    @classmethod
    def type_name(cls) -> str:
        return AzureCredentialType.CertificateCredential

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return CertCredentialSchema

    def __init__(
        self,
        runbook: CertCredentialSchema,
        logger: Logger,
        cloud: Cloud = AZURE_PUBLIC_CLOUD,
    ) -> None:
        super().__init__(runbook, cloud=cloud, logger=logger)
        self._set_auth_env_variables()
        self._cert_path = os.environ.get("AZURE_CLIENT_CERTIFICATE_PATH", "")
        self._client_send_cert_chain = "false"

        runbook = cast(CertCredentialSchema, self.runbook)
        if runbook.cert_path:
            self._cert_path = runbook.cert_path
            self._log.debug(f"Use defined cert path: {self._cert_path}")
            os.environ["AZURE_CLIENT_CERTIFICATE_PATH"] = self._cert_path
        if runbook.client_send_cert_chain:
            self._client_send_cert_chain = runbook.client_send_cert_chain

    def get_credential(self) -> Any:
        self._log.info(f"Authenticating using cert path: {self._cert_path}")

        assert self._tenant_id, "tenant id shouldn't be none for CertificateCredential"
        assert self._client_id, "client id shouldn't be none for CertificateCredential"
        assert self._cert_path, "cert path shouldn't be none for CertificateCredential"

        return CertificateCredential(
            tenant_id=self._tenant_id,
            client_id=self._client_id,
            certificate_path=self._cert_path,
            send_certificate_chain=self._client_send_cert_chain,
        )


class AzureClientAssertionCredential(AzureCredential):
    """
    Class to Create ClientAssertionCredential based on runbook Schema.
    """

    @classmethod
    def type_name(cls) -> str:
        return AzureCredentialType.ClientAssertionCredential

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return ClientAssertionCredentialSchema

    def __init__(
        self,
        runbook: ClientAssertionCredentialSchema,
        logger: Logger,
        cloud: Cloud = AZURE_PUBLIC_CLOUD,
    ) -> None:
        if runbook:
            super().__init__(runbook, cloud=cloud, logger=logger)
        self._msi_client_id = ""
        self._enterprise_app_client_id = ""

        runbook = cast(ClientAssertionCredentialSchema, self.runbook)
        if runbook.msi_client_id:
            self._msi_client_id = runbook.msi_client_id
        if runbook.enterprise_app_client_id:
            self._enterprise_app_client_id = runbook.enterprise_app_client_id

    def _get_managed_identity_token(self, msi_client_id: str, audience: str) -> str:
        credential = ManagedIdentityCredential(client_id=msi_client_id)
        return credential.get_token(audience).token  # type: ignore

    def get_cross_tenant_credential(
        self, msi_client_id: str, enterprise_app_client_id: str, tenant_id: str
    ) -> ClientAssertionCredential:
        assert tenant_id, "tenant_id shouldn't be none for ClientAssertionCredential"
        assert (
            msi_client_id
        ), "msi_client_id shouldn't be none for ClientAssertionCredential"
        assert (
            enterprise_app_client_id
        ), "enterprise_app_client_id shouldn't be non for ClientAssertionCredential"

        audience = "api://AzureADTokenExchange"
        credential = ClientAssertionCredential(
            tenant_id=tenant_id,
            client_id=enterprise_app_client_id,
            func=lambda: self._get_managed_identity_token(msi_client_id, audience),
        )
        return credential

    def get_credential(self) -> Any:
        self._log.info("Authenticating using ClientAssertionCredential")
        return self.get_cross_tenant_credential(
            self._msi_client_id, self._enterprise_app_client_id, self._tenant_id
        )


class AzureClientSecretCredential(AzureCredential):
    """
    Class to create ClientSecretCredential based on runbook Schema
    Methods:
        get_credential(self) -> Any:
            return the credential based on runbook Schema define.
    """

    @classmethod
    def type_name(cls) -> str:
        return AzureCredentialType.ClientSecretCredential

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return ClientSecretCredentialSchema

    def __init__(
        self,
        runbook: ClientSecretCredentialSchema,
        logger: Logger,
        cloud: Cloud = AZURE_PUBLIC_CLOUD,
    ) -> None:
        super().__init__(runbook, cloud=cloud, logger=logger)
        self._set_auth_env_variables()
        self._client_secret = os.environ.get("AZURE_CLIENT_SECRET", "")

        runbook = cast(ClientSecretCredentialSchema, self.runbook)
        if runbook.client_secret:
            self._client_secret = runbook.client_secret
            self._log.debug(
                f"Use defined client secret: ({len(self._client_secret)} bytes)"
            )
            os.environ["AZURE_CLIENT_SECRET"] = self._client_secret

    def get_client_secret_credential(
        self, tenant_id: str, client_id: str, client_secret: str
    ) -> ClientSecretCredential:
        """
        get ClientSecretCredential, will be deprecated in Security WAVE
        """
        assert tenant_id, "tenant id shouldn't be none for ClientSecretCredential"
        assert client_id, "client id shouldn't be none for ClientSecretCredential"
        assert (
            client_secret
        ), "client_secret shouldn't be None for ClientSecretCredential"

        return ClientSecretCredential(
            tenant_id=tenant_id, client_id=client_id, client_secret=client_secret
        )

    def get_credential(self) -> Any:
        self._log.info("Authenticating using ClientSecretCredential")
        return self.get_client_secret_credential(
            self._tenant_id, self._client_id, self._client_secret
        )


class AzureTokenCredential(AzureCredential):
    """
    Class to create azure credential based on preappled tokens
    """

    @classmethod
    def type_name(cls) -> str:
        return AzureCredentialType.TokenCredential

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return TokenCredentialSchema

    def __init__(
        self,
        runbook: TokenCredentialSchema,
        logger: Logger,
        cloud: Cloud = AZURE_PUBLIC_CLOUD,
    ) -> None:
        super().__init__(runbook, cloud=cloud, logger=logger)
        self._token = runbook.token

    def get_credential(self) -> Any:
        return get_static_access_token(self._token)


class AzureCliCredentialImpl(AzureCredential):
    """
    Class to create AzureCliCredential based on runbook Schema. Uses Azure CLI
    for authentication which requires logging in to Azure via "az login" first.
    """

    @classmethod
    def type_name(cls) -> str:
        return AzureCredentialType.AzCliCredential

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return AzureCredentialSchema

    def __init__(
        self,
        runbook: AzureCredentialSchema,
        logger: Logger,
        cloud: Cloud = AZURE_PUBLIC_CLOUD,
    ) -> None:
        super().__init__(runbook, logger=logger, cloud=cloud)

    def get_credential(self) -> Any:
        """
        return AzureCliCredential for authentication
        """
        self._log.info("Authenticating using AzureCliCredential")

        # Determine additionally_allowed_tenants based on allow_all_tenants setting
        additionally_allowed_tenants = ["*"] if self._allow_all_tenants else None

        # Create AzureCliCredential with proper parameter types
        return AzureCliCredential(
            tenant_id=self._tenant_id,
            additionally_allowed_tenants=additionally_allowed_tenants,
        )
