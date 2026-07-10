# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import List

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    schema,
    search_space,
    simple_requirement,
)
from lisa.features import Disk
from lisa.operating_system import BSD, Windows
from lisa.tools import Mount
from lisa.util import SkippedException

# A fixed 16-byte salt (32 hex chars) and passphrase. Because the fscrypt key
# descriptor is derived deterministically from salt + passphrase, re-adding the
# same key later yields the same descriptor and transparently unlocks the data.
_FSCRYPT_SALT = "0x00112233445566778899aabbccddeeff"
_FSCRYPT_PASSPHRASE = "lisa-fscrypt-pass"
_PLAINTEXT_TOKEN = "lisa-fscrypt-topsecret"


@TestSuiteMetadata(
    area="security",
    category="functional",
    description="""
    Validates native (kernel) filesystem encryption — fscrypt — end to end.

    Each variation formats a data disk with encryption support, applies an
    encryption policy to a directory, writes a known plaintext, then proves:
      1. Data is readable while the key is present in the keyring.
      2. On a fresh mount without the key, filenames are ciphertext and the
         plaintext is inaccessible (directory is "locked").
      3. Re-adding the identical key transparently unlocks the data.
    """,
)
class FscryptSuite(TestSuite):
    @TestCaseMetadata(
        description="""
        fscrypt lifecycle on ext4 using e4crypt (from e2fsprogs).
        """,
        priority=2,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                data_disk_count=search_space.IntRange(min=1),
            ),
            unsupported_os=[Windows, BSD],
        ),
    )
    def verify_fscrypt_ext4(self, log: Logger, node: Node) -> None:
        self._run_fscrypt_lifecycle(
            log,
            node,
            fs_label="ext4",
            mkfs_command="mkfs.ext4 -F -O encrypt",
            crypt_tool="e4crypt",
            packages=["e2fsprogs", "keyutils"],
        )

    @TestCaseMetadata(
        description="""
        fscrypt lifecycle on f2fs using f2fscrypt (from f2fs-tools).
        """,
        priority=3,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                data_disk_count=search_space.IntRange(min=1),
            ),
            unsupported_os=[Windows, BSD],
        ),
    )
    def verify_fscrypt_f2fs(self, log: Logger, node: Node) -> None:
        self._run_fscrypt_lifecycle(
            log,
            node,
            fs_label="f2fs",
            mkfs_command="mkfs.f2fs -f -O extra_attr,encrypt",
            crypt_tool="f2fscrypt",
            packages=["f2fs-tools", "keyutils"],
        )

    def _run_fscrypt_lifecycle(
        self,
        log: Logger,
        node: Node,
        fs_label: str,
        mkfs_command: str,
        crypt_tool: str,
        packages: List[str],
    ) -> None:
        mount_point = "/mnt/fscrypt"
        secret_dir = f"{mount_point}/secret"

        # --- Preconditions ------------------------------------------------
        for package in packages:
            node.os.install_packages(package)

        if node.execute(f"command -v {crypt_tool}", shell=True).exit_code != 0:
            raise SkippedException(f"{crypt_tool} is not available on this image")

        if (
            node.execute(
                "grep -q '^CONFIG_FS_ENCRYPTION=y' /boot/config-$(uname -r)",
                sudo=True,
                shell=True,
            ).exit_code
            != 0
        ):
            raise SkippedException("kernel is not built with CONFIG_FS_ENCRYPTION=y")

        data_disk = node.features[Disk].get_raw_data_disks()[0]
        log.info(f"using data disk {data_disk} for {fs_label} fscrypt test")

        mount = node.tools[Mount]
        # Ensure a clean slate in case a previous run left it mounted.
        mount.umount(data_disk, mount_point, erase=False)

        # --- Format + mount + apply policy + write (single keyring session) ---
        # add_key stores the key in the *calling process'* session keyring, so
        # the key-add, policy-set and write must run in one shell invocation.
        node.execute(
            f"{mkfs_command} {data_disk}",
            sudo=True,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="failed to format disk",
        )
        mount.mount(data_disk, mount_point)

        add_and_write = (
            f"mkdir -p {secret_dir} "
            f"&& DESC=$(printf '{_FSCRYPT_PASSPHRASE}\\n' "
            f"| {crypt_tool} add_key -S {_FSCRYPT_SALT} "
            f"| grep -oE '[0-9a-f]{{16}}' | head -1) "
            f'&& test -n "$DESC" '
            f"&& {crypt_tool} set_policy $DESC {secret_dir} "
            f"&& echo {_PLAINTEXT_TOKEN} > {secret_dir}/plain.txt "
            f"&& grep -q {_PLAINTEXT_TOKEN} {secret_dir}/plain.txt"
        )
        node.execute(
            add_and_write,
            sudo=True,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "failed to add key, set policy, or read back plaintext with key present"
            ),
        )
        log.info("plaintext readable while encryption key is present")

        # --- Lock: fresh mount without the key ---------------------------
        mount.umount(data_disk, mount_point, erase=False)
        mount.mount(data_disk, mount_point)

        listing = node.execute(f"ls {secret_dir}", sudo=True, shell=True).stdout
        if "plain.txt" in listing:
            raise AssertionError(
                "filename 'plain.txt' is visible in cleartext without the key — "
                "encryption policy is not in effect"
            )

        # Reading the file without the key must fail (ENOKEY). Encrypted
        # filenames make the original path non-existent, so a read is expected
        # to return a non-zero exit code.
        if (
            node.execute(f"cat {secret_dir}/plain.txt", sudo=True, shell=True).exit_code
            == 0
        ):
            raise AssertionError("plaintext was readable without the key")
        log.info("directory is locked (ciphertext filenames, no plaintext access)")

        # --- Unlock: re-add the identical key ----------------------------
        recover = (
            f"printf '{_FSCRYPT_PASSPHRASE}\\n' "
            f"| {crypt_tool} add_key -S {_FSCRYPT_SALT} "
            f"&& cat {secret_dir}/plain.txt"
        )
        result = node.execute(
            recover,
            sudo=True,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "re-adding the key did not unlock the encrypted data"
            ),
        )
        if _PLAINTEXT_TOKEN not in result.stdout:
            raise AssertionError(
                "recovered content did not match the original plaintext"
            )
        log.info("data transparently unlocked after re-adding the key")

        # --- Cleanup ------------------------------------------------------
        mount.umount(data_disk, mount_point, erase=False)
