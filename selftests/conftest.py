from schema import Schema  # type: ignore

from target import Target


class Custom(Target):
    schema: Schema = Schema(None)
    # @property
    # @classmethod
    # def schema(cls) -> Schema:
    #     return Schema()

    def deploy(self) -> str:
        return "localhost"

    def delete(self) -> None:
        pass
