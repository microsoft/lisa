# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import uuid
from typing import cast

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    RemoteNode,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import BSD, CBLMariner, Ubuntu
from lisa.secret import add_secret
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.tools import Sshpass, Usermod
from lisa.util import generate_random_chars
from microsoft.testsuites.vm_extensions.runtime_extensions.common import (
    create_and_verify_vmaccess_extension_run,
)


def _generate_openssh_key(node: Node, filename: str) -> None:
    node.execute(
        cmd=f"ssh-keygen -f {filename} -N example",
        shell=True,
        expected_exit_code=0,
        expected_exit_code_failure_message="Failed to create OpenSSH file.",
    )


def _generate_and_retrieve_openssh_key(node: Node, filename: str) -> str:
    _generate_openssh_key(node=node, filename=filename)
    result = node.execute(
        cmd=f"cat {filename}.pub",
        shell=True,
        expected_exit_code=0,
        expected_exit_code_failure_message="Failed to open OpenSSH key file.",
    )
    return result.stdout


def _generate_password() -> str:
    password = generate_random_chars()
    add_secret(password)
    return password


def _generate_and_retrieve_ssh2_key(node: Node, filename: str) -> str:
    # Converts OpenSSH public key to SSH2 public key
    _generate_openssh_key(node=node, filename=filename)
    result = node.execute(
        cmd=f"ssh-keygen -e -f {filename}.pub",
        shell=True,
        expected_exit_code=0,
        expected_exit_code_failure_message="Failed to generate SSH2 key.",
    )
    return result.stdout


def _generate_and_retrieve_pem_cert(node: Node) -> str:
    node.execute(
        cmd='openssl req -nodes -x509 -newkey rsa:2048 -keyout \
            /tmp/key.pem -out /tmp/cert.pem -subj "/C=US/ST=WA/\
            L=Redmond/O=Microsoft/OU=DevOps/CN=www.example.com/\
            emailAddress=dev@www.example.com"',
        shell=True,
        expected_exit_code=0,
        expected_exit_code_failure_message="Failed to create certificate.",
    )

    result = node.execute(
        cmd="cat /tmp/cert.pem",
        shell=True,
        expected_exit_code=0,
        expected_exit_code_failure_message="Failed to retrieve certificate.",
    )
    return result.stdout


def _validate_password(
    node: Node, username: str, password: str, expected_exit_code: int = 0
) -> None:
    if isinstance(node.os, CBLMariner):
        if node.os.information.version >= "2.0.0":
            # In Mariner 2.0, there is a security restriction that only allows wheel
            # group users to use 'su' command. Add current user
            # (specified during VM creation) to wheel group in Mariner
            node.tools[Usermod].add_user_to_group("wheel", sudo=True)

    # simple command to determine if username password combination is valid/invalid
    if type(node.os) is Ubuntu and node.os.information.release in ["18.04", "16.04"]:
        message = "Permission denied, please try again."
        ssh_pass = node.tools[Sshpass]
        node = cast(RemoteNode, node)
        ssh_pass.verify_user_password_with_sshpass(
            target_ip=node.internal_address,
            target_password=password,
            target_username=username,
            expected_exit_code=expected_exit_code,
            expected_exit_code_failure_message=message,
        )
    else:
        message = f"Password not set as intended for user {username}."
        node.execute(
            cmd=f'echo "{password}" | su --command true {username}',
            shell=True,
            expected_exit_code=0 if expected_exit_code == 0 else 1,
            expected_exit_code_failure_message=message,
        )


def _validate_ssh_key_exists(node: Node, username: str, exists: bool = True) -> None:
    # Command checks whether authorized_keys file is created and has correct format
    message = f"Public key file for user {username} \
        {'does not exist' if exists else 'exists'}."
    node.execute(
        cmd=f"ssh-keygen -l -f /home/{username}/.ssh/authorized_keys",
        shell=True,
        sudo=True,
        expected_exit_code=0 if exists else 255,
        expected_exit_code_failure_message=message,
    )


def _validate_account_expiration_date(
    node: Node, username: str, expiration_str: str
) -> None:
    message = f"Cannot retrieve account details for user {username}"
    # Command checks whether the account expiration specified is correct
    result = node.execute(
        cmd=f"chage -l {username}",
        shell=True,
        sudo=True,
        expected_exit_code=0,
        expected_exit_code_failure_message=message,
    )

    assert_that(result.stdout).described_as(
        f"Expected the account details to contain expiration date of {expiration_str}"
    ).contains(expiration_str)


