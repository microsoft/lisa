# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import os
from dataclasses import dataclass, field
from pathlib import PurePath, PurePosixPath
from typing import List, Type

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.node import Node
from lisa.operating_system import CBLMariner
from lisa.tools import Cat, Chmod, Cp, Echo, Ln, Ls, Lsblk, Sed, Tar, Uname
from lisa.util import UnsupportedDistroException, field_metadata

from .kernel_installer import BaseInstaller, BaseInstallerSchema
from .kernel_source_installer import SourceInstaller, SourceInstallerSchema

DEFAULT_ADDITIONAL_GRUB_ENTRY = (
    "#!/bin/sh\n"
    "exec tail -n +3 $0\n\n"
    "menuentry 'Custom Linux Default entry LISA' "
    "--class azurelinux --class gnu-linux --class gnu --class os "
    "--id=REPL_MENUENTRY_ID {\n"
    "    load_video\n"
    "    set gfxpayload=keep\n"
    "    insmod gzio\n"
    "    insmod part_gpt\n"
    "    insmod ext2\n"
    "    set root='hd0,gpt2'\n"
    "    if [ x$feature_platform_search_hint = xy ]; then\n"
    "        search --no-floppy --fs-uuid --set=root "
    "--hint-bios=hd0,gpt2 --hint-efi=hd0,gpt2 "
    "--hint-baremetal=ahci0,gpt2  REPL_UUID\n"
    "    else\n"
    "        search --no-floppy --fs-uuid --set=root REPL_UUID\n"
    "    fi\n"
    "    echo    'Loading Linux REPL_KERNEL_VERSION ...'\n"
    "    linux   //boot/REPL_KERNEL_VERSION root=PARTUUID=REPL_PARTUUID ro "
    "selinux=0 rd.auto=1 net.ifnames=0 lockdown=integrity "
    "sysctl.kernel.unprivileged_bpf_disabled=1 init=/lib/systemd/systemd ro "
    "audit=0 console=tty1 console=ttyS0,115200n8 "
    "crashkernel=512M-32G:256M,32G-:512M $kernelopts\n"
    "    echo    'Loading initial ramdisk ...'\n"
    "    initrd /boot/REPL_INITRD_VERSION\n"
    "}\n"
)


@dataclass_json()
@dataclass
class BinaryInstallerSchema(BaseInstallerSchema):
    # kernel binary local absolute path
    kernel_image_path: str = field(
        default="",
        metadata=field_metadata(
            required=True,
        ),
    )

    # kernel modules tar.gz files local absolute path
    kernel_modules_path: str = field(
        default="",
        metadata=field_metadata(
            required=True,
        ),
    )

    # kernel config local absolute path
    kernel_config_path: str = field(
        default="",
        metadata=field_metadata(
            required=True,
        ),
    )

    # initrd binary local absolute path
    initrd_image_path: str = field(
        default="",
        metadata=field_metadata(
            required=False,
        ),
    )
    # vmlinux binary local absolute path
    vmlinux_image_path: str = field(
        default="",
        metadata=field_metadata(
            required=False,
        ),
    )

    # additional grub file local absolute path
    additional_grub_file: str = field(
        default="",
        metadata=field_metadata(
            required=False,
        ),
    )
    menuentry_id: str = field(
        default="custom_kernel_lisa",
        metadata=field_metadata(
            required=False,
        ),
    )


