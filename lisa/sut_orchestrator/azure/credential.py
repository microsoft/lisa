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

from lisa import schema
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
    tenant_id: str = ""
    client_id: str = ""
    type: str = AzureCredentialType.DefaultAzureCredential


@dataclass_json()
@dataclass
class CertCredentialSchema(AzureCredentialSchema):
    cert_path: str = ""
    client_send_cert_chain = "false"
    type: str = AzureCredentialType.CertificateCredential


@dataclass_json()
@dataclass
class ClientAssertionCredentialSchema(AzureCredentialSchema):
    msi_client_id: str = ""
    enterprise_app_client_id: str = ""
    type: str = AzureCredentialType.ClientAssertionCredential


@dataclass_json()
@dataclass
class ClientSecretCredentialSchema(AzureCredentialSchema):
    # for ClientSecretCredential, will be deprecated due to Security WAVE
    client_secret: str = ""
    type: str = AzureCredentialType.ClientSecretCredential


class AzureCredential(subclasses.BaseClassWithRunbookMixin):
    """
    Base Class for creating azure credential based on runbook Schema
    """

    @classmethod
    def type_name(cls) -> str:
        return constants.DEFAULT_AZURE_CREDENTIAL

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return AzureCredentialSchema

    def __init__(self, runbook: AzureCredentialSchema) -> None:
        super().__init__(runbook=runbook)
        # parameters overwrite seq: env var <- runbook <- cmd
        self._credential_type = AzureCredentialType.DefaultAzureCredential
        self._client_id = os.environ.get("AZURE_CLIENT_ID", "")
        self._tenant_id = os.environ.get("AZURE_TENANT_ID", "")

        assert runbook, "azure_credential shouldn't be empty"
        self._azure_credential = runbook
        if runbook.type:
            self._credential_type = runbook.type
        if runbook.client_id:
            self._client_id = runbook.client_id
        if runbook.tenant_id:
            self._tenant_id = runbook.tenant_id

    def get_credential(self, log: Logger) -> Any:
        """
        return AzureCredential with related schema
        """
        log.info("Authenticating using DefaultAzureCredential")
        return DefaultAzureCredential()


class AzureCertificateCredential(AzureCredential):
    """
    Class to create azure credential based on runbook AzureCredentialSchema.
    Methods:
        get_credential(self, log: Logger) -> Any:
            return the credential based on runbook AzureCredentialSchema define.
    """

    @classmethod
    def type_name(cls) -> str:
        return constants.CERTIFICATE_CREDENTIAL

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return CertCredentialSchema

    def __init__(self, runbook: CertCredentialSchema) -> None:
        super().__init__(runbook)
        self._cert_path = os.environ.get("AZURE_CLIENT_CERTIFICATE_PATH", "")
        self._client_send_cert_chain = "false"

        runbook = cast(CertCredentialSchema, self.runbook)
        self._credential_type = AzureCredentialType.CertificateCredential
        if runbook.cert_path:
            self._cert_path = runbook.cert_path
        if runbook.client_send_cert_chain:
            self._client_send_cert_chain = runbook.client_send_cert_chain

    def get_credential(self, log: Logger) -> Any:
        log.info(f"Authenticating using cert path: {self._cert_path}")

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

    def __init__(self, runbook: ClientAssertionCredentialSchema | None) -> None:
        if runbook:
            super().__init__(runbook)
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

        AUDIENCE = "api://AzureADTokenExchange"
        credential = ClientAssertionCredential(
            tenant_id=tenant_id,
            client_id=enterprise_app_client_id,
            func=lambda: self._get_managed_identity_token(msi_client_id, AUDIENCE),
        )
        return credential

    def get_credential(self, log: Logger) -> Any:
        log.info("Authenticating using ClientAssertionCredential")
        return self.get_cross_tenant_credential(
            self._msi_client_id, self._enterprise_app_client_id, self._tenant_id
        )


class AzureClientSecretCredential(AzureCredential):
    """
    Class to create ClientSecretCredential based on runbook Schema
    Methods:
        get_credential(self, log: Logger) -> Any:
            return the credential based on runbook Schema define.
    """

    @classmethod
    def type_name(cls) -> str:
        return constants.CLIENT_SECRET_CREDENTIAL

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return ClientSecretCredentialSchema

    def __init__(self, runbook: ClientSecretCredentialSchema) -> None:
        super().__init__(runbook)
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
