# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import base64
import json
import shlex
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Generator, Optional, Tuple

from assertpy import assert_that
from azure.core.exceptions import HttpResponseError
from microsoft.testsuites.vm_extensions.vm_extension_base import VmExtensionTestBase

from lisa import Node, TestCaseMetadata, TestSuiteMetadata, simple_requirement
from lisa.environment import Environment, EnvironmentStatus
from lisa.operating_system import BSD, Windows
from lisa.secret import add_secret
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import get_vm
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform, AzurePlatformSchema
from lisa.util import LisaException, SkippedException, generate_random_chars


def _generate_password() -> str:
    password = generate_random_chars()
    add_secret(password)
    return password


def _expiration_days(date: datetime) -> int:
    return (date.date() - datetime(1970, 1, 1).date()).days


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="""
    Validate Linux VMAccess using Azure APIs and protected inline Custom Script.
    No runner or localhost SSH connections are made. Password hashes, account
    policy, public keys/permissions, and local sudo operations are checked;
    these are not SSH authentication tests.
    """,
    tags=["VM_Extension", "VMAccessForLinux"],
    reuse_deployed_environment=True,
    requirement=simple_requirement(
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
        unsupported_os=[BSD, Windows],
        environment_status=EnvironmentStatus.Deployed,
    ),
)
class VMAccessTests(VmExtensionTestBase):  # type: ignore[misc]
    PUBLISHER = "Microsoft.OSTCExtensions"
    EXTENSION_TYPE = "VMAccessForLinux"
    EXTENSION_KEY = "vmaccess"
    DEFAULT_VERSION = "1.5"
    VALIDATION_EXTENSION = "vmaccess-validation"

    def _is_test_deployment(self, environment: Environment) -> bool:
        platform = environment.platform
        assert isinstance(platform, AzurePlatform)
        runbook = platform.runbook.get_extended_runbook(AzurePlatformSchema)
        return runbook.deploy and not runbook.dry_run

    def before_case(
        self,
        node: Node,
        environment: Environment,
        variables: Dict[str, Any],
        **kwargs: Any,
    ) -> None:
        self._snapshot_path = ""
        if not self._is_test_deployment(environment):
            raise SkippedException(
                "VMAccess validation requires LISA-deployed test VMs, "
                "not deploy:false or dry_run"
            )
        platform = environment.platform
        assert isinstance(platform, AzurePlatform)
        if get_vm(platform, node).storage_profile.os_disk.os_type.lower() != "linux":
            raise SkippedException("VMAccessForLinux requires a Linux VM")
        extension = node.features[AzureExtension]
        self._cleanup_existing_extensions(
            extension,
            self._resolve_publisher(variables),
            self._resolve_type(variables),
            node.log,
        )
        self._cleanup_existing_extensions(
            extension, "Microsoft.Azure.Extensions", "CustomScript", node.log
        )
        try:
            snapshot = self._guest(node, "snapshot_state")["snapshot"]
            if not isinstance(snapshot, str):
                raise LisaException("Custom Script returned an invalid state path")
            self._snapshot_path = snapshot
        except Exception:
            node.mark_dirty()
            raise

    def after_case(self, node: Node, environment: Environment, **kwargs: Any) -> None:
        if not self._is_test_deployment(environment):
            node.log.info("Leaving the pre-existing environment untouched")
            return
        if not self._snapshot_path:
            node.log.info(
                "Case setup did not complete; no guest test state needs restoring"
            )
            return
        try:
            try:
                self._uninstall(node)
            finally:
                try:
                    if self._snapshot_path:
                        self._guest(node, "restore_state", snapshot=self._snapshot_path)
                finally:
                    node.features[AzureExtension].delete(
                        self.VALIDATION_EXTENSION, ignore_not_found=True
                    )
        except Exception:
            node.mark_dirty()
            raise

    def _guest(self, node: Node, operation: str, **arguments: Any) -> Dict[str, Any]:
        marker = f"VMACCESS_RESULT_{uuid.uuid4().hex}:"
        request = {"operation": operation, "marker": marker, **arguments}
        payload = base64.b64encode(json.dumps(request).encode()).decode()
        source = (
            Path(__file__).parent / "scripts" / "vmaccess_validation.py"
        ).read_text(encoding="utf-8")
        script = (
            "#!/bin/bash\nset -euo pipefail\numask 077\n"
            f"python3 - {shlex.quote(payload)} <<'VMACCESS_PYTHON'\n"
            f"{source}\nVMACCESS_PYTHON\n"
        )
        extension = node.features[AzureExtension]
        result = extension.create_or_update(
            name=self.VALIDATION_EXTENSION,
            publisher="Microsoft.Azure.Extensions",
            type_="CustomScript",
            type_handler_version="2.1",
            auto_upgrade_minor_version=True,
            force_update_tag=str(uuid.uuid4()),
            settings={},
            protected_settings={"script": base64.b64encode(script.encode()).decode()},
        )
        assert_that(result["provisioning_state"]).described_as(
            "Custom Script guest validation must succeed"
        ).is_equal_to("Succeeded")
        instance_view = extension.get(self.VALIDATION_EXTENSION).instance_view
        if instance_view is None:
            raise LisaException("Custom Script returned no instance view")
        outputs = [
            status.message or ""
            for status in instance_view.substatuses or []
            if status.code and status.code.lower() == "componentstatus/stdout/succeeded"
        ]
        for status in instance_view.statuses or []:
            message = status.message or ""
            if "\n[stdout]\n" in message:
                outputs.append(
                    message.split("\n[stdout]\n", 1)[1].split("\n[stderr]\n", 1)[0]
                )
        matching_outputs = [output for output in outputs if marker in output]
        if not matching_outputs:
            raise LisaException(
                "Custom Script returned no completion result for this invocation; "
                "check extension status and the 4 KiB output limit"
            )
        response = json.loads(matching_outputs[0].rsplit(marker, 1)[1].strip())
        if not isinstance(response, dict):
            raise LisaException("Custom Script returned an invalid validation result")
        return response

    def _script(self, node: Node, script: str, expected_exit_code: int = 0) -> str:
        response = self._guest(
            node, "command", script=script, expected_exit_code=expected_exit_code
        )
        stdout = response["stdout"]
        if not isinstance(stdout, str):
            raise LisaException("Custom Script command stdout is not a string")
        return stdout

    def _validate_account(self, node: Node, username: str, **expected: Any) -> None:
        self._guest(node, "validate_account", username=username, **expected)

    def _new_key(
        self, node: Node, algorithm: str = "rsa", format_: str = "openssh"
    ) -> Tuple[str, str]:
        result = self._guest(node, "generate_key", algorithm=algorithm, format=format_)
        setting, public_key = result["setting"], result["public_key"]
        if not isinstance(setting, str) or not isinstance(public_key, str):
            raise LisaException("Custom Script returned invalid key material")
        return setting, public_key

    def _apply(
        self,
        node: Node,
        variables: Dict[str, Any],
        protected_settings: Optional[Dict[str, Any]] = None,
        settings: Optional[Dict[str, Any]] = None,
        failure: str = "",
        version: Optional[str] = None,
    ) -> None:
        extension = node.features[AzureExtension]
        requested = version or self._get_version(variables)
        major_minor, exact = extension.normalize_type_handler_version(requested)
        try:
            result = extension.create_or_update(
                name=self.extension_name,
                publisher=self._resolve_publisher(variables),
                type_=self._resolve_type(variables),
                type_handler_version=major_minor,
                auto_upgrade_minor_version=not exact,
                force_update_tag=str(uuid.uuid4()),
                settings=settings or {},
                protected_settings=protected_settings or {},
            )
        except HttpResponseError as error:
            if not failure:
                raise
            assert_that(str(error)).contains(failure)
            return
        if failure:
            raise LisaException(f"Expected VMAccess to fail with: {failure}")
        self._assert_provisioned(result, variables)
        installed = extension.get_installed_type_handler_version(self.extension_name)
        if exact:
            assert_that(
                extension.are_type_handler_versions_equal(requested, installed)
            ).described_as("VMAccess candidate version mismatch").is_true()

    @contextmanager
    def _without_provisioning_keys(self, node: Node) -> Generator[None, None, None]:
        backup = f"/var/lib/waagent/ovf-env.vmaccess-{uuid.uuid4().hex}.xml"
        self._script(node, f"cp -p /var/lib/waagent/ovf-env.xml {backup}")
        try:
            self._script(
                node,
                "python3 -c "
                + shlex.quote(
                    "import xml.etree.ElementTree as E; "
                    "p='/var/lib/waagent/ovf-env.xml'; t=E.parse(p); "
                    "[parent.remove(child) for parent in t.iter() "
                    "for child in list(parent) "
                    "if child.tag.split('}')[-1] in ('PublicKeys', 'KeyPairs')]; "
                    "t.write(p)"
                ),
            )
            yield
        finally:
            self._script(node, f"mv -f {backup} /var/lib/waagent/ovf-env.xml")

    @TestCaseMetadata(
        description="Reset an existing password hash; reject the previous password.",
        priority=2,
        maturity="preview",
    )
    def verify_existing_password_reset(
        self, node: Node, variables: Dict[str, Any]
    ) -> None:
        username = "vmaccess-existing"
        old, new = _generate_password(), _generate_password()
        self._script(
            node,
            f"useradd -m {username}\n"
            f"printf '%s\\n' {shlex.quote(username + ':' + old)} | chpasswd",
        )
        self._validate_account(node, username, password=old)
        self._apply(node, variables, {"username": username, "password": new})
        self._validate_account(
            node, username, password=new, rejected_password=old, passwordless=False
        )

    @TestCaseMetadata(
        description="Passwordless sudo, empty passwords, and sudoer preservation.",
        priority=2,
        maturity="preview",
    )
    def verify_passwordless_access_and_sudo_preservation(
        self, node: Node, variables: Dict[str, Any]
    ) -> None:
        first, second = "vmaccess-sudo1", "vmaccess-sudo2"
        password = _generate_password()
        self._apply(node, variables, {"username": first, "password": password})
        self._validate_account(node, first, password=password, passwordless=False)
        self._apply(
            node,
            variables,
            {
                "username": second,
                "password": password,
                "enable_passwordless_access": True,
            },
        )
        self._validate_account(node, first, passwordless=False)
        self._validate_account(node, second, password=password, passwordless=True)
        self._apply(
            node,
            variables,
            {
                "username": second,
                "password": password,
                "enable_passwordless_access": False,
            },
        )
        self._validate_account(node, first, passwordless=False)
        self._validate_account(node, second, passwordless=False)
        _, key = self._new_key(node)
        self._apply(
            node,
            variables,
            {
                "username": first,
                "password": "",
                "ssh_key": key,
            },
        )
        self._validate_account(node, first, password=password, keys=[key])
        self._apply(node, variables, {"remove_user": second})
        self._validate_account(node, first, password=password, passwordless=True)
        self._script(node, f"! getent passwd {second}")

    @TestCaseMetadata(
        description="Reject malformed credentials, expiration, and system-user resets.",
        priority=3,
        maturity="preview",
    )
    def verify_invalid_account_settings(
        self, node: Node, variables: Dict[str, Any]
    ) -> None:
        for key, error in [
            (
                "---- BEGIN SSH2 PUBLIC KEY ----\n"
                "invalid\n---- END SSH2 PUBLIC KEY ----",
                "Failed to convert SSH2 key",
            ),
            (
                "-----BEGIN CERTIFICATE-----\ninvalid\n-----END CERTIFICATE-----",
                "Failed to generate public key file",
            ),
        ]:
            self._apply(
                node,
                variables,
                {
                    "username": "vmaccess-badkey",
                    "ssh_key": key,
                },
                failure=error,
            )
        self._apply(
            node,
            variables,
            {
                "username": "vmaccess-badexpiry",
                "password": _generate_password(),
                "expiration": "not-a-date",
            },
            failure="Failed to create the account",
        )
        self._apply(
            node,
            variables,
            {
                "username": "root",
                "password": _generate_password(),
            },
            failure="system user",
        )
        for option in ["reset_ssh", "restore_backup_ssh", "password"]:
            self._apply(
                node,
                variables,
                {
                    "remove_user": "vmaccess-conflict",
                    option: _generate_password() if option == "password" else True,
                },
                failure="Cannot reset sshd_config and remove a user",
            )

    @TestCaseMetadata(
        description="Validate expired account policy and configured credentials.",
        priority=3,
        maturity="preview",
    )
    def verify_expired_accounts(self, node: Node, variables: Dict[str, Any]) -> None:
        expiration = datetime.now(timezone.utc) - timedelta(days=2)
        _, key = self._new_key(node)
        username = "vmaccess-expired"
        password = _generate_password()
        self._apply(
            node,
            variables,
            {
                "username": username,
                "password": password,
                "ssh_key": key,
                "expiration": expiration.date().isoformat(),
            },
        )
        self._validate_account(
            node,
            username,
            password=password,
            keys=[key],
            expiration=_expiration_days(expiration),
        )

    @TestCaseMetadata(
        description="Settings without a username must not create or alter accounts.",
        priority=3,
        maturity="preview",
    )
    def verify_missing_username(self, node: Node, variables: Dict[str, Any]) -> None:
        before = self._script(node, "sha256sum /etc/passwd /etc/group")
        self._apply(node, variables, {"password": _generate_password()})
        assert_that(self._script(node, "sha256sum /etc/passwd /etc/group")).is_equal_to(
            before
        )

    @TestCaseMetadata(
        description="Recover SSH configuration/firewall settings without connecting.",
        priority=3,
        maturity="preview",
        timeout=3600,
    )
    def verify_ssh_configuration_recovery(
        self, node: Node, variables: Dict[str, Any]
    ) -> None:
        backup = f"/tmp/vmaccess-sshd-{uuid.uuid4().hex}"
        self._apply(node, variables, {})
        self._script(
            node,
            f"""
command -v iptables
mkdir -m 700 {backup}
cp -p /etc/ssh/sshd_config {backup}/original
iptables-save > {backup}/firewall
if test -f /var/cache/vmaccess/backup; then
    cp -p /var/cache/vmaccess/backup {backup}/extension-backup
fi
""",
        )
        try:
            self._script(
                node,
                """
printf '\\nInvalidVmAccessDirective yes\\n' >> /etc/ssh/sshd_config
if /usr/sbin/sshd -t; then exit 1; fi
iptables -I INPUT 1 -p tcp -m tcp --dport 22 -j REJECT
iptables -I OUTPUT 1 -p tcp -m tcp --sport 22 -j DROP
iptables -C INPUT -p tcp -m tcp --dport 22 -j REJECT
iptables -C OUTPUT -p tcp -m tcp --sport 22 -j DROP
""",
            )
            self._apply(node, variables, {"reset_ssh": True})
            self._script(
                node,
                """
/usr/sbin/sshd -t
! grep -q '^InvalidVmAccessDirective' /etc/ssh/sshd_config
""",
            )
            for rule in [
                "INPUT -p tcp -m tcp --dport 22 -j REJECT",
                "OUTPUT -p tcp -m tcp --sport 22 -j DROP",
            ]:
                self._script(node, f"iptables -C {rule}", expected_exit_code=1)
            self._script(
                node,
                f"""
cp -p {backup}/original /etc/ssh/sshd_config
printf '\\n# vmaccess-restore-marker\\n' >> /etc/ssh/sshd_config
mkdir -p /var/cache/vmaccess
cp -p /etc/ssh/sshd_config /var/cache/vmaccess/backup
printf '\\n# changed-after-backup\\n' >> /etc/ssh/sshd_config
""",
            )
            self._apply(node, variables, {"restore_backup_ssh": True})
            self._script(
                node,
                """
/usr/sbin/sshd -t
grep -q '^# vmaccess-restore-marker' /etc/ssh/sshd_config
if grep -q '^# changed-after-backup' /etc/ssh/sshd_config; then
    echo 'Modified configuration was not replaced by the backup' >&2
    exit 1
fi
test ! -e /var/cache/vmaccess/backup
""",
            )
            self._script(
                node,
                """
printf '\\nInvalidVmAccessDirective yes\\n' >> /etc/ssh/sshd_config
test ! -e /var/cache/vmaccess/backup
""",
            )
            self._apply(node, variables, {"restore_backup_ssh": True})
            self._script(node, "/usr/sbin/sshd -t")
        finally:
            self._script(
                node,
                f"""
iptables-restore < {backup}/firewall
cp -p {backup}/original /etc/ssh/sshd_config
if test -f {backup}/extension-backup; then
    cp -p {backup}/extension-backup /var/cache/vmaccess/backup
fi
if systemctl list-unit-files ssh.service --no-legend | grep -q ssh.service; then
    systemctl restart ssh
else
    systemctl restart sshd
fi
rm -f {backup}/original {backup}/extension-backup {backup}/firewall
rmdir {backup}
""",
            )

    @TestCaseMetadata(
        description="""
        Install the explicit VMAccess candidate and validate the account's password
        hash and sudo permissions through Custom Script. A full requested version
        must match the installed handler. No SSH connectivity is required/tested.
        """,
        priority=5,
        tags=["microsoft.ostcextensions.vmaccessforlinux"],
        maturity="preview",
    )
    def microsoft_ostcextensions_vmaccessforlinux_boot_validation_test(
        self, node: Node, variables: Dict[str, Any]
    ) -> None:
        username = "vmaccessuser-bootval"
        password = _generate_password()
        self._apply(
            node,
            variables,
            {"username": username, "password": password},
            version=self._get_version(variables, use_default=False),
        )
        self._validate_account(
            node,
            username,
            password=password,
            rejected_password=_generate_password(),
            passwordless=False,
        )

    @TestCaseMetadata(
        description="Validate a configured password hash and default account policy.",
        priority=1,
    )
    def verify_valid_password_run(self, node: Node, variables: Dict[str, Any]) -> None:
        username = "vmaccessuser"
        password = _generate_password()
        self._apply(node, variables, {"username": username, "password": password})
        self._validate_account(
            node,
            username,
            password=password,
            rejected_password=_generate_password(),
            passwordless=False,
            expiration=-1,
        )

    @TestCaseMetadata(
        description="Validate RSA key contents, permissions, and passwordless sudo.",
        priority=3,
    )
    def verify_openssh_key_run(self, node: Node, variables: Dict[str, Any]) -> None:
        username = "vmaccessuser-openssh"
        _, key = self._new_key(node)
        self._apply(node, variables, {"username": username, "ssh_key": key})
        self._validate_account(node, username, keys=[key], passwordless=True)

    @TestCaseMetadata(
        description="Validate both the configured password hash and public key.",
        priority=3,
    )
    def verify_password_and_ssh_key_run(
        self, node: Node, variables: Dict[str, Any]
    ) -> None:
        username = "vmaccessuser-both"
        password = _generate_password()
        _, key = self._new_key(node)
        self._apply(
            node,
            variables,
            {
                "username": username,
                "password": password,
                "ssh_key": key,
            },
        )
        self._validate_account(
            node, username, password=password, keys=[key], passwordless=False
        )

    @TestCaseMetadata(
        description="Reject missing/empty credentials without provisioning keys.",
        priority=3,
    )
    def verify_no_password_and_ssh_key_run_failed(
        self, node: Node, variables: Dict[str, Any]
    ) -> None:
        username = "vmaccessuser-none"
        with self._without_provisioning_keys(node):
            for settings in [
                {"username": username},
                {"username": username, "password": ""},
            ]:
                self._apply(
                    node,
                    variables,
                    settings,
                    failure="No password or ssh_key is specified",
                )
        self._script(node, f"! getent passwd {username}")

    @TestCaseMetadata(
        description="Validate the exact public key extracted from a PEM certificate.",
        priority=3,
    )
    def verify_pem_certificate_ssh_key_run(
        self, node: Node, variables: Dict[str, Any]
    ) -> None:
        username = "vmaccessuser-cert"
        certificate, public_key = self._new_key(node, format_="certificate")
        self._apply(node, variables, {"username": username, "ssh_key": certificate})
        self._validate_account(node, username, keys=[public_key])

    @TestCaseMetadata(
        description="Validate the exact OpenSSH public key imported from SSH2 format.",
        priority=3,
    )
    def verify_ssh2_key_run(self, node: Node, variables: Dict[str, Any]) -> None:
        username = "vmaccessuser-ssh2"
        setting, public_key = self._new_key(node, format_="ssh2")
        self._apply(node, variables, {"username": username, "ssh_key": setting})
        self._validate_account(node, username, keys=[public_key])

    @TestCaseMetadata(
        description="Remove an account, its home, keys, and sudo permission.",
        priority=3,
    )
    def verify_remove_username_run(self, node: Node, variables: Dict[str, Any]) -> None:
        username = "vmaccessuser-remove"
        password = _generate_password()
        _, key = self._new_key(node)
        self._apply(
            node,
            variables,
            {
                "username": username,
                "password": password,
                "ssh_key": key,
            },
        )
        self._validate_account(node, username, password=password, keys=[key])
        self._apply(node, variables, {"remove_user": username})
        self._script(
            node,
            f"""
if getent passwd {username}; then
    echo 'The removed account still exists' >&2
    exit 1
fi
test ! -e /home/{username}
if test -f /etc/sudoers.d/waagent; then
    ! grep -q '^{username} ' /etc/sudoers.d/waagent
fi
""",
        )

    @TestCaseMetadata(
        description="Validate a public key and future account expiration.",
        priority=3,
    )
    def verify_valid_expiration_run(
        self, node: Node, variables: Dict[str, Any]
    ) -> None:
        username = "vmaccessuser-exp"
        _, key = self._new_key(node)
        expiration = datetime.now(timezone.utc) + timedelta(days=30)
        self._apply(
            node,
            variables,
            {
                "username": username,
                "ssh_key": key,
                "expiration": expiration.date().isoformat(),
            },
        )
        self._validate_account(
            node, username, keys=[key], expiration=_expiration_days(expiration)
        )