class BinaryInstaller(BaseInstaller):
    @classmethod
    def type_name(cls) -> str:
        return "dom0_binaries"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return BinaryInstallerSchema

    @property
    def _output_names(self) -> List[str]:
        return []

    def validate(self) -> None:
        if not isinstance(self._node.os, CBLMariner):
            raise UnsupportedDistroException(
                self._node.os,
                f"The '{self.type_name()}' installer only support Mariner distro",
            )

    def install(self) -> str:
        node = self._node
        runbook: BinaryInstallerSchema = self.runbook
        kernel_image_path: str = runbook.kernel_image_path
        initrd_image_path: str = runbook.initrd_image_path
        kernel_modules_path: str = runbook.kernel_modules_path
        kernel_config_path: str = runbook.kernel_config_path
        additional_grub_file: str = runbook.additional_grub_file
        menuentry_id: str = runbook.menuentry_id
        vmlinux_image_path: str = runbook.vmlinux_image_path
        target_grub_file_path = "/etc/grub.d/40_custom_kernel_lisa"

        uname = node.tools[Uname]
        current_kernel = uname.get_linux_information().kernel_version_raw

        mariner_version = int(node.os.information.version.major)

        # Kernel absolute path: /home/user/vmlinuz-5.15.57.1+
        # Naming convention : vmlinuz-<version>
        new_kernel = os.path.basename(kernel_image_path).split("-")[1].strip()

        # if its lvbs kernel, then the new kernel name should be
        # vmlinuz-<version>-lvbs
        if "lvbs" in current_kernel:
            new_kernel = f"{new_kernel}-lvbs"

        self._log.info(f"Installing kernel {new_kernel} on {node.name}")

        # Copy the binaries to azure VM from where LISA is running
        err: str = f"Can not find kernel image path: {kernel_image_path}"
        assert os.path.exists(kernel_image_path), err
        node.shell.copy(
            PurePath(kernel_image_path),
            node.get_pure_path(f"/var/tmp/vmlinuz-{new_kernel}"),
        )
        _copy_kernel_binary(
            node,
            node.get_pure_path(f"/var/tmp/vmlinuz-{new_kernel}"),
            node.get_pure_path(f"/boot/vmlinuz-{new_kernel}"),
        )

        err = f"Can not find kernel modules path: {kernel_modules_path}"
        assert os.path.exists(kernel_modules_path), err
        node.shell.copy(
            PurePath(kernel_modules_path),
            node.get_pure_path(f"/var/tmp/kernel_modules_{new_kernel}.tar.gz"),
        )
        tar = node.tools[Tar]
        tar.extract(
            file=f"/var/tmp/kernel_modules_{new_kernel}.tar.gz",
            dest_dir="/lib/modules/",
            gzip=True,
            sudo=True,
        )

        # if current kernel contains "lvbs" then copy vmlinux.bin
        # to /usr/lib/firmware/vmlinux
        if "lvbs" in current_kernel:
            # Copy the kernel binary to /usr/lib/firmware/vmlinux
            err = f"Can not find vmlinux image path: {vmlinux_image_path}"
            assert os.path.exists(vmlinux_image_path), err
            node.shell.copy(
                PurePath(vmlinux_image_path),
                node.get_pure_path("/var/tmp/vmlinux.bin"),
            )
            _copy_kernel_binary(
                node,
                node.get_pure_path("/var/tmp/vmlinux.bin"),
                node.get_pure_path("/usr/lib/firmware/vmlinux"),
            )

        if initrd_image_path:
            err = f"Can not find initrd image path: {initrd_image_path}"
            assert os.path.exists(initrd_image_path), err
            node.shell.copy(
                PurePath(initrd_image_path),
                node.get_pure_path(f"/var/tmp/initrd.img-{new_kernel}"),
            )
            _copy_kernel_binary(
                node,
                node.get_pure_path(f"/var/tmp/initrd.img-{new_kernel}"),
                node.get_pure_path(f"/boot/initrd.img-{new_kernel}"),
            )
        else:
            if mariner_version <= 2:
                # Mariner 2.0 initrd
                target = f"/boot/initrd.img-{current_kernel}"
                link = f"/boot/initrd.img-{new_kernel}"

                ln = node.tools[Ln]
                ln.create_link(
                    target=target,
                    link=link,
                )
            else:
                # Mariner 3.0 and above
                initramfs = f"/boot/initramfs-{new_kernel}.img"
                dracut_cmd = f"dracut --force {initramfs} {new_kernel}"
                node.execute(dracut_cmd, sudo=True, shell=True)

        if kernel_config_path:
            # Copy kernel config
            err = f"Can not find kernel config path: {kernel_config_path}"
            assert os.path.exists(kernel_config_path), err
            node.shell.copy(
                PurePath(kernel_config_path),
                node.get_pure_path(f"/var/tmp/config-{new_kernel}"),
            )
            _copy_kernel_binary(
                node,
                node.get_pure_path(f"/var/tmp/config-{new_kernel}"),
                node.get_pure_path(f"/boot/config-{new_kernel}"),
            )

        if mariner_version <= 2:
            _update_mariner_v2_config(
                node,
                current_kernel,
                new_kernel,
                mariner_version,
            )

            return new_kernel

        if additional_grub_file:
            tmp_path = "/var/tmp/additional_grub_file"
            node.shell.copy(
                PurePath(additional_grub_file),
                node.get_pure_path(tmp_path),
            )
        else:
            # Create a file with DEFAULT_ADDITIONAL_GRUB_ENTRY contents on the  node
            tmp_path = str(node.working_path / "additional_grub_file")
            echo = node.tools[Echo]
            echo.write_to_file(
                DEFAULT_ADDITIONAL_GRUB_ENTRY,
                PurePath(tmp_path),
            )
        _copy_kernel_binary(
            node,
            node.get_pure_path(tmp_path),
            node.get_pure_path(target_grub_file_path),
        )
        node.tools[Chmod].chmod(
            path=target_grub_file_path,
            permission="755",
            sudo=True,
        )

        cat = node.tools[Cat]
        sed = node.tools[Sed]

        # Replace all the placeholders in the additional grub file
        vmlinuz_replacement = f"vmlinuz-{new_kernel}"
        initrd_replacement = f"initramfs-{new_kernel}.img"

        sed.substitute(
            regexp="REPL_MENUENTRY_ID",
            replacement=menuentry_id,
            file=target_grub_file_path,
            sudo=True,
        )
        sed.substitute(
            regexp="REPL_KERNEL_VERSION",
            replacement=vmlinuz_replacement,
            file=target_grub_file_path,
            sudo=True,
        )
        sed.substitute(
            regexp="REPL_INITRD_VERSION",
            replacement=initrd_replacement,
            file=target_grub_file_path,
            sudo=True,
        )

        lsblk = node.tools[Lsblk]
        root_partition = lsblk.find_partition_by_mountpoint("/", force_run=True)
        sed.substitute(
            regexp="REPL_UUID",
            replacement=root_partition.uuid,
            file=target_grub_file_path,
            sudo=True,
        )
        sed.substitute(
            regexp="REPL_PARTUUID",
            replacement=root_partition.part_uuid,
            file=target_grub_file_path,
            sudo=True,
        )

        # Comment out the existing GRUB_DEFAULT line
        grub_default_file = "/etc/default/grub"
        sed.substitute(
            regexp="^GRUB_DEFAULT=",
            replacement="#GRUB_DEFAULT=",
            file=grub_default_file,
            sudo=True,
        )
        # Add the new GRUB_DEFAULT line with the new kernel
        sed.insert_line_beginning(
            line=f"GRUB_DEFAULT={menuentry_id}",
            file=grub_default_file,
            sudo=True,
        )
        cat.read(grub_default_file, sudo=True, force_run=True)

        grub_cfg = "/boot/grub2/grub.cfg"
        node.execute(
            f"grub2-mkconfig -o {grub_cfg}",
            sudo=True,
            shell=True,
        )
        cat.read(grub_cfg, sudo=True, force_run=True)

        return new_kernel


