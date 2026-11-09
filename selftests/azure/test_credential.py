# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase
from unittest.mock import MagicMock, patch

from azure.core.credentials import AccessToken
from azure.core.exceptions import ClientAuthenticationError
from azure.identity import AzureCliCredential, DefaultAzureCredential

from lisa.sut_orchestrator.azure.credential import (
    AzureCliCredentialImpl,
    AzureCredentialSchema,
    AzureDefaultCredential,
)


class AzureCredentialTestCase(TestCase):
    def test_cli_invocation_recovers_without_changing_identity(self) -> None:
        for factory, sdk_type in (
            (AzureDefaultCredential, DefaultAzureCredential),
            (AzureCliCredentialImpl, AzureCliCredential),
        ):
            for message in (
                "Failed to invoke Azure CLI",
                "Failed to invoke the Azure CLI",
            ):
                with self.subTest(factory=factory.__name__, message=message):
                    logger = MagicMock()
                    credential = factory(
                        AzureCredentialSchema(), logger=logger
                    ).get_credential()
                    first = AccessToken("first-token", 100)
                    refreshed = AccessToken("refreshed-token", 200)
                    with patch.object(
                        sdk_type,
                        "get_token",
                        side_effect=[
                            first,
                            ClientAuthenticationError(message=message),
                            refreshed,
                        ],
                    ) as get_token, patch(
                        "lisa.sut_orchestrator.azure.credential.time.sleep"
                    ) as sleep:
                        self.assertIs(
                            first, credential.get_token("scope", tenant_id="tenant")
                        )
                        self.assertIs(
                            refreshed, credential.get_token("scope", tenant_id="tenant")
                        )
                        self.assertEqual(3, get_token.call_count)
                        get_token.assert_called_with("scope", tenant_id="tenant")
                        sleep.assert_called_once_with(5)
                    logger.warning.assert_called_once()
                    logger.error.assert_not_called()
                    credential.close()

    def test_cli_invocation_failure_is_bounded_and_propagates(self) -> None:
        logger = MagicMock()
        credential = AzureCliCredentialImpl(
            AzureCredentialSchema(), logger=logger
        ).get_credential()
        failure = ClientAuthenticationError(message="Failed to invoke Azure CLI")
        with patch.object(
            AzureCliCredential, "get_token", side_effect=failure
        ) as get_token, patch(
            "lisa.sut_orchestrator.azure.credential.time.sleep"
        ) as sleep:
            with self.assertRaises(ClientAuthenticationError) as raised:
                credential.get_token("scope")
            self.assertIs(failure, raised.exception)
            self.assertEqual(3, get_token.call_count)
            self.assertEqual(2, sleep.call_count)
        logger.error.assert_called_once()
        credential.close()

    def test_explicit_authentication_failures_are_not_retried(self) -> None:
        for message in (
            "Please run 'az login' to set up an account",
            "AADSTS700082: The refresh token has expired",
            "The client does not have authorization to perform this action",
        ):
            with self.subTest(message=message):
                logger = MagicMock()
                credential = AzureCliCredentialImpl(
                    AzureCredentialSchema(), logger=logger
                ).get_credential()
                failure = ClientAuthenticationError(message=message)
                with patch.object(
                    AzureCliCredential, "get_token", side_effect=failure
                ) as get_token, patch(
                    "lisa.sut_orchestrator.azure.credential.time.sleep"
                ) as sleep:
                    with self.assertRaises(ClientAuthenticationError) as raised:
                        credential.get_token("scope")
                    self.assertIs(failure, raised.exception)
                    get_token.assert_called_once_with("scope")
                    sleep.assert_not_called()
                logger.warning.assert_not_called()
                credential.close()
