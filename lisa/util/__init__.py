# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import hashlib
import ipaddress
import random
import re
import string
import sys
from copy import deepcopy
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from threading import Lock
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
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
)

import paramiko
import pluggy
import requests
from assertpy import assert_that
from dataclasses_json import config
from marshmallow import fields
from retry import retry
from semver import VersionInfo

from lisa import secret
from lisa.util import constants
from lisa.util.perf_timer import create_timer

if TYPE_CHECKING:
    from lisa.operating_system import OperatingSystem
    from lisa.testsuite import TestResult
    from lisa.util.logger import Logger

T = TypeVar("T")
global_ssh_key_access_lock = Lock()

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


# Used to filter ANSI escape sequences for better layout in logs and other
# output. ANSI escapes are special character sequences that control terminal
# behavior (colors, cursor movement, etc.) but interfere with text parsing.
#
# Examples of sequences we filter:
# 1. CSI (Control Sequence Introducer): "\x1b[31m" (red color), "\x1b[2J"
# 2. OSC (Operating System Command): "\x1b]0;Title\x07" (set window title)
# 3. OSC 3008 audit logs: "\x1b]3008;user=test;...\x1b\" (sudo audit from
#    systemd 258+)
# 4. Single-char escapes: "\x1bM" (reverse line feed), "\x1b7" (save cursor)
#
# Note: This regex captures the most common ANSI sequences encountered in
# terminal output. It does NOT capture all possible ANSI escapes (e.g., DCS,
# PM, APC sequences), but it handles the sequences that typically appear in
# command output and logs. For LISA's use case (filtering terminal output for
# parsing), this provides sufficient coverage.
#
# Pattern breakdown (order matters - OSC must come first!):
# 1. OSC sequences: ESC ] <data> (BEL|ESC\)
#    - Matches: \x1b]...\x07 or \x1b]...\x1b\
#    - Must be first to prevent ']' from matching in single-char range
# 2. Single-char escapes: ESC followed by one character from
#    [@-Z\\-_=<>a-kzNM78]
#    - Matches: \x1b7, \x1bM, etc.
# 3. CSI sequences: ESC [ <params> <command>
#    - Matches: \x1b[31m, \x1b[2J, etc.
__ansi_escape = re.compile(
    r"\x1B(?:"  # Start: ESC character followed by one of three patterns
    # Pattern 1: OSC (Operating System Command) - ESC ] <data> <terminator>
    r"\]"  # Literal ']' character after ESC
    # Data: any char except BEL/ESC, or ESC not followed by \ # noqa: E502
    r"(?:[^\x07\x1B]|\x1B(?!\\))*"
    r"(?:\x07|\x1B\\)"  # Terminator: BEL (\x07) or ST (ESC \)
    r"|"  # OR
    # Pattern 2: Single-character escapes - ESC <char>
    r"[@-Z\\-_=<>a-kzNM78]"  # One character from these ranges
    r"|"  # OR
    # Pattern 3: CSI (Control Sequence Introducer) - ESC [ <params> <final>
    r"\["  # Literal '[' character after ESC
    r"[0-?]*"  # Parameter bytes (optional)
    r"[ -/]*"  # Intermediate bytes (optional)
    r"[@-~]"  # Final byte (required)
    r")"  # End of alternation
)

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


PANIC_PATTERNS: List[Pattern[str]] = [
    re.compile(r"^(.*Kernel panic - not syncing:.*)$", re.MULTILINE),
    re.compile(r"^(.*RIP:.*)$", re.MULTILINE),
    re.compile(r"^(.*grub>.*)$", re.MULTILINE),
    re.compile(r"^The operating system has halted.$", re.MULTILINE),
    # Synchronous Exception at 0x000000003FD04000
    re.compile(r"^(.*Synchronous Exception at.*)$", re.MULTILINE),
]

# ignore some return lines, which shouldn't be a panic line.
PANIC_IGNORABLE_PATTERNS: List[Pattern[str]] = [
    re.compile(r"^(.*ipt_CLUSTERIP: ClusterIP.*loaded successfully.*)$", re.MULTILINE),
    # This is a known issue with Hyper-V when running on AMD processors.
    # The problem occurs in VM sizes that have 16 or more vCPUs which means 2 or
    # more NUMA nodes on AMD processors.
    # The call trace is annoying but does not affect correct operation of the VM.
    re.compile(r"(.*RIP: 0010:topology_sane.isra.*)$", re.MULTILINE),
]

