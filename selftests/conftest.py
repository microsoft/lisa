from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    from typing import Any, Mapping

from target import Target


class Custom(Target):
    @classmethod
    def schema(cls) -> Mapping[Any, Any]:
        return {}

    def deploy(self) -> str:
        return "localhost"

    def delete(self) -> None:
        pass
