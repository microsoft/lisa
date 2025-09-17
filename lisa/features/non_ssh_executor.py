import re
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

            # Check for full prompt pattern instead of individual characters
            if not self._is_valid_prompt(response):
                raise LisaException(
                    f"Valid shell prompt not found in output. "
                    f"Expected a shell prompt ending with $, #, or >, "
                    f"but got: {response.strip()}"
                )

            for command in commands:
                serial_console.write(self._add_newline(command))
                out.append(serial_console.read())
            collected_info = "\n\n".join(out)
            self._log.info(
                f"Collected information using NonSshExecutor:\n{collected_info}"
            )
            return out
        except Exception as e:
            raise LisaException(f"Failed to execute commands: {e}") from e
        finally:
            serial_console.close()

    def _is_valid_prompt(self, response: str) -> bool:
        """
        Check if the response contains a valid shell prompt pattern.

        :param response: The response from the serial console
        :return: True if a valid prompt is found, False otherwise
        """
        if not response:
            return False

        # Generic pattern that matches any prompt format:
        # - Username and hostname part: word chars, @, hyphens, dots
        # - Colon separator
        # - Path part: ~, /, word chars, dots, hyphens, slashes
        # - Optional whitespace
        # - Ending with $, #, or >
        # - Optional trailing whitespace
        prompt_pattern = r"[a-zA-Z0-9_@.-]+:[~/a-zA-Z0-9_./-]*\s*[\$#>]\s*$"

        # Check each line in the response for the prompt pattern
        lines = response.split("\n")
        for line in lines:
            line = line.strip()
            if re.search(prompt_pattern, line):
                self._log.debug(f"Valid prompt found: '{line}'")
                return True

        self._log.debug(f"No valid prompt found in response: '{response.strip()}'")
        return False

    def _add_newline(self, command: str) -> str:
        """
        Adds a newline character to the command if it does not already end with one.
        newline is required to run the command in serial console.
        """
        if not command.endswith("\n"):
            return f"{command}\n"
        return command
