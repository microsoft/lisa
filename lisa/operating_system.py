from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from lisa.node import Node


class OperatingSystem:
    def __init__(self, node: Any, is_linux: bool) -> None:
        super().__init__()
        self._node: Node = node
        self._is_linux = is_linux

    @property
    def is_windows(self) -> bool:
        return not self._is_linux

    @property
    def is_linux(self) -> bool:
        return self._is_linux


class Windows(OperatingSystem):
    def __init__(self, node: Any) -> None:
        super().__init__(node, is_linux=False)


class Linux(OperatingSystem):
    def __init__(self, node: Any) -> None:
        super().__init__(node, is_linux=True)
