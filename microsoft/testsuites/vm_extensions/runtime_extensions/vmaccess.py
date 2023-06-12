# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Dict, Optional

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import BSD
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.features import AzureExtension


def _validate_password(
    node: Node, username: str, password: str, valid: bool = True
) -> None:
    # simple command to determine if username password combination is valid/invalid
    node.execute(
        cmd=f'echo "{password}" | su --command true - {username}',
        shell=True,
        expected_exit_code=0 if valid else 1,
        expected_exit_code_failure_message=f"Password not set as intended for user {username}.",
    )


def _validate_ssh_key_exists(node: Node, username: str, exists: bool = True) -> None:
    # Command checks whether the authorized_keys file is created and has the correct format
    node.execute(
        cmd=f"ssh-keygen -l -f /home/{username}/.ssh/authorized_keys",
        shell=True,
        sudo=True,
        expected_exit_code=0 if exists else 255,
        expected_exit_code_failure_message=f"Public key file for user {username} {'does not exist' if 0 else 'exists'}.",
    )


def _validate_account_expiration_date(
    node: Node, username: str, expiration_str: str
) -> None:
    # Command checks whether the account expiration specified is correct
    result = node.execute(
        cmd=f"chage -l {username}",
        shell=True,
        sudo=True,
        expected_exit_code=0,
        expected_exit_code_failure_message=f"Cannot retrieve account details for user {username}",
    )

    assert_that(result.stdout).described_as(
        f"Expected the account details to contain expiration date of {expiration_str}"
    ).contains(expiration_str)


def _create_and_verify_extension_run(
    node: Node,
    settings: Optional[Dict[str, Any]] = None,
    protected_settings: Optional[Dict[str, Any]] = None,
) -> None:
    extension = node.features[AzureExtension]
    result = extension.create_or_update(
        name="VMAccess",
        publisher="Microsoft.OSTCExtensions",
        type_="VMAccessForLinux",
        type_handler_version="1.5",
        auto_upgrade_minor_version=True,
        settings=settings or {},
        protected_settings=protected_settings or {},
    )

    assert_that(result["provisioning_state"]).described_as(
        "Expected the extension to succeed"
    ).is_equal_to("Succeeded")


