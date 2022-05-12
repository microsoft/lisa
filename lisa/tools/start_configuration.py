# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePosixPath

from lisa.executable import Tool
from lisa.tools.echo import Echo


class StartConfiguration(Tool):
    """
    StartConfiguration is a tool that can be used to add commands to the /etc/rc.local
    file. The commands will be executed at boot time.
    """

    @property
    def command(self) -> str:
        return ""

    @property
    def can_install(self) -> bool:
        return True

    def add_command(self, command: str) -> None:
        # add command to /etc/rc.local
        # The command will be executed at boot time
        self.node.tools[Echo].write_to_file(
            command, PurePosixPath("/etc/rc.local"), append=True, sudo=True
        )

    def _check_exists(self) -> bool:
        # check if /etc/rc.local exists
        return self.node.shell.exists(PurePosixPath("/etc/rc.local"))

    def _install(self) -> bool:
        # create rc.local file at /etc/rc.local
        # with shbang #!/bin/sh
        self.node.tools[Echo].write_to_file(
            "#!/bin/sh -e", PurePosixPath("/etc/rc.local"), append=True, sudo=True
        )

        # add executable permissions to /etc/rc.local
        self.node.execute("chmod +x /etc/rc.local", sudo=True)

        return self._check_exists()
