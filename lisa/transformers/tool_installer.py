from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

from dataclasses_json import dataclass_json

from lisa import schema, tools
from lisa.executable import Tool
from lisa.node import quick_connect
from lisa.transformer import Transformer
from lisa.util import LisaException, field_metadata


@dataclass_json
@dataclass
class ToolInstallerTransformerSchema(schema.Transformer):
    tool_names: List[str] = field(default_factory=List[str])
    # the SSH connection information to the node
    connection: Optional[schema.RemoteNode] = field(
        default=None, metadata=field_metadata(required=True)
    )


class ToolInstallerTransformer(Transformer):
    """
    Accepts tool names and VM details.
    Installs the specified tools on the VM
    """

    @classmethod
    def type_name(cls) -> str:
        return "tool_installer"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return ToolInstallerTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        return []

    def _internal_run(self) -> Dict[str, Any]:
        runbook: ToolInstallerTransformerSchema = self.runbook
        assert runbook.connection, "connection must be defined."
        assert runbook.tool_names, "installer must be defined."

        node = quick_connect(runbook.connection, "remote_node")

        for tool_name in runbook.tool_names:
            if tool_name not in tools.__all__:
                raise LisaException(f"{tool_name} is not a valid tool")
            tool: None | Tool = getattr(tools, tool_name)
            if tool:
                node.tools[tool]

        return {}
