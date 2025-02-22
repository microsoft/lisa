import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Type, cast

from azure.identity import (
    CertificateCredential,
    ClientAssertionCredential,
    ClientSecretCredential,
    DefaultAzureCredential,
    ManagedIdentityCredential,
)
from dataclasses_json import dataclass_json
from msrestazure.azure_cloud import AZURE_PUBLIC_CLOUD, Cloud  # type: ignore

from lisa import schema, secret
from lisa.util import constants, subclasses
from lisa.util.logger import Logger


class AzureCredentialType(str, Enum):
    DefaultAzureCredential = constants.DEFAULT_AZURE_CREDENTIAL
    CertificateCredential = constants.CERTIFICATE_CREDENTIAL
    ClientAssertionCredential = constants.CLIENT_ASSERTION_CREDENTIAL
    ClientSecretCredential = constants.CLIENT_SECRET_CREDENTIAL


@dataclass_json()
@dataclass
class AzureCredentialSchema(schema.TypedSchema, schema.ExtendableSchemaMixin):
    type: str = AzureCredentialType.DefaultAzureCredential
    tenant_id: str = ""
    client_id: str = ""


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
            self._credential_type = AzureCredentialType.DefaultAzureCredential

        self._log.debug(f"Credential type: {self._credential_type}")
        self._cloud = cloud

        # parameters overwrite seq: env var <- runbook <- cmd
        self._tenant_id = os.environ.get("AZURE_TENANT_ID", "")
        self._client_id = os.environ.get("AZURE_CLIENT_ID", "")

        assert runbook, "azure_credential shouldn't be empty"
        if runbook.tenant_id:
            self._tenant_id = runbook.tenant_id
        if runbook.client_id:
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

    def __hash__(self) -> int:
        return hash(self._get_key())

    def get_credential(self) -> Any:
        """
        return AzureCredential with related schema
        """
        return DefaultAzureCredential(cloud=self._cloud)

    def _get_key(self) -> str:
        return f"{self._credential_type}_{self._client_id}_{self._tenant_id}"


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
        self._cert_path = os.environ.get("AZURE_CLIENT_CERTIFICATE_PATH", "")
        self._client_send_cert_chain = "false"

        runbook = cast(CertCredentialSchema, self.runbook)
        self._credential_type = AzureCredentialType.CertificateCredential
        if runbook.cert_path:
            self._cert_path = runbook.cert_path
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
        return constants.CLIENT_ASSERTION_CREDENTIAL

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
        self._credential_type = AzureCredentialType.ClientAssertionCredential

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
        return constants.CLIENT_SECRET_CREDENTIAL

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
        self._credential_type = AzureCredentialType.ClientSecretCredential
        self._client_secret = os.environ.get("AZURE_CLIENT_SECRET", "")

        runbook = cast(ClientSecretCredentialSchema, self.runbook)
        if runbook.client_id:
            self._client_id = runbook.client_id
        if runbook.tenant_id:
            self._tenant_id = runbook.tenant_id
        if runbook.client_secret:
            self._client_secret = runbook.client_secret

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

    def get_credential(self, log: Logger) -> Any:
        log.info("Authenticating using ClientSecretCredential")
        return self.get_client_secret_credential(
            self._tenant_id, self._client_id, self._client_secret
        )
