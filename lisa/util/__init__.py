# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import random
import re
import string
import sys
from datetime import datetime
from pathlib import Path
from time import sleep
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Pattern,
    Type,
    TypeVar,
    cast,
)

import pluggy
from assertpy import assert_that
from dataclasses_json import config
from marshmallow import fields
from semver import VersionInfo

from lisa import secret
from lisa.util import constants
from lisa.util.perf_timer import create_timer

if TYPE_CHECKING:
    from lisa.operating_system import OperatingSystem

T = TypeVar("T")

# regex to validate url
# source -
# https://github.com/django/django/blob/stable/1.3.x/django/core/validators.py#L45
__url_pattern = re.compile(
    r"^(?:http|ftp)s?://"  # http:// or https://
    r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)"
    r"+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|"  # ...domain
    r"localhost|"  # localhost...
    r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"  # ...or ip
    r"(?::\d+)?"  # optional port
    r"(?:/?|[/?]\S+)$",
    re.IGNORECASE,
)


# used to filter ansi escapes for better layout in log and other place
# Example:
# Text: "\x1b[?1h\x1b=\rAdd linux-next specific files for 20230221\x1b[m\r\n\r\x1b[K\x1b[?1l\x1b>"  # noqa: E501
# Escape Result: '\rAdd linux-next specific files for 20230221\r\n\r'
__ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_=<>a-kzNM78]|\[[0-?]*[ -/]*[@-~])")

# 10.0.22000.100
# 18.04.5
# 18.04
# 18
__version_info_pattern = re.compile(
    r"^[vV]?(?P<major>[0-9]*?)"
    r"(?:[\.\-\_](?P<minor>[0-9]*?))?"
    r"(?:[\.\-\_](?P<patch>[0-9]*?))?"
    r"(?:[\.\-\_](?P<prerelease>.*?))?$",
    re.VERBOSE,
)

# hooks manager helper, they must be same name.
_NAME_LISA = "lisa"
plugin_manager = pluggy.PluginManager(_NAME_LISA)
hookspec = pluggy.HookspecMarker(_NAME_LISA)
hookimpl = pluggy.HookimplMarker(_NAME_LISA)


class LisaException(Exception):
    ...


class UnsupportedOperationException(LisaException):
    """
    An operation might not be supported. Use this exception to
    indicate that explicitly.
    """

    ...


class MissingPackagesException(LisaException):
    """
    Use to signal that packages were not found during installation.
    """

    def __init__(self, packages: List[str]) -> None:
        self.packages = packages

    def __str__(self) -> str:
        return f"Package manager could not install packages: {' '.join(self.packages)}"


class UnsupportedDistroException(LisaException):
    """
    This exception is used to indicate that a test case does not support the testing
    distro.
    """

    def __init__(self, os: "OperatingSystem", message: str = "") -> None:
        self.name = os.name
        self.version = os.information.full_version
        self._extended_message = message

    def __str__(self) -> str:
        message = f"Unsupported system: '{self.version}'"
        if self._extended_message:
            message = f"{message}. {self._extended_message}"
        return message


class RepoNotExistException(LisaException):
    """
    This exception is used to indicate that a repo URL not existing issue
    """

    def __init__(self, os: "OperatingSystem", message: str = "") -> None:
        self.name = os.name
        self.version = os.information.full_version
        self._extended_message = message

    def __str__(self) -> str:
        message = f"Repo not existing in '{self.version}'"
        if self._extended_message:
            message = f"{message}. {self._extended_message}"
        return message


class ReleaseEndOfLifeException(LisaException):
    """
    This exception is used to indicate that a release is end of life
    """

    def __init__(self, os: "OperatingSystem", message: str = "") -> None:
        self.name = os.name
        self.version = os.information.full_version
        self._extended_message = message

    def __str__(self) -> str:
        message = f"The release '{self.version}' is end of life"
        if self._extended_message:
            message = f"{message}. {self._extended_message}"
        return message


class UnsupportedKernelException(LisaException):
    """
    This exception is used to indicate that a test case does not support the testing
    kernel.
    """

    def __init__(self, os: "OperatingSystem", message: str = "") -> None:
        self.version = os.information.full_version
        self.kernel_version = ""
        if hasattr(os, "get_kernel_information"):
            self.kernel_version = (
                os.get_kernel_information().raw_version  # type: ignore
            )
        self._extended_message = message

    def __str__(self) -> str:
        message = (
            f"Unsupported kernel version: '{self.kernel_version}' on '{self.version}'"
        )
        if self._extended_message:
            message = f"{message}. {self._extended_message}"
        return message


