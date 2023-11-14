from dataclasses import dataclass, field
from typing import Any, Optional

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.node import Node, quick_connect
from lisa.transformer import Transformer
from lisa.util import field_metadata


@dataclass_json
@dataclass
class DeploymentTransformerSchema(schema.Transformer):
    # SSH connection information to the node
    connection: Optional[schema.RemoteNode] = field(
        default=None, metadata=field_metadata(required=False)
    )


class DeploymentTransformer(Transformer):
    def __init__(
        self,
        runbook: DeploymentTransformerSchema,
        node: Optional[Node] = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(runbook, *args, **kwargs)
        if node:
            self._node = node
        else:
            assert (
                runbook.connection
            ), "'connection' must be defined if not running during deployed phase."
            self._node = quick_connect(
                runbook.connection, runbook.name, parent_logger=self._log
            )

    @classmethod
    def type_name(cls) -> str:
        return "deployment"
