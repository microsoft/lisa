from typing import List

from lisa.feature import Feature
from lisa.features.serial_console import SerialConsole
from lisa.util import LisaException


class NonSshExecutor(Feature):
    """
    NonSshExecutor is used to run commands on the node when SSH is not available.
    Lisa by default uses SSH for connection, but this feature provides an alternative
    execution method for scenarios where SSH connectivity is not possible or desired.
    """

    @classmethod
    def name(cls) -> str:
        return "NonSshExecutor"

    def enabled(self) -> bool:
        return True

    def execute(self, commands: List[str]) -> List[str]:
        """
        Executes a list of commands on the node and returns their outputs.

        :param commands: A list of shell commands to execute.
        :return: A string containing the output of the executed commands.
        """

        if not self._node.features.is_supported(SerialConsole):
            raise NotImplementedError(
                "NonSshExecutor requires SerialConsole feature to be supported."
            )
        out = self._execute(commands)
        return out

    def _execute(self, commands: List[str]) -> List[str]:
        out: List[str] = []
        serial_console = self._node.features[SerialConsole]
        try:
            serial_console.ensure_login()
            # clear the console before executing commands
            _ = serial_console.read()
            # write a newline and read to make sure serial console has the prompt
            serial_console.write("\n")
            response = serial_console.read()
            if not response or "$" not in response and "#" not in response:
                raise LisaException("Serial console prompt not found in output")
            for command in commands:
                serial_console.write(self._add_newline(command))
                out.append(serial_console.read())
            return out
        except Exception as e:
            raise LisaException(f"Failed to execute commands: {e}") from e
        finally:
            serial_console.close()

    def _add_newline(self, command: str) -> str:
        """
        Adds a newline character to the command if it does not already end with one.
        newline is required to run the command in serial console.
        """
        if not command.endswith("\n"):
            return f"{command}\n"
        return command