@TestSuiteMetadata(
    area="vm_extension",
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
    @TestCaseMetadata(
        description="""
        Runs the VMAccess VM extension with a valid username and password.
        """,
        priority=1,
    )
    def verify_valid_password_run(self, log: Logger, node: Node) -> None:
        username = "vmaccessuser"
        password = _generate_password()
        incorrect_password = _generate_password()
        protected_settings = {
            "username": username,
            "password": password,
        }

        create_and_verify_vmaccess_extension_run(
            node=node, protected_settings=protected_settings
        )
        _validate_password(node=node, username=username, password=password)
        _validate_password(
            node=node,
            username=username,
            password=incorrect_password,
            expected_exit_code=5,
        )

    @TestCaseMetadata(
        description="""
        Runs the VMAccess VM extension with an OpenSSH public key.
        """,
        priority=3,
    )
    def verify_openssh_key_run(self, log: Logger, node: Node) -> None:
        username = "vmaccessuser-openssh"
        ssh_filename = f"/tmp/{str(uuid.uuid4())}"
        openssh_key = _generate_and_retrieve_openssh_key(
            node=node, filename=ssh_filename
        )

        protected_settings = {"username": username, "ssh_key": openssh_key}

        create_and_verify_vmaccess_extension_run(
            node=node, protected_settings=protected_settings
        )
        _validate_ssh_key_exists(node=node, username=username)

    @TestCaseMetadata(
        description="""
        Runs the VMAccess VM extension with both a password and OpenSSH public key.
        """,
        priority=3,
    )
    def verify_password_and_ssh_key_run(self, log: Logger, node: Node) -> None:
        username = "vmaccessuser-both"
        password = _generate_password()
        ssh_filename = f"/tmp/{str(uuid.uuid4())}"
        openssh_key = _generate_and_retrieve_openssh_key(
            node=node, filename=ssh_filename
        )

        protected_settings = {
            "username": username,
            "ssh_key": openssh_key,
            "password": password,
        }

        create_and_verify_vmaccess_extension_run(
            node=node, protected_settings=protected_settings
        )
        # Expecting both password and ssh key to be created as intended
        _validate_ssh_key_exists(node=node, username=username)
        _validate_password(node=node, username=username, password=password)

    @TestCaseMetadata(
        description="""
        Runs the VMAccess VM extension without a password and OpenSSH public key.
        """,
        priority=3,
    )
    def verify_no_password_and_ssh_key_run_failed(
        self, log: Logger, node: Node
    ) -> None:
        username = "vmaccessuser-none"
        password = _generate_password()
        protected_settings = {"username": username}

        create_and_verify_vmaccess_extension_run(
            node=node, protected_settings=protected_settings
        )
        # Expecting no ssh keys and password to exist for this user
        _validate_ssh_key_exists(node=node, username=username, exists=False)
        _validate_password(
            node=node, username=username, password=password, expected_exit_code=255
        )

    @TestCaseMetadata(
        description="""
        Runs the VMAccess VM extension with a certificate containing a public ssh key
        in pem format.
        """,
        priority=3,
    )
    def verify_pem_certificate_ssh_key_run(self, log: Logger, node: Node) -> None:
        username = "vmaccessuser-cert"
        pem_cert = _generate_and_retrieve_pem_cert(node=node)
        protected_settings = {"username": username, "ssh_key": pem_cert}

        create_and_verify_vmaccess_extension_run(
            node=node, protected_settings=protected_settings
        )
        _validate_ssh_key_exists(node=node, username=username)

    @TestCaseMetadata(
        description="""
        Runs the VMAccess VM extension with an SSH2 public key.
        """,
        priority=3,
    )
    def verify_ssh2_key_run(self, log: Logger, node: Node) -> None:
        username = "vmaccessuser-ssh2"
        ssh_filename = f"/tmp/{str(uuid.uuid4())}"
        ssh2_key = _generate_and_retrieve_ssh2_key(node=node, filename=ssh_filename)

        protected_settings = {"username": username, "ssh_key": ssh2_key}

        create_and_verify_vmaccess_extension_run(
            node=node, protected_settings=protected_settings
        )
        _validate_ssh_key_exists(node=node, username=username)

    @TestCaseMetadata(
        description="""
        Runs the VMAccess VM extension with a username to remove.
        """,
        priority=3,
    )
    def verify_remove_username_run(self, log: Logger, node: Node) -> None:
        username = "vmaccessuser-remove"
        password = _generate_password()
        protected_settings = {"username": username, "password": password}

        create_and_verify_vmaccess_extension_run(
            node=node, protected_settings=protected_settings
        )
        _validate_password(node=node, username=username, password=password)

        protected_settings = {"remove_user": username}

        create_and_verify_vmaccess_extension_run(
            node=node, protected_settings=protected_settings
        )
        _validate_password(
            node=node, username=username, password=password, expected_exit_code=5
        )

    @TestCaseMetadata(
        description="""
        Runs the VMAccess VM extension with an OpenSSH public key
        and valid expiration date.
        """,
        priority=3,
    )
    def verify_valid_expiration_run(self, log: Logger, node: Node) -> None:
        username = "vmaccessuser-exp"
        ssh_filename = f"/tmp/{str(uuid.uuid4())}"
        openssh_key = _generate_and_retrieve_openssh_key(
            node=node, filename=ssh_filename
        )

        protected_settings = {
            "username": username,
            "ssh_key": openssh_key,
            "expiration": "2024-01-01",
        }

        create_and_verify_vmaccess_extension_run(
            node=node, protected_settings=protected_settings
        )
        _validate_ssh_key_exists(node=node, username=username)
        _validate_account_expiration_date(
            node=node, username=username, expiration_str="Jan 01, 2024"
        )