TEST_PANIC_PATTERNS: List[Pattern[str]] = [
    # Rust panics - must have "panicked at" with backtrace markers
    re.compile(r"^(.*panicked at .*)$", re.MULTILINE),
    re.compile(r"^(.*stack backtrace:.*)$", re.MULTILINE | re.IGNORECASE),
]

# Root filesystem mount failure patterns
ROOTFS_FAILURE_PATTERNS: List[Pattern[str]] = [
    # Warning: dracut-initqueue timeout - starting timeout scripts
    # Warning: dracut-initqueue: starting timeout scripts
    re.compile(r"^(.*dracut-initqueue.*timeout.*)$", re.MULTILINE),
    # ALERT!  UUID=fbf1c3fe-02ca-4347-93ae-458f0bce93a6 does not exist.  Dropping to a shell!  # noqa: E501
    re.compile(r"^(.*UUID=.*does not exist.*)$", re.MULTILINE),
]


class LisaException(Exception):
    def __init__(self, *args: object) -> None:
        args = tuple(secret.mask(arg) if isinstance(arg, str) else arg for arg in args)
        super().__init__(*args)


class DeploymentActiveException(LisaException):
    """
    This exception is used to indicate that there is an active deployment with the same name. It may be caused by the previous deployment not cleaned up yet.
    LISA should catch this exception and retry the deployment after a timeout period to allow the old environment to be cleaned up.
    """

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


class NotEnoughMemoryException(LisaException):
    """
    This exception is used to indicate that that the system does not have enough memory.
    """

    def __init__(self, message: str = "") -> None:
        self._extended_message = message

    def __str__(self) -> str:
        message = "Not enough memory"
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
        return (
            f"{self.stage} found panic in {self.source}. You can check the panic "
            "details from the serial console log. Please download the test logs and "
            "retrieve the serial_log from 'environments' directory, or you can ask "
            f"support. Detected Panic phrases: {self.panics}"
        )


class PostTestPanicDetectedError(LisaException):
    """
    This exception is raised when a test panic is detected in test output.
    """

    def __init__(self, stage: str, panics: List[Any], source: str = "test log") -> None:
        self.stage = stage
        self.panics = panics
        self.source = source
        super().__init__(str(self))

    def __str__(self) -> str:
        return (
            f"{self.stage} found test panic in {self.source}. "
            f"Detected Test Panic lines: {self.panics}"
        )


class RootFsMountFailedException(LisaException):
    """
    This exception is used to indicate root filesystem mount failure.
    """

    def __init__(self, message: List[Any], source: str = "serial log") -> None:
        self.message = message
        self.source = source

    def __str__(self) -> str:
        return (
            f"found root filesystem mount failure in {self.source}. Possible causes "
            "include: missing or incorrect UUID, unsupported or corrupted filesystem, "
            "or missing storage drivers. Please verify disk presence, UUID accuracy, "
            f"and initramfs contents. Detected root filesystem issues: {self.message}"
        )


class RequireUserPasswordException(LisaException):
    """
    This exception is used to indicate the exception that running commands
    require an input of user password
    """


class SshSpawnTimeoutException(LisaException):
    """
    This exception is used to indicate a timeout while spawning a process
    using SshShell.
    """


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
            except Exception as e:
                self._is_initialized = False
                raise e


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