class UnsupportedCpuArchitectureException(LisaException):
    """
    This exception is used to indicate that a test case does not support the
    Architecture.
    """

    def __init__(self, arch: str = "") -> None:
        self.arch = arch

    def __str__(self) -> str:
        return f"Unsupported CPU architecture {self.arch}"


class SkippedException(LisaException):
    """
    A test case can be skipped based on runtime information.
    """

    ...


class PassedException(LisaException):
    """
    A test case may verify several things, but part of verification cannot be done. In
    this situation, the test case may be considered to passed also. Raise this
    Exception to bring an error message, and make test pass also.
    """

    ...


class BadEnvironmentStateException(LisaException):
    """
    A test might leave the environment in bad state after failing. Use this exception
    to indicate the environment is in a bad state.
    """

    ...


class NotMeetRequirementException(LisaException):
    """
    Raise when the capability doesn't meet the requirement.
    """

    ...


class ResourceAwaitableException(Exception):
    """
    Wait for more resources to create environment.
    """

    def __init__(self, resource_name: str, message: str = "") -> None:
        self.resource_name = resource_name
        self.message = message

    def __str__(self) -> str:
        return (
            f"awaitable resource '{self.resource_name}' is not enough. "
            f"{self.message}"
        )


class TcpConnectionException(LisaException):
    """
    This exception is used to indicate that VM can't be connected issue.
    """

    def __init__(
        self, address: str, port: int, tcp_error_code: int, message: str = ""
    ) -> None:
        self.address = address
        self.port = port
        self.tcp_error_code = tcp_error_code
        self.message = message

    def __str__(self) -> str:
        format_str = (
            f"cannot connect to TCP port: [{self.address}:{self.port}],"
            f" error code: {self.tcp_error_code}"
        )
        if self.message:
            format_str += f", {self.message}"
        return format_str


class LisaTimeoutException(LisaException):
    """
    This exception is used to indicate a timeout exception.
    """


class KernelPanicException(LisaException):
    """
    This exception is used to indicate kernel panic exception.
    """

    def __init__(
        self, stage: str, panics: List[Any], source: str = "serial log"
    ) -> None:
        self.stage = stage
        self.panics = panics
        self.source = source

    def __str__(self) -> str:
        return f"{self.stage} found panic in {self.source}: {self.panics}"


class ContextMixin:
    def get_context(self, context_type: Type[T]) -> T:
        if not hasattr(self, "_context"):
            self._context: T = context_type()
        else:
            assert isinstance(
                self._context, context_type
            ), f"actual: {type(self._context)}"
        return self._context

    def remove_context(self) -> None:
        if hasattr(self, "_context"):
            delattr(self, "_context")


class InitializableMixin:
    """
    This mixin uses to do one time but delay initialization work.

    __init__ shouldn't do time costing work as most design recommendation. But
    something may be done let an object works. _initialize uses to call for one time
    initialization. If an object is initialized, it do nothing.
    """

    def __init__(self) -> None:
        super().__init__()
        self._is_initialized: bool = False

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        """
        override for initialization logic. This mixin makes sure it's called only once.
        """
        raise NotImplementedError()

    def initialize(self, *args: Any, **kwargs: Any) -> None:
        """
        This is for caller, do not override it.
        """
        if not self._is_initialized:
            try:
                self._is_initialized = True
                self._initialize(*args, **kwargs)
            except Exception as identifier:
                self._is_initialized = False
                raise identifier


class BaseClassMixin:
    @classmethod
    def type_name(cls) -> str:
        raise NotImplementedError()


class SwitchableMixin:
    """
    This mixin could be used to switch the state of objects.
    """

    def _switch(self, enable: bool) -> None:
        raise NotImplementedError()

    def disable(self) -> None:
        self._switch(False)

    def enable(self) -> None:
        self._switch(True)


def get_date_str(current: Optional[datetime] = None) -> str:
    if current is None:
        current = datetime.now()
    return current.utcnow().strftime("%Y%m%d")


def get_datetime_path(current: Optional[datetime] = None) -> str:
    if current is None:
        current = datetime.now()
    date = get_date_str(current)
    time = current.utcnow().strftime("%H%M%S-%f")[:-3]
    return f"{date}-{time}"


