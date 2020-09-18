from abc import abstractmethod
from pathlib import Path
from typing import Any, Dict, Iterable, List, Type, TypeVar

T = TypeVar("T")


class LisaException(Exception):
    pass


class ContextMixin:
    def get_context(self, context_type: Type[T]) -> T:
        if not hasattr(self, "_context"):
            self._context: T = context_type()
        else:
            assert isinstance(
                self._context, context_type
            ), f"actual: {type(self._context)}"
        return self._context


class InitializableMixin:
    def __init__(self) -> None:
        self._is_initialized: bool = False

    @abstractmethod
    def _initialize(self) -> None:
        raise NotImplementedError()

    def initialize(self) -> None:
        if not self._is_initialized:
            try:
                self._is_initialized = True
                self._initialize()
            except Exception as identifier:
                self._is_initialized = False
                raise identifier


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


def fields_to_dict(src: Any, fields: Iterable[str]) -> Dict[str, Any]:
    """
    copy field values form src to dest, if it's not None
    """
    assert src
    assert fields

    result: Dict[str, Any] = dict()
    for field in fields:
        value = getattr(src, field)
        if value is not None:
            result[field] = value
    return result


def set_filtered_fields(src: Any, dest: Any, fields: List[str]) -> None:
    """
    copy field values form src to dest, if it's not None
    """
    assert src
    assert dest
    assert fields
    for field_name in fields:
        if hasattr(src, field_name):
            field_value = getattr(src, field_name)
        else:
            raise LisaException(f"field {field_name} doesn't exist on src")
        if field_value is not None:
            setattr(dest, field_name, field_value)