@TestSuiteMetadata(
    area="vm_extensions",
    category="functional",
    description="""
    This test suite tests the functionality of the VMAccess VM extension.

    Settings are protected unless otherwise mentioned.
    OpenSSH format public keys correspond to ssh-rsa keys.

    It has 8 test cases to verify if VMAccess runs successfully when provided:
        1. Username and password
        2. Username and OpenSSH format public key
        3. Username with both a password and OpenSSH format public key
        4. Username with no password or ssh key (should fail)
        5. Username and certificate containing public ssh key in pem format
        6. Username and SSH2 format public key
        7. Username to remove
        8. Username, OpenSSH format public key, and valid expiration date
    """,
    requirement=simple_requirement(
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
        unsupported_os=[BSD],
    ),
)
class VMAccessTests(TestSuite):
    _OPENSSH_KEY = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDNCPG1FxE2r/OOMCiUfUSuj6FdI9vg4VBExCZ8k1MPLMy8w9mhPOCi3cb7bJ25MCwidsM9vKGJHVAHwcJseAGhYRCBBzO7xhlosP6Kc6MJGFF/5OsODGd9gB2zqsrmF1hCpcQuBB8++4DBBFcQQuJRfXRBYBvYN2xROd5Z3eJ/928TLLendbNOGlZUYoZT5bDGOUkNPu6x7BAwkuqaltF0MAgMEZRAg0Js17N/h8vVrEP1tCRfieC4TOvAP6PQtPlacjgTdYNg7ophVphyhwvS12oUpBlpAC0gTLOyUluxEoC83mxmN3+UNxf9kdj+Uhg2oHk6S+cqHblpRI2KXqcB"
    _CERT_SSH_KEY = """\
-----BEGIN CERTIFICATE-----
MIICOTCCAaICCQD7F0nb+GtpcTANBgkqhkiG9w0BAQsFADBhMQswCQYDVQQGEwJh
YjELMAkGA1UECAwCYWIxCzAJBgNVBAcMAmFiMQswCQYDVQQKDAJhYjELMAkGA1UE
CwwCYWIxCzAJBgNVBAMMAmFiMREwDwYJKoZIhvcNAQkBFgJhYjAeFw0xNDA4MDUw
ODIwNDZaFw0xNTA4MDUwODIwNDZaMGExCzAJBgNVBAYTAmFiMQswCQYDVQQIDAJh
YjELMAkGA1UEBwwCYWIxCzAJBgNVBAoMAmFiMQswCQYDVQQLDAJhYjELMAkGA1UE
AwwCYWIxETAPBgkqhkiG9w0BCQEWAmFiMIGfMA0GCSqGSIb3DQEBAQUAA4GNADCB
iQKBgQC4Vugyj4uAKGYHW/D1eAg1DmLAv01e+9I0zIi8HzJxP87MXmS8EdG5SEzR
N6tfQQie76JBSTYI4ngTaVCKx5dVT93LiWxLV193Q3vs/HtwwH1fLq0rAKUhREQ6
+CsRGNyeVfJkNsxAvNvQkectnYuOtcDxX5n/25eWAofobxVbSQIDAQABMA0GCSqG
SIb3DQEBCwUAA4GBAF20gkq/DeUSXkZA+jjmmbCPioB3KL63GpoTXfP65d6yU4xZ
TlMoLkqGKe3WoXmhjaTOssulgDAGA24IeWy/u7luH+oHdZEmEufFhj4M7tQ1pAhN
CT8JCL2dI3F76HD6ZutTOkwRar3PYk5q7RsSJdAemtnwVpgp+RBMtbmct7MQ
-----END CERTIFICATE-----
"""
    _SSH2_KEY = """\
---- BEGIN SSH2 PUBLIC KEY ----
Comment: "rsa-key-20230508"
AAAAB3NzaC1yc2EAAAADAQABAAABAQDNCPG1FxE2r/OOMCiUfUSuj6FdI9vg4VBE
xCZ8k1MPLMy8w9mhPOCi3cb7bJ25MCwidsM9vKGJHVAHwcJseAGhYRCBBzO7xhlo
sP6Kc6MJGFF/5OsODGd9gB2zqsrmF1hCpcQuBB8++4DBBFcQQuJRfXRBYBvYN2xR
Od5Z3eJ/928TLLendbNOGlZUYoZT5bDGOUkNPu6x7BAwkuqaltF0MAgMEZRAg0Js
17N/h8vVrEP1tCRfieC4TOvAP6PQtPlacjgTdYNg7ophVphyhwvS12oUpBlpAC0g
TLOyUluxEoC83mxmN3+UNxf9kdj+Uhg2oHk6S+cqHblpRI2KXqcB
---- END SSH2 PUBLIC KEY ----
"""

    # @TestCaseMetadata(
    #     description="""
    #     Runs the VMAccess VM extension with a valid username and password.
    #     """,
    #     priority=3,
    # )
    # def verify_valid_password_run(self, log: Logger, node: Node) -> None:
    #     username = "vmaccessuser"
    #     password = "vmaccesspassword"
    #     incorrect_password = "vmaccesspassword1"
    #     protected_settings = {
    #         "username": username,
    #         "password": password,
    #     }

    #     _create_and_verify_extension_run(
    #         node=node, protected_settings=protected_settings
    #     )
    #     _validate_password(node=node, username=username, password=password)
    #     _validate_password(
    #         node=node, username=username, password=incorrect_password, valid=False
    #     )

    # @TestCaseMetadata(
    #     description="""
    #     Runs the VMAccess VM extension with an OpenSSH public key.
    #     """,
    #     priority=3,
    # )
    # def verify_openssh_key_run(self, log: Logger, node: Node) -> None:
    #     username = "vmaccessuser"
    #     protected_settings = {"username": username, "ssh_key": self._OPENSSH_KEY}

    #     _create_and_verify_extension_run(
    #         node=node, protected_settings=protected_settings
    #     )
    #     _validate_ssh_key_exists(node=node, username=username)

    # @TestCaseMetadata(
    #     description="""
    #     Runs the VMAccess VM extension with both a password and OpenSSH public key.
    #     """,
    #     priority=3,
    # )
    # def verify_password_and_ssh_key_run(self, log: Logger, node: Node) -> None:
    #     username = "vmaccessuser"
    #     password = "vmaccesspassword"
    #     protected_settings = {
    #         "username": username,
    #         "ssh_key": self._OPENSSH_KEY,
    #         "password": password,
    #     }

    #     _create_and_verify_extension_run(
    #         node=node, protected_settings=protected_settings
    #     )
    #     # Expecting both password and ssh key to be created as intended
    #     _validate_ssh_key_exists(node=node, username=username)
    #     _validate_password(node=node, username=username, password=password)

    # @TestCaseMetadata(
    #     description="""
    #     Runs the VMAccess VM extension without a password and OpenSSH public key.
    #     """,
    #     priority=3,
    # )
    # def verify_no_password_and_ssh_key_run_failed(
    #     self, log: Logger, node: Node
    # ) -> None:
    #     username = "vmaccessuser"
    #     password = "vmaccesspassword"
    #     protected_settings = {"username": username}

    #     _create_and_verify_extension_run(
    #         node=node, protected_settings=protected_settings
    #     )
    #     # Expecting no ssh keys and password to exist for this user
    #     _validate_ssh_key_exists(node=node, username=username, exists=False)
    #     _validate_password(node=node, username=username, password=password, valid=False)

    # @TestCaseMetadata(
    #     description="""
    #     Runs the VMAccess VM extension with a certificate containing a public ssh key
    #     in pem format.
    #     """,
    #     priority=3,
    # )
    # def verify_pem_certificate_ssh_key_run(self, log: Logger, node: Node) -> None:
    #     username = "vmaccessuser"
    #     protected_settings = {"username": username, "ssh_key": self._CERT_SSH_KEY}

    #     _create_and_verify_extension_run(
    #         node=node, protected_settings=protected_settings
    #     )
    #     _validate_ssh_key_exists(node=node, username=username)

    # @TestCaseMetadata(
    #     description="""
    #     Runs the VMAccess VM extension with an SSH2 public key.
    #     """,
    #     priority=3,
    # )
    # def verify_ssh2_key_run(self, log: Logger, node: Node) -> None:
    #     username = "vmaccessuser"
    #     protected_settings = {"username": username, "ssh_key": self._SSH2_KEY}

    #     _create_and_verify_extension_run(
    #         node=node, protected_settings=protected_settings
    #     )
    #     _validate_ssh_key_exists(node=node, username=username)

    # @TestCaseMetadata(
    #     description="""
    #     Runs the VMAccess VM extension with a username to remove.
    #     """,
    #     priority=3,
    # )
    # def verify_remove_username_run(self, log: Logger, node: Node) -> None:
    #     username = "vmaccessuser"
    #     password = "vmaccesspassword"
    #     protected_settings = {"username": username, "password": password}

    #     _create_and_verify_extension_run(
    #         node=node, protected_settings=protected_settings
    #     )
    #     _validate_password(node=node, username=username, password=password)

    #     protected_settings = {"remove_user": username}

    #     _create_and_verify_extension_run(
    #         node=node, protected_settings=protected_settings
    #     )
    #     _validate_password(node=node, username=username, password=password, valid=False)

    @TestCaseMetadata(
        description="""
        Runs the VMAccess VM extension with an OpenSSH public key and valid expiration date.
        """,
        priority=3,
    )
    def verify_valid_expiration_run(self, log: Logger, node: Node) -> None:
        username = "vmaccessuser"
        protected_settings = {
            "username": username,
            "ssh_key": self._OPENSSH_KEY,
            "expiration": "2030-01-01",
        }

        _create_and_verify_extension_run(
            node=node, protected_settings=protected_settings
        )
        _validate_ssh_key_exists(node=node, username=username)
        _validate_account_expiration_date(
            node=node, username=username, expiration_str="Jan 01, 2030"
        )
