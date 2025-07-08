from lisa.feature import Feature
from lisa.features.serial_console import SerialConsole


class NonSshExecutor(Feature):
    """
    NonSshExecutor is used to run commands on the node when SSH is not available.
    Lisa by default uses SSH for connection, but this feature provides an alternative
    execution method for scenarios where SSH connectivity is not possible or desired.
    """

    COMMANDS_TO_EXECUTE = [
        "ip addr show",
        "ip link show",
        "systemctl status NetworkManager --no-pager --plain",
        "systemctl status network --no-pager --plain",
        "systemctl status systemd-networkd --no-pager --plain",
        "ping -c 3 -n 8.8.8.8",
    ]

    @classmethod
    def name(cls) -> str:
        return "NonSshExecutor"

    def enabled(self) -> bool:
        return True

    def execute(self, commands: list[str] = COMMANDS_TO_EXECUTE) -> list[str]:
        """
        Executes a list of commands on the node and returns their outputs.

        :param commands: A list of shell commands to execute.
        :return: A string containing the output of the executed commands.
        """
        out = []
        serial_console = self._node.features[SerialConsole]
        serial_console.login()
        # clear the console before executing commands
        serial_console.write("\n")
        _ = serial_console.read()
        for command in commands:
            serial_console.write(self._add_newline(command))
            out.append(serial_console.read())
        return out

    def _add_newline(self, command: str) -> str:
        """
        Adds a newline character to the command if it does not already end with one.
        newline is required to run the command in serial console.
        """
        if not command.endswith("\n"):
            return f"{command}\n"
        return command