class Dom0Installer(SourceInstaller):
    @classmethod
    def type_name(cls) -> str:
        return "dom0"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return SourceInstallerSchema

    @property
    def _output_names(self) -> List[str]:
        return []

    def install(self) -> str:
        node = self._node

        # The /sbin/installkernel script in Mariner expects mariner.cfg to be present.
        # However, the dom0 variant of Mariner doesn't have it. So, `make install`
        # fails. To workaround this failure, create a blank mariner.cfg file. This has
        # no effect on dom0 since this file is not referenced anywhere by dom0 boot.
        # This is only to make the installkernel script happy.
        mariner_cfg = PurePosixPath("/boot/mariner.cfg")
        if not node.tools[Ls].path_exists(str(mariner_cfg), sudo=True):
            node.tools[Echo].write_to_file("", mariner_cfg, sudo=True)

        new_kernel = super().install()

        # If it is dom0,
        # Name of the current kernel binary should be vmlinuz-<kernel version>
        uname = node.tools[Uname]
        current_kernel = uname.get_linux_information().kernel_version_raw

        mariner_version = int(node.os.information.version.major)
        _update_mariner_v2_config(
            node,
            current_kernel,
            new_kernel,
            mariner_version,
        )

        return new_kernel


def _copy_kernel_binary(
    node: Node,
    source: PurePath,
    destination: PurePath,
) -> None:
    cp = node.tools[Cp]
    cp.copy(
        src=source,
        dest=destination,
        sudo=True,
    )


def _update_mariner_v2_config(
    node: Node,
    current_kernel: str,
    new_kernel: str,
    mariner_version: int,
) -> None:
    cat = node.tools[Cat]
    sed = node.tools[Sed]

    # Param for Dom0 3.0 kernel installation
    mariner_config = "/boot/grub2/grub.cfg"
    vmlinuz_regexp = f"vmlinuz-{current_kernel}"
    vmlinuz_replacement = f"vmlinuz-{new_kernel}"
    initrd_regexp = f"initramfs-{current_kernel}.img"
    initrd_replacement = f"initramfs-{new_kernel}.img"

    if isinstance(node.os, CBLMariner) and mariner_version <= 2:
        # Change param for Dom0 2.0 kernel installation
        mariner_config = "/boot/mariner-mshv.cfg"
        initrd_regexp = f"mariner_initrd_mshv=initrd.img-{current_kernel}"
        initrd_replacement = f"mariner_initrd_mshv=initrd.img-{new_kernel}"

    cat.read(mariner_config, sudo=True, force_run=True)

    # Modify file to point new kernel binary
    sed.substitute(
        regexp=vmlinuz_regexp,
        replacement=vmlinuz_replacement,
        file=mariner_config,
        sudo=True,
    )

    # Modify file to point new initrd binary
    sed.substitute(
        regexp=initrd_regexp,
        replacement=initrd_replacement,
        file=mariner_config,
        sudo=True,
    )

    lsblk = node.tools[Lsblk]
    root_partition = lsblk.find_partition_by_mountpoint("/", force_run=True)

    # initramfs can only understand PARTUUID
    sed.substitute(
        regexp=f"root=UUID={root_partition.uuid}",
        replacement=f"root=PARTUUID={root_partition.part_uuid}",
        file=mariner_config,
        sudo=True,
    )
    cat.read(mariner_config, sudo=True, force_run=True)