def get_public_key_data(private_key_file_path: str) -> str:
    # TODO: support ppk, if it's needed.
    private_key_path = Path(private_key_file_path)
    if not private_key_path.exists():
        raise LisaException(f"private key file not exist {private_key_file_path}")

    public_key_file = Path(private_key_path).stem
    public_key_path = private_key_path.parent / f"{public_key_file}.pub"
    try:
        with open(public_key_path, "r") as fp:
            public_key_data = fp.read()
    except FileNotFoundError:
        raise LisaException(f"public key file not exist {public_key_path}")
    public_key_data = public_key_data.strip()
    return public_key_data


def fields_to_dict(
    src: Any,
    fields: Iterable[str],
    is_none_included: bool = False,
    ignore_non_exists: bool = False,
) -> Dict[str, Any]:
    """
    copy field values form src to dest, if it's not None
    """
    assert src
    assert fields

    result: Dict[str, Any] = {}
    for field in fields:
        if hasattr(src, field) or not ignore_non_exists:
            value = getattr(src, field)
            if is_none_included or (value is not None):
                result[field] = value
    return result


def dict_to_fields(src: Dict[str, Any], dest: Any) -> Any:
    assert src
    for field_name, field_value in src.items():
        if hasattr(dest, field_name):
            setattr(dest, field_name, field_value)
    return dest


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
            raise LisaException(f"field '{field_name}' doesn't exist on src")
        if field_value is not None:
            setattr(dest, field_name, field_value)


def find_patterns_in_lines(lines: str, patterns: List[Pattern[str]]) -> List[List[Any]]:
    """
    For each pattern: if a pattern needs one return, it returns [str]. if it
    needs multiple return, it returns like [(str, str)].
    """
    results: List[List[str]] = []
    # create a list for each pattern. If use like [[]] * len(patterns), the
    # items is the same [] object actually. It doesn't matter in this method,
    # because the list is assigned each time. But it may mislead others, and
    # make potential bug in other places.
    for _ in range(len(patterns)):
        results.append([])
    for index, pattern in enumerate(patterns):
        if not results[index]:
            results[index] = pattern.findall(lines)
    return results


def get_matched_str(
    content: str, pattern: Pattern[str], first_match: bool = True
) -> str:
    result: str = ""
    if content:
        matched_item = pattern.findall(content)
        if matched_item:
            # if something matched, it's like ['matched']
            result = matched_item[0 if first_match else -1]
    return result


def find_patterns_groups_in_lines(
    lines: str, patterns: List[Pattern[str]], single_line: bool = True
) -> List[List[Dict[str, str]]]:
    """
    for each pattern find the matches and return with group names.
    """
    results: List[List[Dict[str, str]]] = []
    # create a list for each pattern.
    for _ in range(len(patterns)):
        results.append([])
    if single_line:
        for line in lines.splitlines(keepends=False):
            for index, pattern in enumerate(patterns):
                matches = pattern.match(line)
                if matches:
                    results[index].append(matches.groupdict())
    else:
        for index, pattern in enumerate(patterns):
            finds = pattern.findall(lines)
            for find in finds:
                results[index].append(dict(zip(pattern.groupindex, find)))
    return results


def find_groups_in_lines(
    lines: str, pattern: Pattern[str], single_line: bool = True
) -> List[Dict[str, str]]:
    return find_patterns_groups_in_lines(lines, [pattern], single_line)[0]


def find_group_in_lines(
    lines: str, pattern: Pattern[str], single_line: bool = True
) -> Dict[str, str]:
    output = find_groups_in_lines(lines, pattern, single_line)
    if len(output) == 1:
        result = output[0]
    elif len(output) == 0:
        result = {}
    else:
        raise LisaException(
            f"pattern returns more than one result, use find_groups_in_lines."
            f"results: {output}"
        )

    return result


def deep_update_dict(src: Dict[str, Any], dest: Dict[str, Any]) -> Dict[str, Any]:
    if (
        dest is None
        or isinstance(dest, int)
        or isinstance(dest, bool)
        or isinstance(dest, float)
        or isinstance(dest, str)
    ):
        result = dest
    else:
        result = dest.copy()

    if isinstance(result, dict):
        for key, value in src.items():
            if isinstance(value, dict) and key in dest:
                value = deep_update_dict(value, dest[key])
            result[key] = value
    elif isinstance(src, dict):
        result = src.copy()
    else:
        result = src

    return result


