from pathlib import Path
from typing import Type, TypeVar

T = TypeVar("T")


class LisaException(Exception):
    pass


class ContextMixin:
    def get_context(self, context_type: Type[T]) -> T:
        if not hasattr(self, "_context"):
            self._context: T = context_type()
        else:
            assert isinstance(self._context, context_type)
        return self._context


def get_public_key_data(private_key_file_path: str) -> str:

    # TODO: support ppk, if it's needed.
    private_key_path = Path(private_key_file_path)
    if not private_key_path.exists:
        raise LisaException(f"private key file not exist {private_key_file_path}")
    public_key_path = private_key_path.parent / f"{private_key_path.name}.pub"
    if not public_key_path.exists:
        raise LisaException(f"private key file not exist {public_key_path}")
    with open(public_key_path, "r") as fp:
        public_key_data = fp.read()
    return public_key_data
