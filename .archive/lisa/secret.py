import re
from typing import Any, List, Optional, Pattern, Set, Tuple, Union

PATTERN_GUID = (
    re.compile(r"^([0-9a-f]{8})-(?:[0-9a-f]{4}-){3}[0-9a-f]{8}([0-9a-f]{4})$"),
    r"\1-****-****-****-********\2",
)
PATTERN_HEADTAIL = (
    re.compile(r"^([\w])[\W\w]+([\w])$"),
    r"\1****\2",
)
PATTERN_FILENAME = (
    re.compile(r"^[^.]*?[\\/]?(.)[^\\/]*?(.[.]?[^.]*)$"),
    r"\1***\2",
)

patterns = {"guid": PATTERN_GUID, "headtail": PATTERN_HEADTAIL}


def replace(
    origin: Any,
    mask: Optional[Union[Pattern[str], Tuple[Pattern[str], str]]] = None,
    sub: str = "******",
) -> str:
    if mask:
        if isinstance(mask, tuple):
            configured_sub = mask[1]
            mask = mask[0]
        else:
            configured_sub = sub
        result = mask.sub(configured_sub, origin)
        if result == origin:
            # failed and fallback
            result = sub
        return result
    else:
        return sub


_secret_list: List[Tuple[str, str]] = list()
_secret_set: Set[str] = set()


def reset() -> None:
    _secret_set.clear()
    _secret_list.clear()


def add_secret(
    origin: Any,
    mask: Optional[Union[Pattern[str], Tuple[Pattern[str], str]]] = None,
    sub: str = "******",
) -> None:
    global _secret_list
    if origin and origin not in _secret_set:
        if not isinstance(origin, str):
            origin = str(origin)
        _secret_set.add(origin)
        _secret_list.append((origin, replace(origin, sub=sub, mask=mask)))
        # deal with longer first, in case it's broken by shorter
        _secret_list = sorted(_secret_list, reverse=True, key=lambda x: len(x[0]))


def mask(input: str) -> str:
    for secret in _secret_list:
        if secret[0] in input:
            input = input.replace(secret[0], secret[1])
    return input
