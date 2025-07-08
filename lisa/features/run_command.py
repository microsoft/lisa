from typing import List

from lisa.feature import Feature

FEATURE_NAME_RUNCOMMAND = "RunCommand"


class RunCommand(Feature):
    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_RUNCOMMAND

    def execute(self, commands: List[str]) -> str:
        """
        Executes a list of commands on the node and returns their outputs.

        :param commands: A list of shell commands to execute.
        :return: A list of outputs corresponding to each command.
        """
        raise NotImplementedError(
            "The execute method must be implemented by the subclass."
        )
