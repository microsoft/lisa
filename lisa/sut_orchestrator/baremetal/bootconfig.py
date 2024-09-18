# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Optional, Type

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.node import quick_connect
from lisa.tools import Cat, Sed
from lisa.util import (
    InitializableMixin,
    LisaException,
    field_metadata,
    find_group_in_lines,
    subclasses,
)
from lisa.util.logger import get_logger

from .schema import BootConfigSchema

BOOT_LABEL = "label lisa baremetal"


class BootConfig(subclasses.BaseClassWithRunbookMixin, InitializableMixin):
    def __init__(
        self,
        runbook: BootConfigSchema,
    ) -> None:
        super().__init__(runbook=runbook)
        self.boot_config_runbook: BootConfigSchema = self.runbook
        self._log = get_logger("boot_config", self.__class__.__name__)

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return BootConfigSchema

    def config(self) -> None:
        raise NotImplementedError()


@dataclass_json()
@dataclass
class PxeBootSchema(BootConfigSchema):
    connection: Optional[schema.RemoteNode] = field(
        default=None, metadata=field_metadata(required=True)
    )
    host_name: str = field(default="", metadata=field_metadata(required=True))
    image_source: str = field(default="", metadata=field_metadata(required=True))
    kernel_boot_params: Optional[str] = field(default="")


class PxeBoot(BootConfig):
    def __init__(
        self,
        runbook: PxeBootSchema,
    ) -> None:
        super().__init__(runbook=runbook)
        self.pxe_runbook: PxeBootSchema = self.runbook
        self._log = get_logger("pxe_boot", self.__class__.__name__)
        self._boot_dir = "/var/lib/tftpboot/"

    @classmethod
    def type_name(cls) -> str:
        return "pxe_boot"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return PxeBootSchema

    def config(self) -> None:
        assert self.pxe_runbook.connection, "connection is required for dhcp_server"

        self.pxe_runbook.connection.name = "dhcp_server"
        self._dhcp_server = quick_connect(
            self.pxe_runbook.connection, logger_name="dhcp_server"
        )

        node_name = f"{self.pxe_runbook.host_name}"
        pxe_boot_config_path = self._get_pxe_config_path(node_name)
        if not pxe_boot_config_path:
            with open(pxe_boot_config_path, "w") as f:
                f.write("timeout 150\n\nmenu title selections\n\n")

        boot_image = PurePosixPath(
            self.pxe_runbook.image_source,
        ).relative_to(self._boot_dir)
        boot_entry = f"kernel {boot_image}"

        sed = self._dhcp_server.tools[Sed]
        # Delete the label if one is existed
        sed.delete_lines(
            f"^{BOOT_LABEL}$/,/^$",
            PurePosixPath(pxe_boot_config_path),
        )
        self._log.debug(
            "Deleted boot entry for LISA if existed"
            f"{pxe_boot_config_path}, "
            f"pointing to {boot_entry}"
        )

        # Add one at the start
        params = self.pxe_runbook.kernel_boot_params
        append = f"\\n    append {params}" if params else ""
        match_str = "/^menu.*/"
        sed.append(
            f" \\\\n{BOOT_LABEL}\\n    {boot_entry}{append}",
            f"{pxe_boot_config_path}",
            f"{match_str}",
        )

        self._log.debug(
            "Added boot entry for LISA at "
            f"{pxe_boot_config_path}, "
            f"pointing to {boot_entry}"
        )

    def _get_pxe_config_path(self, node_name: str) -> str:
        cat = self._dhcp_server.tools[Cat]
        output_dhcp_info = cat.read(
            "/etc/dhcp/dhcpd.conf",
            force_run=True,
        )
        # Here is part of output_dhcp_info
        # ...
        # host dev-gp9 {
        #    hardware ethernet 04:27:28:06:f7:88;
        #    fixed-address 192.168.3.123;
        #    option host-name "blade3";
        # }
        #
        # host dev-gp10 {
        #    hardware ethernet 04:27:28:15:3f:f0;
        #    fixed-address 192.168.3.117;
        #    option host-name "blade4";
        # }
        # ...
        # if node 10 is used to be bootup from pxe_server,
        # configuration file for node 10 on pxe_server needs
        # to be modified. The configuration file's name for
        # node 10 is actually based on its physical address:
        # 04:27:28:15:3f:f0 as you can see from the above,
        # and it is called 01-04-27-28-15-3f-f0 under bootup
        # directory. Below is to find the node's physical
        # address string 04:27:28:15:3f:f0 from output_dhcp_info
        # and then obtain the configuration file name for
        # later bootup menu change.
        host_ref = f"host {node_name}"
        pattern = host_ref + r"\s+\{\r?\n\s+hardware ethernet\s+(?P<mac>[0-9a-f:]+);"
        node_pattern = re.compile(pattern, re.M)
        node_address = find_group_in_lines(
            lines=output_dhcp_info,
            pattern=node_pattern,
            single_line=False,
        )
        if node_address:
            config_file = "01-" + node_address["mac"].replace(":", "-")
            config_file_fullpath = self._boot_dir + f"pxelinux.cfg/{config_file}"
        else:
            raise LisaException(f"Failed to find DHCP entry for {node_name}")

        return config_file_fullpath
