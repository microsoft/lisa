from typing import Any, Dict, List, Union

from lisa import (
    Logger,
    RemoteNode,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    tools,
)
from lisa.executable import Tool
from lisa.util import LisaException, SkippedException


@TestSuiteMetadata(
    area="adhoc",
    category="functional",
    description="""
    This test suite includes adhoc tests
    """,
)
class Adhoc(TestSuite):
    @TestCaseMetadata(
        description="""
        This test case will install the tools
        passed as parameter 'install_tools'
        """,
        priority=5,
    )
    def tool_install(
        self, log: Logger, node: RemoteNode, variables: Dict[str, Any]
    ) -> None:
        tool_name_parameter = "install_tools"
        tool_names: List[str] = variables.get(tool_name_parameter, [])
        if not tool_names:
            raise SkippedException(f"{tool_name_parameter} is empty")
        if type(tool_names) != list:
            raise LisaException(f"{tool_name_parameter} parameter should be List[str]")
        #  Create mapping from lowercase tool name to actual tool name
        defined_tool_mapping: Dict[str, str] = {
            tool.lower(): tool for tool in tools.__all__
        }
        for input_tool_name in tool_names:
            tool_name = defined_tool_mapping.get(input_tool_name.lower())
            if not tool_name:
                raise LisaException(f"{input_tool_name} is not a valid tool")
            tool: Union[None, Tool] = getattr(tools, tool_name)
            node.tools[tool]  # type: ignore # pylint: disable=W0104