class LisaVersionInfo(VersionInfo):
    def __init__(self, version_str: str, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.version_str = version_str

    @classmethod
    def parse(cls, version: str) -> "LisaVersionInfo":
        version_info = VersionInfo.parse(version)
        return LisaVersionInfo(version, *version_info.to_tuple())


def get_date_str(current: Optional[datetime] = None) -> str:
    if current is None:
        current = datetime.now()
    return current.now(timezone.utc).strftime("%Y%m%d")


def get_datetime_path(current: Optional[datetime] = None) -> str:
    if current is None:
        current = datetime.now()
    date = get_date_str(current)
    time = current.now(timezone.utc).strftime("%H%M%S-%f")[:-3]
    return f"{date}-{time}"


algorthim_dict: Dict[str, Any] = {
    "RSA": paramiko.RSAKey,
    "DSA": paramiko.DSSKey,
    "ECDSA": paramiko.ECDSAKey,
}


def get_or_generate_key_pairs(
    log: "Logger", key_length: int = 2048, algorthim: str = "RSA"
) -> str:
    # refer: https://learn.microsoft.com/en-us/azure/virtual-machines/linux/create-ssh-keys-detailed#supported-ssh-key-formats # noqa: E501
    # azure platform key accepts only RSA key with minimum length of 2048 bits.
    # for some older distro, it only supports 2048 bits.
    public_key_file: str = str(constants.RUN_LOCAL_LOG_PATH / "id_rsa.pub")
    private_key_file: str = str(constants.RUN_LOCAL_LOG_PATH / "id_rsa")

    if not (Path(private_key_file).exists() and Path(public_key_file).exists()):
        key_class = algorthim_dict.get(algorthim.upper(), None)
        assert key_class, f"unsupported key algorthim: {algorthim}"
        key = key_class.generate(key_length)
        with global_ssh_key_access_lock:
            with open(private_key_file, "w") as f:
                key.write_private_key(f)
            with open(public_key_file, "w") as f:
                f.write(f"{key.get_name()} {key.get_base64()}")
        log.info(f"ssh key is generated at {private_key_file}")
    return private_key_file


def get_public_key_data(private_key_file_path: str = "") -> str:
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
            # deep copy, to avoid reference issue.
            copied_value = deepcopy(field_value)
            setattr(dest, field_name, copied_value)


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
            if len(pattern.groupindex) == 1:
                # if there is only one group, findall returns the string, not a list.
                results[index].append(dict(zip(pattern.groupindex, finds)))
            else:
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


def parse_version(version: str) -> LisaVersionInfo:
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
    if LisaVersionInfo.isvalid(version):
        return LisaVersionInfo.parse(version)

    match = __version_info_pattern.search(version)
    if not match:
        raise LisaException(f"The version is invalid format: {version}")

    ver: Dict[str, Any] = {
        key: 0 if value is None else int(value)
        for key, value in match.groupdict().items()
        if key != "prerelease"
    }
    ver["prerelease"] = match["prerelease"]
    rest = match.string[match.end() :]
    ver["build"] = rest
    release_version = LisaVersionInfo(version, **ver)

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
    return f"{prefix}{content[len(prefix) :][-kept_len + len(prefix):]}"


def generate_random_chars(
    candidates: str = string.ascii_letters + string.digits, length: int = 20
) -> str:
    return "".join(random.choices(candidates, k=length))


def generate_strong_password(length: int = 20) -> str:
    if length < 4:
        raise ValueError("length must be greater than 4 to contains all types.")

    # Removed \ and - from standard punctuation due to Azure password doesn't support.
    special_chars = r"""!"#$%&'()*+,./:;<=>?@[]^_`{|}~"""
    upper_char = random.choice(string.ascii_uppercase)
    lower_char = random.choice(string.ascii_lowercase)
    digit_char = random.choice(string.digits)
    special_char = random.choice(special_chars)
    password = list(
        upper_char
        + lower_char
        + digit_char
        + special_char
        + generate_random_chars(
            candidates=string.ascii_letters + string.digits + special_chars,
            length=length - 4,
        )
    )
    random.shuffle(password)
    return "".join(password)


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
        raise LisaTimeoutException(f"timeout: {timeout_message}")


def retry_without_exceptions(
    skipped_exceptions: List[Type[Exception]],
    tries: int = -1,
    delay: float = 0,
    max_delay: Optional[float] = None,
    backoff: float = 1,
    jitter: Union[Tuple[float, float], float] = 0,
    logger: Optional["Logger"] = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: object, **kwargs: object) -> T:
            current_delay = delay
            current_tries = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if any(isinstance(e, ex_type) for ex_type in skipped_exceptions):
                        raise
                    else:
                        current_tries += 1
                        if current_tries == tries:
                            raise
                        if max_delay is not None and current_delay > max_delay:
                            current_delay = max_delay
                        sleep(current_delay)
                        # Apply jitter if it's specified as a tuple (min, max)
                        if isinstance(jitter, tuple):
                            current_delay += random.uniform(jitter[0], jitter[1])
                        elif jitter > 0:
                            current_delay += random.uniform(0, jitter)
                        current_delay *= backoff

                        if logger:
                            logger.info(
                                "Retrying in %s seconds...",
                                round(current_delay, 2),
                                exc_info=True,
                            )

        return wrapper

    return decorator


def get_first_combination(
    items: List[Any],
    index: int,
    results: List[Any],
    check: Callable[[List[Any]], bool],
    next_value: Callable[..., Any],
    can_early_stop: bool = False,
) -> bool:
    if index == len(items):
        if check(results):
            return True
        return False

    if can_early_stop and not check(results):
        return False

    item = items[index]
    for data in next_value(item):
        results.append(data)
        if get_first_combination(
            items=items,
            index=index + 1,
            results=results,
            check=check,
            next_value=next_value,
            can_early_stop=can_early_stop,
        ):
            return True
        results.pop()

    return False


def check_panic(content: str, stage: str, log: "Logger") -> None:
    log.debug("checking panic...")
    ignored_candidates = [
        x
        for sublist in find_patterns_in_lines(str(content), PANIC_IGNORABLE_PATTERNS)
        for x in sublist
        if x
    ]
    panics = [
        x
        for sublist in find_patterns_in_lines(str(content), PANIC_PATTERNS)
        for x in sublist
        if x and x not in ignored_candidates
    ]

    if panics:
        raise KernelPanicException(stage, panics)


def append_test_panic_to_test_result(
    test_result: "TestResult", node_name: str, panics: List[str]
) -> None:
    # Filter out empty/whitespace-only lines and remove duplicates
    # while preserving order
    filtered_panics = [p.strip() for p in panics if p and p.strip()]
    unique_panics = list(dict.fromkeys(filtered_panics))
    panic_lines = "\n".join(unique_panics)

    panic_id = hashlib.sha256(f"{node_name}\x00{panic_lines}".encode()).hexdigest()[:16]

    panic_summary = (
        f"TEST PANIC DETECTED on {node_name} [id:{panic_id}]\n"
        f"Detected Test Panic Lines:\n{panic_lines}\n"
    )

    # Check if we've already added this exact panic (by id) to avoid duplicates
    # from both success and failure paths
    if test_result.message and f"[id:{panic_id}]" in test_result.message:
        return

    if test_result.message:
        test_result.message += f"\n\n{panic_summary}"
    else:
        test_result.message = panic_summary


def check_test_panic(
    content: str,
    stage: str,
    log: "Logger",
    test_result: Optional["TestResult"] = None,
    node_name: str = "",
    source: str = "test log",
) -> None:
    log.debug("checking test panic...")
    panics = [
        x
        for sublist in find_patterns_in_lines(str(content), TEST_PANIC_PATTERNS)
        for x in sublist
        if x
    ]

    if panics:
        if test_result is not None:
            # Append panic info to existing test result message, don't raise
            append_test_panic_to_test_result(test_result, node_name, panics)
        else:
            # Only raise exception if no test_result context
            raise PostTestPanicDetectedError(stage, panics, source)


def check_rootfs_failure(content: str, log: "Logger") -> None:
    """
    Check if console log contains root filesystem mount failure message.
    If found, raise RootFsMountFailedException.
    """
    log.debug("checking root filesystem mount failure...")
    matched = find_patterns_in_lines(str(content), ROOTFS_FAILURE_PATTERNS)
    all_matches = [item for sublist in matched for item in sublist]
    if all_matches:
        raise RootFsMountFailedException(all_matches)


def to_bool(value: Union[str, bool, int]) -> bool:
    """
    Convert a string to a boolean value.
    Returns sensible "True/False" values for strings, bools and ints, failing
    otherwise.
    Allows for casing and leading/trailing whitespace.
    """
    str_to_bool_map = {
        "true": True,
        "false": False,
        "yes": True,
        "no": False,
        "1": True,
        "0": False,
    }

    # Handle boolean values directly
    if isinstance(value, bool):
        return value

    # Handle integer values directly
    if isinstance(value, int):
        return bool(value)

    # If the value is a string, convert it to lowercase and strip whitespace
    # and look it up in the dictionary.
    if isinstance(value, str):
        value = value.lower().strip()
        bool_value = str_to_bool_map.get(value)
        if bool_value is None:
            raise ValueError(f"Invalid boolean string: {value}")
        return bool_value

    # If the value is not a string, boolean, or integer, raise an error.
    raise TypeError(
        f"Unsupported type for conversion to boolean: {type(value).__name__}"
    )


@retry(tries=10, delay=0.5)  # type: ignore
def get_public_ip() -> str:
    response = requests.get("https://api.ipify.org/", timeout=5)
    result = response.text
    ipaddress.ip_address(result)
    return str(result)