def is_valid_url(url: str, raise_error: bool = True) -> bool:
    is_url = True
    if __url_pattern.match(url) is None:
        if raise_error:
            raise LisaException(f"invalid url: {url}")
        else:
            is_url = False
    return is_url


def filter_ansi_escape(content: str) -> str:
    return __ansi_escape.sub("", content)


def dump_file(file_name: Path, content: Any) -> None:
    # This is for path validation. If provided file path isn't under run local path,
    # an error will be raised. Want to ensure logs only put under run local path
    file_name.absolute().relative_to(constants.RUN_LOCAL_LOG_PATH)
    file_name.parent.mkdir(parents=True, exist_ok=True)
    with open(file_name, "w") as f:
        f.write(secret.mask(content))


def parse_version(version: str) -> VersionInfo:
    """
    Convert an incomplete version string into a semver-compatible Version
    object

    source -
    https://python-semver.readthedocs.io/en/latest/usage.html#dealing-with-invalid-versions

    * Tries to detect a "basic" version string (``major.minor.patch``).
    * If not enough components can be found, missing components are
        set to zero to obtain a valid semver version.

    :param str version: the version string to convert
    :return: a tuple with a :class:`Version` instance (or ``None``
        if it's not a version) and the rest of the string which doesn't
        belong to a basic version.
    :rtype: tuple(:class:`Version` | None, str)
    """
    if VersionInfo.isvalid(version):
        return VersionInfo.parse(version)

    match = __version_info_pattern.search(version)
    if not match:
        raise LisaException(f"The version is invalid format: {version}")

    ver: Dict[str, Any] = {
        key: 0 if value is None else int(value)
        for key, value in match.groupdict().items()
        if key != "prerelease"
    }
    ver["prerelease"] = match["prerelease"]
    rest = match.string[match.end() :]  # noqa:E203
    ver["build"] = rest
    release_version = VersionInfo(**ver)

    return release_version


def field_metadata(
    field_function: Optional[Callable[..., Any]] = None, *args: Any, **kwargs: Any
) -> Any:
    """
    wrap for shorter
    """
    if field_function is None:
        field_function = fields.Raw
    assert field_function
    encoder = kwargs.pop("encoder", None)
    decoder = kwargs.pop("decoder", None)
    # keep data_key for underlying marshmallow
    field_name = kwargs.get("data_key")
    return config(
        field_name=cast(str, field_name),
        encoder=encoder,
        decoder=decoder,
        mm_field=field_function(*args, **kwargs),
    )


def is_unittest() -> bool:
    return "unittest" in sys.argv[0]


def truncate_keep_prefix(content: str, kept_len: int, prefix: str = "lisa-") -> str:
    """
    This method is used to truncate names, when some resource has length
    limitation. It keeps meaningful part and the defined prefix.

    To support custom names. if the string size doesn't exceed the limitation,
    there is no any validation and truncate.

    The last chars include the datetime pattern, it's more unique than leading
    project/test pass names. The name is used to identify lisa deployed
    environment too, so it needs to keep the leading "lisa-" after truncated.

    This makes the name from lisa-long-name... to lisa-name...
    """

    # do nothing, if the string is shorter than required.
    if len(content) <= kept_len:
        return content

    if not content.startswith(prefix):
        assert_that(content).described_as(
            "truncate_keep_prefix should be start with prefix"
        ).starts_with(prefix)
    if kept_len < len(prefix):
        assert_that(len(prefix)).described_as(
            f"kept length must be greater than prefix '{prefix}'"
        ).is_less_than_or_equal_to(kept_len)
    return f"{prefix}{content[len(prefix) : ][-kept_len+len(prefix):]}"


def generate_random_chars(
    candidates: str = string.ascii_letters + string.digits, length: int = 20
) -> str:
    return "".join(random.choices(candidates, k=length))


def strip_strs(obj: Any, fields: List[str]) -> Any:
    for field in fields:
        if hasattr(obj, field):
            value = getattr(obj, field)
            value = value.strip() if isinstance(value, str) else value
            setattr(obj, field, value)
    return obj


def check_till_timeout(
    func: Callable[..., Any],
    timeout_message: str,
    timeout: int = 60,
    interval: int = 1,
) -> None:
    timer = create_timer()
    while timer.elapsed(False) < timeout:
        if func():
            break
        sleep(interval)
    if timer.elapsed() >= timeout:
        raise LisaException(f"timeout: {timeout_message}")
