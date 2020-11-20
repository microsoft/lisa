from schema import Schema  # type: ignore
from target import Target


class Custom(Target):
    @classmethod
    def schema(cls) -> Schema:
        return Schema(None)

    def deploy(self) -> str:
        return "localhost"

    def delete(self) -> None:
        pass
