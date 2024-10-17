# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
import time
from dataclasses import dataclass
from enum import Enum
from functools import partial
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Iterable,
    List,
    Match,
    Optional,
    Pattern,
    Sequence,
    Type,
    Union,
)

from assertpy import assert_that
from retry import retry
from semver import VersionInfo

from lisa import notifier
from lisa.base_tools import (
    AptAddRepository,
    Cat,
    Sed,
    Service,
    Uname,
    Wget,
    YumConfigManager,
)
from lisa.executable import Tool
from lisa.util import (
    BaseClassMixin,
    LisaException,
    LisaTimeoutException,
    MissingPackagesException,
    ReleaseEndOfLifeException,
    RepoNotExistException,
    filter_ansi_escape,
    get_matched_str,
    parse_version,
    retry_without_exceptions,
)
from lisa.util.logger import get_logger
from lisa.util.perf_timer import create_timer
from lisa.util.process import ExecutableResult
from lisa.util.subclasses import Factory

if TYPE_CHECKING:
    from lisa.node import Node


_get_init_logger = partial(get_logger, name="os")


def get_matched_os_name(cmd_result: ExecutableResult, pattern: Pattern[str]) -> str:
    # Check if the command is timedout. If it is, the system might be in a bad state
    # Then raise an exception to avoid more timedout commands.
    if cmd_result.is_timeout:
        raise LisaTimeoutException(
            f"Command timed out: {cmd_result.cmd}. "
            "Please check if the system allows to run command from remote."
        )
    return get_matched_str(cmd_result.stdout, pattern)


class CpuArchitecture(str, Enum):
    X64 = "x86_64"
    ARM64 = "aarch64"
    I386 = "i386"


class AzureCoreRepo(str, Enum):
    AzureCoreMultiarch = "azurecore-multiarch"
    AzureCoreDebian = "azurecore-debian"
    AzureCore = "azurecore"


@dataclass
# stores information about repository in Posix operating systems
class RepositoryInfo(object):
    # name of the repository, for example focal-updates
    name: str


@dataclass
# OsInformation - To have full distro info.
# GetOSVersion() method at below link was useful to get distro info.
# https://github.com/microsoft/lisa/blob/master/Testscripts/Linux/utils.sh
class OsInformation:
    # structured version information, for example 8.0.3
    version: VersionInfo
    # Examples: Microsoft, Red Hat
    vendor: str
    # the string edition of version. Examples: 8.3, 18.04
    release: str = ""
    # Codename for the release
    codename: str = ""
    # Update available
    update: str = ""
    # Full name of release and version. Examples: Ubuntu 18.04.5 LTS (Bionic
    # Beaver), Red Hat Enterprise Linux release 8.3 (Ootpa)
    full_version: str = "Unknown"


@dataclass
# It's similar with UnameResult, and will replace it.
class KernelInformation:
    version: VersionInfo
    raw_version: str
    hardware_platform: str
    operating_system: str
    version_parts: List[str]


class OperatingSystem:
    __lsb_release_pattern = re.compile(r"^Description:[ \t]+([\w]+)[ ]+$", re.M)
    # NAME="Oracle Linux Server"
    __os_release_pattern_name = re.compile(r"^NAME=\"?([^\" \r\n]+).*?\"?\r?$", re.M)
    __os_release_pattern_id = re.compile(r"^ID=\"?([^\" \r\n]+).*?\"?\r?$", re.M)
    # The ID_LIKE is to match some unknown distro, but derived from known distros.
    # For example, the ID and ID_LIKE in /etc/os-release of AlmaLinux is:
    # ID="almalinux"
    # ID_LIKE="rhel centos fedora"
    # The __os_release_pattern_id can match "almalinux"
    # The __os_release_pattern_idlike can match "rhel"
    __os_release_pattern_idlike = re.compile(
        r"^ID_LIKE=\"?([^\" \r\n]+).*?\"?\r?$", re.M
    )
    __redhat_release_pattern_header = re.compile(r"^([^ ]*) .*$")
    # Red Hat Enterprise Linux Server 7.8 (Maipo) => Maipo
    __redhat_release_pattern_bracket = re.compile(r"^.*\(([^ ]*).*\)$")
    __debian_issue_pattern = re.compile(r"^([^ ]+) ?.*$")
    __release_pattern = re.compile(r"^DISTRIB_ID='?([^ \n']+).*$", re.M)
    __suse_release_pattern = re.compile(r"^(SUSE).*$", re.M)
    __bmc_release_pattern = re.compile(r".*(wcscli).*$", re.M)
    # VMware ESXi 8.0.2 build-23305546
    # VMware ESXi 8.0 Update 2
    __vmware_esxi_release_pattern = re.compile(r"^(VMware ESXi).*$", re.M)

    __posix_factory: Optional[Factory[Any]] = None

    def __init__(self, node: "Node", is_posix: bool) -> None:
        super().__init__()
        self._node: Node = node
        self._is_posix = is_posix
        self._log = get_logger(name="os", parent=self._node.log)
        self._information: Optional[OsInformation] = None
        self._packages: Dict[str, VersionInfo] = dict()

    @classmethod
    def create(cls, node: "Node") -> Any:
        log = _get_init_logger(parent=node.log)
        result: Optional[OperatingSystem] = None

        detected_info = ""
        # assume all guest nodes are posix
        if node.shell.is_posix or node.parent:
            # delay create factory to make sure it's late than loading extensions
            if cls.__posix_factory is None:
                cls.__posix_factory = Factory[Posix](Posix)
                cls.__posix_factory.initialize()
            # cast type for easy to use
            posix_factory: Factory[Posix] = cls.__posix_factory

            matched = False
            os_infos: List[str] = []
            for os_info_item in cls._get_detect_string(node):
                if os_info_item:
                    os_infos.append(os_info_item)
                    for sub_type in posix_factory.values():
                        posix_type: Type[Posix] = sub_type
                        pattern = posix_type.name_pattern()
                        if pattern.findall(os_info_item):
                            detected_info = os_info_item
                            result = posix_type(node)
                            matched = True
                            break
                    if matched:
                        break

            if not os_infos:
                raise LisaException(
                    "unknown posix distro, no os info found. "
                    "it may cause by not support basic commands like `cat`"
                )
            elif not result:
                raise LisaException(
                    f"unknown posix distro names '{os_infos}', "
                    f"support it in operating_system."
                )
        else:
            result = Windows(node)
        log.debug(f"detected OS: '{result.name}' by pattern '{detected_info}'")
        return result

    @property
    def is_windows(self) -> bool:
        return not self._is_posix

    @property
    def is_posix(self) -> bool:
        return self._is_posix

    @property
    def information(self) -> OsInformation:
        if not self._information:
            self._information = self._get_information()
            self._log.debug(f"parsed os information: {self._information}")

        return self._information

    @property
    def name(self) -> str:
        return self.__class__.__name__

    def capture_system_information(self, saved_path: Path) -> None:
        ...

    @classmethod
    def _get_detect_string(cls, node: Any) -> Iterable[str]:
        typed_node: Node = node
        cmd_result = typed_node.execute(
            cmd="lsb_release -d", no_error_log=True, timeout=60
        )
        yield get_matched_os_name(cmd_result, cls.__lsb_release_pattern)

        cmd_result = typed_node.execute(
            cmd="cat /etc/os-release", no_error_log=True, timeout=60
        )
        yield get_matched_os_name(cmd_result, cls.__os_release_pattern_name)
        yield get_matched_os_name(cmd_result, cls.__os_release_pattern_id)
        cmd_result_os_release = cmd_result

        # for RedHat, CentOS 6.x
        cmd_result = typed_node.execute(
            cmd="cat /etc/redhat-release", no_error_log=True, timeout=60
        )
        yield get_matched_os_name(cmd_result, cls.__redhat_release_pattern_header)
        yield get_matched_os_name(cmd_result, cls.__redhat_release_pattern_bracket)

        # for FreeBSD
        cmd_result = typed_node.execute(cmd="uname", no_error_log=True, timeout=60)
        yield cmd_result.stdout

        # for Debian
        cmd_result = typed_node.execute(
            cmd="cat /etc/issue", no_error_log=True, timeout=60
        )
        yield get_matched_os_name(cmd_result, cls.__debian_issue_pattern)

        # note, cat /etc/*release doesn't work in some images, so try them one by one
        # try best for other distros, like Sapphire
        cmd_result = typed_node.execute(
            cmd="cat /etc/release", no_error_log=True, timeout=60
        )
        yield get_matched_os_name(cmd_result, cls.__release_pattern)

        # try best for other distros, like VeloCloud
        cmd_result = typed_node.execute(
            cmd="cat /etc/lsb-release", no_error_log=True, timeout=60
        )
        yield get_matched_os_name(cmd_result, cls.__release_pattern)

        # try best for some suse derives, like netiq
        cmd_result = typed_node.execute(
            cmd="cat /etc/SuSE-release", no_error_log=True, timeout=60
        )
        yield get_matched_os_name(cmd_result, cls.__suse_release_pattern)

        cmd_result = typed_node.execute(cmd="wcscli", no_error_log=True, timeout=60)
        yield get_matched_os_name(cmd_result, cls.__bmc_release_pattern)

        cmd_result = typed_node.execute(cmd="vmware -lv", no_error_log=True, timeout=60)
        yield get_matched_os_name(cmd_result, cls.__vmware_esxi_release_pattern)

        # try best from distros'family through ID_LIKE
        yield get_matched_str(
            cmd_result_os_release.stdout, cls.__os_release_pattern_idlike
        )

    def _get_information(self) -> OsInformation:
        raise NotImplementedError()

    def _parse_version(self, version: str) -> VersionInfo:
        return parse_version(version)


class Windows(OperatingSystem):
    # Microsoft Windows [Version 10.0.22000.100]
    __windows_version_pattern = re.compile(
        r"^Microsoft Windows \[Version (?P<version>[0-9.]*?)\]$",
        re.M,
    )

    def __init__(self, node: Any) -> None:
        super().__init__(node, is_posix=False)

    def _get_information(self) -> OsInformation:
        cmd_result = self._node.execute(
            cmd="ver",
            shell=True,
            no_error_log=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="error on get os information:",
        )
        assert cmd_result.stdout, "not found os information from 'ver'"

        full_version = cmd_result.stdout
        version_string = get_matched_str(full_version, self.__windows_version_pattern)
        if not version_string:
            raise LisaException(f"OS version information not found in: {full_version}")

        information = OsInformation(
            version=self._parse_version(version_string),
            vendor="Microsoft",
            release=version_string,
            full_version=full_version,
        )
        return information


class Posix(OperatingSystem, BaseClassMixin):
    _os_info_pattern = re.compile(
        r"^(?P<name>.*)=[\"\']?(?P<value>.*?)[\"\']?$", re.MULTILINE
    )
    # output of /etc/fedora-release - Fedora release 22 (Twenty Two)
    # output of /etc/redhat-release - Scientific Linux release 7.1 (Nitrogen)
    # output of /etc/os-release -
    #   NAME="Debian GNU/Linux"
    #   VERSION_ID="7"
    #   VERSION="7 (wheezy)"
    # output of lsb_release -a
    #   LSB Version:	:base-4.0-amd64:base-4.0-noarch:core-4.0-amd64:core-4.0-noarch
    #   Distributor ID:	Scientific
    #   Description:	Scientific Linux release 6.7 (Carbon)
    # In most of the distros, the text in the brackets is the codename.
    # This regex gets the codename for the distro
    _distro_codename_pattern = re.compile(r"^.*\(([^)]+)")

    def __init__(self, node: Any) -> None:
        super().__init__(node, is_posix=True)
        self._first_time_installation: bool = True

    @classmethod
    def type_name(cls) -> str:
        return cls.__name__

    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        return re.compile(f"^{cls.type_name()}$")

    def replace_boot_kernel(self, kernel_version: str) -> None:
        raise NotImplementedError("update boot entry is not implemented")

    def get_kernel_information(self, force_run: bool = False) -> KernelInformation:
        uname = self._node.tools[Uname]
        uname_result = uname.get_linux_information(force_run=force_run)

        parts: List[str] = [str(x) for x in uname_result.kernel_version]
        kernel_information = KernelInformation(
            version=uname_result.kernel_version,
            raw_version=uname_result.kernel_version_raw,
            hardware_platform=uname_result.hardware_platform,
            operating_system=uname_result.operating_system,
            version_parts=parts,
        )

        return kernel_information

    def install_packages(
        self,
        packages: Union[
            str,
            Tool,
            Type[Tool],
            Sequence[Union[str, Tool, Type[Tool]]],
        ],
        signed: bool = False,
        timeout: int = 1200,
        extra_args: Optional[List[str]] = None,
    ) -> None:
        package_names = self._get_package_list(packages)
        self._install_packages(package_names, signed, timeout, extra_args)

    def uninstall_packages(
        self,
        packages: Union[
            str,
            Tool,
            Type[Tool],
            Sequence[Union[str, Tool, Type[Tool]]],
        ],
        signed: bool = False,
        timeout: int = 1200,
        extra_args: Optional[List[str]] = None,
    ) -> None:
        package_names = self._get_package_list(packages)
        self._uninstall_packages(package_names, signed, timeout, extra_args)

    def package_exists(self, package: Union[str, Tool, Type[Tool]]) -> bool:
        """
        Query if a package/tool is installed on the node.
        Return Value - bool
        """
        package_name = self.__resolve_package_name(package)
        return self._package_exists(package_name)

    def is_package_in_repo(self, package: Union[str, Tool, Type[Tool]]) -> bool:
        """
        Query if a package/tool exists in the repo
        Return Value - bool
        """
        package_name = self.__resolve_package_name(package)
        if self._first_time_installation:
            self._initialize_package_installation()
            self._first_time_installation = False
        return self._is_package_in_repo(package_name)

    def update_packages(
        self,
        packages: Union[str, Tool, Type[Tool], Sequence[Union[str, Tool, Type[Tool]]]],
    ) -> None:
        package_names = self._get_package_list(packages)
        self._update_packages(package_names)

    def clean_package_cache(self) -> None:
        raise NotImplementedError()

    def capture_system_information(self, saved_path: Path) -> None:
        # avoid to involve node, it's ok if some command doesn't exist.
        self._node.execute("uname -vrmo").save_stdout_to_file(saved_path / "uname.txt")
        self._node.execute(
            "uptime -s || last reboot -F | head -1 | awk '{print $9,$6,$7,$8}'",
            shell=True,
        ).save_stdout_to_file(saved_path / "uptime.txt")
        self._node.execute(
            "modinfo hv_netvsc",
            no_error_log=True,
        ).save_stdout_to_file(saved_path / "modinfo-hv_netvsc.txt")

        if self._node.is_test_target:
            if self._node.capture_boot_time and self._node._first_initialize:
                from lisa.tools import SystemdAnalyze

                try:
                    systemd_analyze_tool = self._node.tools[SystemdAnalyze]
                    boot_time = systemd_analyze_tool.get_boot_time()
                    boot_time.information.update(self._node.get_information())
                    notifier.notify(boot_time)
                except Exception as identifier:
                    self._node.log.debug(f"error on get boot time: {identifier}")

            file_list = []
            if self._node.capture_azure_information:
                from lisa.tools import Chmod, Find

                find_tool = self._node.tools[Find]
                file_list = find_tool.find_files(
                    self._node.get_pure_path("/var/log/azure/"),
                    file_type="f",
                    sudo=True,
                    ignore_not_exist=True,
                )
                if len(file_list) > 0:
                    self._node.tools[Chmod].update_folder(
                        "/var/log/azure/", "a+rwX", sudo=True
                    )
                file_list.append("/var/log/waagent.log")

            file_list.append("/etc/os-release")
            for file in file_list:
                try:
                    file_name = file.split("/")[-1]
                    self._node.shell.copy_back(
                        self._node.get_pure_path(file),
                        saved_path / f"{file_name}.txt",
                    )
                except FileNotFoundError:
                    self._log.debug(f"File {file} doesn't exist.")
                except Exception as identifier:
                    # Some images have no /etc/os-release. e.g. osirium-ltd osirium_pem
                    # image. It will have an exception (not FileNotFoundError).
                    self._log.debug(
                        f"Fail to copy back file {file}: {identifier}. "
                        "Please check if the file exists"
                    )

    def get_package_information(
        self, package_name: str, use_cached: bool = True
    ) -> VersionInfo:
        found = self._packages.get(package_name, None)
        if found and use_cached:
            return found
        return self._get_package_information(package_name)

    def get_repositories(self) -> List[RepositoryInfo]:
        raise NotImplementedError("get_repositories is not implemented")

    def add_azure_core_repo(
        self, repo_name: Optional[AzureCoreRepo] = None, code_name: Optional[str] = None
    ) -> None:
        raise NotImplementedError("add_azure_core_repo is not implemented")

    def set_kill_user_processes(self) -> None:
        raise NotImplementedError("set_kill_user_processes is not implemented")

    def _process_extra_package_args(self, extra_args: Optional[List[str]]) -> str:
        if extra_args:
            add_args = " ".join(extra_args)
        else:
            add_args = ""
        return add_args

    def _install_packages(
        self,
        packages: List[str],
        signed: bool = True,
        timeout: int = 600,
        extra_args: Optional[List[str]] = None,
    ) -> None:
        raise NotImplementedError()

    def _uninstall_packages(
        self,
        packages: List[str],
        signed: bool = True,
        timeout: int = 600,
        extra_args: Optional[List[str]] = None,
    ) -> None:
        raise NotImplementedError()

    def _update_packages(self, packages: Optional[List[str]] = None) -> None:
        raise NotImplementedError()

    def _package_exists(self, package: str) -> bool:
        raise NotImplementedError()

    def _is_package_in_repo(self, package: str) -> bool:
        raise NotImplementedError()

    def _initialize_package_installation(self) -> None:
        # sub os can override it, but it's optional
        pass

    def _get_package_information(self, package_name: str) -> VersionInfo:
        raise NotImplementedError()

    def _get_version_info_from_named_regex_match(
        self, package_name: str, named_matches: Match[str]
    ) -> VersionInfo:
        essential_matches = ["major", "minor", "build"]

        # verify all essential keys are in our match dict
        assert_that(
            all(map(lambda x: x in named_matches.groupdict().keys(), essential_matches))
        ).described_as(
            "VersionInfo fetch could not identify all required parameters."
        ).is_true()

        # fill in 'patch' version if it's missing
        patch_match = named_matches.group("patch")
        if not patch_match:
            patch_match = "0"
        major_match = named_matches.group("major")
        minor_match = named_matches.group("minor")
        build_match = named_matches.group("build")
        major, minor, patch = map(
            int,
            [major_match, minor_match, patch_match],
        )
        build_match = named_matches.group("build")
        self._node.log.debug(
            f"Found {package_name} version "
            f"{major_match}.{minor_match}.{patch_match}-{build_match}"
        )
        return VersionInfo(major, minor, patch, build=build_match)

    def _cache_and_return_version_info(
        self, package_name: str, info: VersionInfo
    ) -> VersionInfo:
        self._packages[package_name] = info
        return info

    def _get_information(self) -> OsInformation:
        # try to set version info from /etc/os-release.
        cat = self._node.tools[Cat]
        cmd_result = cat.run(
            "/etc/os-release",
            expected_exit_code=0,
            expected_exit_code_failure_message="error on get os information",
        )

        vendor: str = ""
        release: str = ""
        codename: str = ""
        full_version: str = ""
        for row in cmd_result.stdout.splitlines():
            os_release_info = self._os_info_pattern.match(row)
            if not os_release_info:
                continue
            if os_release_info.group("name") == "NAME":
                vendor = os_release_info.group("value")
            elif os_release_info.group("name") == "VERSION_ID":
                release = os_release_info.group("value")
            elif os_release_info.group("name") == "VERSION":
                codename = get_matched_str(
                    os_release_info.group("value"),
                    self._distro_codename_pattern,
                )
            elif os_release_info.group("name") == "PRETTY_NAME":
                full_version = os_release_info.group("value")

        if vendor == "":
            raise LisaException("OS vendor information not found")
        if release == "":
            raise LisaException("OS release information not found")

        information = OsInformation(
            version=self._parse_version(release),
            vendor=vendor,
            release=release,
            codename=codename,
            full_version=full_version,
        )

        return information

    def _get_package_list(
        self,
        packages: Union[
            str,
            Tool,
            Type[Tool],
            Sequence[Union[str, Tool, Type[Tool]]],
        ],
    ) -> List[str]:
        package_names: List[str] = []
        if isinstance(packages, (str, Tool, type)):
            packages = [packages]
        package_names = [self.__resolve_package_name(item) for item in packages]
        if self._first_time_installation:
            self._first_time_installation = False
            self._initialize_package_installation()
        return package_names

    def _install_package_from_url(
        self,
        package_url: str,
        package_name: str = "",
        signed: bool = True,
        timeout: int = 600,
    ) -> None:
        """
        Used if the package to be installed needs to be downloaded from a url first.
        """
        # when package is URL, download the package first at the working path.
        wget_tool = self._node.tools[Wget]
        pkg = wget_tool.get(package_url, str(self._node.working_path), package_name)
        self.install_packages(pkg, signed, timeout)

    def wait_running_process(self, process_name: str, timeout: int = 5) -> None:
        # by default, wait for 5 minutes
        timeout = 60 * timeout
        timer = create_timer()
        while timeout > timer.elapsed(False):
            # Some SUSE-based images need sudo privilege to run below command
            cmd_result = self._node.execute(f"pidof {process_name}", sudo=True)
            if cmd_result.exit_code == 1:
                # not found dpkg or zypper process, it's ok to exit.
                break
            time.sleep(1)

        if timeout < timer.elapsed():
            raise LisaTimeoutException(
                f"timeout to wait previous {process_name} process stop."
            )

    def __resolve_package_name(self, package: Union[str, Tool, Type[Tool]]) -> str:
        """
        A package can be a string or a tool or a type of tool.
        Resolve it to a standard package_name so it can be installed.
        """
        if isinstance(package, str):
            package_name = package
        elif isinstance(package, Tool):
            package_name = package.package_name
        else:
            assert isinstance(package, type), f"actual:{type(package)}"
            # Create a temp object, it doesn't query.
            # So they can be queried together.
            tool = package.create(self._node)
            package_name = tool.package_name

        return package_name


class BSD(Posix):
    ...


class BMC(Posix):
    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        return re.compile("^wcscli$")


class VMWareESXi(Posix):
    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        return re.compile("^VMware ESXi$")


class MacOS(Posix):
    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        return re.compile("^Darwin$")


class Linux(Posix):
    ...


class CoreOs(Linux):
    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        return re.compile("^coreos|Flatcar|flatcar$")


class Alpine(Linux):
    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        return re.compile("^Alpine|alpine|alpaquita")


@dataclass
# `apt-get update` repolist is of the form `<status>:<id> <uri> <name> <metadata>`
# Example:
# Get:5 http://azure.archive.ubuntu.com/ubuntu focal-updates/main amd64 Packages [1298 kB] # noqa: E501
class DebianRepositoryInfo(RepositoryInfo):
    # status for the repository. Examples: `Hit`, `Get`
    status: str

    # id for the repository. Examples : 1, 2
    id: str

    # uri for the repository. Example: `http://azure.archive.ubuntu.com/ubuntu`
    uri: str

    # metadata for the repository. Example: `amd64 Packages [1298 kB]`
    metadata: str


class Debian(Linux):
    # Get:5 http://azure.archive.ubuntu.com/ubuntu focal-updates/main amd64 Packages [1298 kB] # noqa: E501
    _debian_repository_info_pattern = re.compile(
        r"(?P<status>\S+):(?P<id>\d+)\s+(?P<uri>\S+)\s+(?P<name>\S+)"
        r"\s+(?P<metadata>.*)\s*"
    )

    """ Package: dpdk
        Version: 20.11.3-0ubuntu1~backport20.04-202111041420~ubuntu20.04.1
        Version: 1:2.25.1-1ubuntu3.2
    """
    _debian_package_information_regex = re.compile(
        r"Package: ([a-zA-Z0-9:_\-\.]+)\r?\n"  # package name group
        r"Version: ([a-zA-Z0-9:_\-\.~+]+)\r?\n"  # version number group
    )
    _debian_version_splitter_regex = re.compile(
        r"([0-9]+:)?"  # some examples have a mystery number followed by a ':' (git)
        r"(?P<major>[0-9]+)\."  # major
        r"(?P<minor>[0-9]+)[\-\.]"  # minor
        r"(?P<patch>[0-9]+)"  # patch
        r"(?:-)?(?P<build>[a-zA-Z0-9-_\.~+]+)"  # build
        # '-' is added after minor and made optional before build
        # due to the formats like 23.11-1build3
    )
    # apt-cache policy git
    # git:
    #   Installed: 1:2.17.1-1ubuntu0.9
    #   Candidate: 1:2.17.1-1ubuntu0.9
    #   Version table:
    #  *** 1:2.17.1-1ubuntu0.9 500
    #         500 http://azure.archive.ubuntu.com/ubuntu bionic-updates/main amd64 Packages # noqa: E501
    #         500 http://security.ubuntu.com/ubuntu bionic-security/main amd64 Packages # noqa: E501
    #         100 /var/lib/dpkg/status
    #      1:2.17.0-1ubuntu1 500
    #         500 http://azure.archive.ubuntu.com/ubuntu bionic/main amd64 Packages
    # apt-cache policy mock
    # mock:
    #   Installed: (none)
    #   Candidate: 1.3.2-2
    #   Version table:
    #      1.3.2-2 500
    #         500 http://azure.archive.ubuntu.com/ubuntu bionic/universe amd64 Packages # noqa: E501
    # apt-cache policy test
    # N: Unable to locate package test
    _package_candidate_pattern = re.compile(
        r"([\w\W]*?)(Candidate: \(none\)|Unable to locate package.*)", re.M
    )
    # E: The repository 'http://azure.archive.ubuntu.com/ubuntu impish-backports Release' does not have a Release file # noqa: E501
    # E: The repository 'http://azure.archive.ubuntu.com/ubuntu groovy Release' no longer has a Release file. # noqa: E501
    # E: The repository 'http://security.ubuntu.com/ubuntu zesty-security Release' does no longer have a Release file. # noqa: E501
    _repo_not_exist_patterns: List[Pattern[str]] = [
        re.compile("does not have a Release file", re.M),
        re.compile("no longer has a Release file", re.M),
        re.compile("does no longer have a Release file", re.M),
    ]
    end_of_life_releases: List[str] = []
    # The following signatures couldn't be verified because the public key is not available: NO_PUBKEY 0E98404D386FA1D9 NO_PUBKEY 6ED0E7B82643E131 # noqa: E501
    _key_not_available_pattern = re.compile(r"NO_PUBKEY (?P<key>[0-9A-F]{16})", re.M)

    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        return re.compile("^debian|Forcepoint|Kali$")

    def add_key(self, server_name: str, key: str) -> None:
        self._node.execute(
            f"apt-key adv --keyserver {server_name} --recv-keys {key}",
            sudo=True,
        )

    def get_apt_error(self, stdout: str) -> List[str]:
        error_lines: List[str] = []
        for line in stdout.splitlines(keepends=False):
            if line.startswith("E: "):
                error_lines.append(line)
        return error_lines

    def _get_package_information(self, package_name: str) -> VersionInfo:
        # run update of package info
        apt_info = self._node.execute(
            f"apt show {package_name}",
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Could not find package information for package {package_name}"
            ),
        )
        match = self._debian_package_information_regex.search(apt_info.stdout)
        if not match:
            raise LisaException(
                "Package information parsing could not find regex match "
                f" for {package_name} using regex "
                f"{self._debian_package_information_regex.pattern}"
            )
        version_str = match.group(2)
        match = self._debian_version_splitter_regex.search(version_str)
        if not match:
            raise LisaException(
                f"Could not parse version info: {version_str} "
                "for package {package_name}"
            )
        self._node.log.debug(f"Attempting to parse version string: {version_str}")
        version_info = self._get_version_info_from_named_regex_match(
            package_name, match
        )
        return self._cache_and_return_version_info(package_name, version_info)

    def add_azure_core_repo(
        self, repo_name: Optional[AzureCoreRepo] = None, code_name: Optional[str] = None
    ) -> None:
        arch = self.get_kernel_information().hardware_platform
        arch_name = "arm64" if arch == "aarch64" else "amd64"

        self.install_packages(["gnupg", "software-properties-common"])
        keys = [
            "https://packages.microsoft.com/keys/microsoft.asc",
            "https://packages.microsoft.com/keys/msopentech.asc",
        ]
        if (
            repo_name == AzureCoreRepo.AzureCore
            or self.information.codename != "buster"
        ):
            # 1. Some scenarios need packages which are not in azurecore-debian, such as
            # azure-compatscanner. Add azurecore from Ubuntu bionic instead
            # 2. azurezcore-debian only supports buster. For other versions,
            # use azurecore instead
            code_name = "bionic"
            repo_name = AzureCoreRepo.AzureCore
            # If it's architecture is aarch64, azurecore-multiarch repo is also needed
            if arch == "aarch64":
                repo_url = "http://packages.microsoft.com/repos/azurecore-multiarch/"
                self.add_repository(
                    repo=(f"deb [arch={arch_name}] {repo_url} {code_name} main"),
                    keys_location=keys,
                )
        else:
            code_name = self.information.codename
            repo_name = AzureCoreRepo.AzureCoreDebian

        repo_url = f"http://packages.microsoft.com/repos/{repo_name.value}/"
        self.add_repository(
            repo=(f"deb [arch={arch_name}] {repo_url} {code_name} main"),
            keys_location=keys,
        )

    def wait_running_package_process(self) -> None:
        is_first_time: bool = True
        # wait for 10 minutes
        timeout = 60 * 10
        timer = create_timer()
        while timeout > timer.elapsed(False):
            # fix the dpkg, in case it's broken.
            dpkg_result = self._node.execute(
                "dpkg --force-all --configure -a", sudo=True
            )
            pidof_result = self._node.execute("pidof dpkg dpkg-deb")
            if dpkg_result.exit_code == 0 and pidof_result.exit_code == 1:
                # not found dpkg process, it's ok to exit.
                break
            if is_first_time:
                is_first_time = False
                self._log.debug("found system dpkg process, waiting it...")
            time.sleep(1)

        if timeout < timer.elapsed():
            raise LisaTimeoutException("timeout to wait previous dpkg process stop.")

    def get_repositories(self) -> List[RepositoryInfo]:
        self._initialize_package_installation()
        repo_list_str = self._node.execute("apt-get update", sudo=True).stdout

        repositories: List[RepositoryInfo] = []
        for line in repo_list_str.splitlines():
            matched = self._debian_repository_info_pattern.search(line)
            if matched:
                repositories.append(
                    DebianRepositoryInfo(
                        name=matched.group("name"),
                        status=matched.group("status"),
                        id=matched.group("id"),
                        uri=matched.group("uri"),
                        metadata=matched.group("metadata"),
                    )
                )

        return repositories

    def clean_package_cache(self) -> None:
        self._node.execute("apt-get clean", sudo=True, shell=True)

    @retry(tries=10, delay=5)
    def remove_repository(
        self,
        repo: str,
        key: Optional[List[str]] = None,
    ) -> None:
        self._initialize_package_installation()
        if key:
            self._node.execute(
                cmd=f"apt-key del {key}",
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message="fail to del apt key",
            )

        apt_repo = self._node.tools[AptAddRepository]
        apt_repo.remove_repository(repo)

        # Unlike add repository, remove repository doesn't trigger apt update.
        # So, it's needed to run apt update after remove repository.
        self._node.execute("apt-get update", sudo=True)

    @retry(tries=10, delay=5)
    def add_repository(
        self,
        repo: str,
        no_gpgcheck: bool = True,
        repo_name: Optional[str] = None,
        keys_location: Optional[List[str]] = None,
    ) -> None:
        self._initialize_package_installation()
        if keys_location:
            for key_location in keys_location:
                wget = self._node.tools[Wget]
                key_file_path = wget.get(
                    url=key_location,
                    file_path=str(self._node.working_path),
                    force_run=True,
                )
                self._node.execute(
                    cmd=f"apt-key add {key_file_path}",
                    sudo=True,
                    expected_exit_code=0,
                    expected_exit_code_failure_message="fail to add apt key",
                )
        # This command will trigger apt update too, so it doesn't need to update
        # repos again.

        apt_repo = self._node.tools[AptAddRepository]
        apt_repo.add_repository(repo)

        # apt update will not be triggered on Debian during add repo
        if type(self._node.os) == Debian:
            self._node.execute("apt-get update", sudo=True)

    def is_end_of_life_release(self) -> bool:
        return self.information.full_version in self.end_of_life_releases

    @retry_without_exceptions(
        tries=10,
        delay=5,
        skipped_exceptions=[ReleaseEndOfLifeException, RepoNotExistException],
    )
    def _initialize_package_installation(self) -> None:
        # wait running system package process.
        self.wait_running_package_process()
        result = self._node.execute("apt-get update", sudo=True, timeout=1800)
        if result.exit_code != 0:
            not_available_keys = self._key_not_available_pattern.findall(result.stdout)
            if len(set(not_available_keys)) > 0:
                self.install_packages("gnupg")
                for key in set(not_available_keys):
                    self._node.execute(
                        "apt-key adv --keyserver keyserver.ubuntu.com "
                        f"--recv-keys {key}",
                        sudo=True,
                    )
                result = self._node.execute("apt-get update", sudo=True, timeout=1800)
        for pattern in self._repo_not_exist_patterns:
            if pattern.search(result.stdout):
                if self.is_end_of_life_release():
                    raise ReleaseEndOfLifeException(self._node.os)
                else:
                    raise RepoNotExistException(self._node.os)
        result.assert_exit_code(message="\n".join(self.get_apt_error(result.stdout)))

    @retry_without_exceptions(
        tries=10,
        delay=5,
        skipped_exceptions=[ReleaseEndOfLifeException, RepoNotExistException],
    )
    def _install_packages(
        self,
        packages: List[str],
        signed: bool = True,
        timeout: int = 600,
        extra_args: Optional[List[str]] = None,
    ) -> None:
        file_packages = []
        for index, package in enumerate(packages):
            if package.endswith(".deb"):
                # If the package is a .deb file then it would first need to be unpacked.
                # using dpkg command before installing it like other packages.
                file_packages.append(package)
                package = Path(package).stem
                packages[index] = package
        add_args = self._process_extra_package_args(extra_args)
        command = (
            f"DEBIAN_FRONTEND=noninteractive apt-get {add_args} "
            f"-y install {' '.join(packages)}"
        )
        if not signed:
            command += " --allow-unauthenticated"
        self.wait_running_package_process()
        if file_packages:
            self._node.execute(
                f"dpkg -i {' '.join(file_packages)}", sudo=True, timeout=timeout
            )
            # after install package, need update the repo
            self._initialize_package_installation()

        install_result = self._node.execute(
            command, shell=True, sudo=True, timeout=timeout
        )
        # get error lines.
        install_result.assert_exit_code(
            0,
            f"Failed to install {packages}, "
            f"please check the package name and repo are correct or not.\n"
            + "\n".join(self.get_apt_error(install_result.stdout))
            + "\n",
        )

    def _uninstall_packages(
        self,
        packages: List[str],
        signed: bool = True,
        timeout: int = 600,
        extra_args: Optional[List[str]] = None,
    ) -> None:
        add_args = self._process_extra_package_args(extra_args)
        command = (
            f"DEBIAN_FRONTEND=noninteractive apt-get {add_args} "
            f"-y remove {' '.join(packages)}"
        )
        if not signed:
            command += " --allow-unauthenticated"
        self.wait_running_package_process()
        uninstall_result = self._node.execute(
            command, shell=True, sudo=True, timeout=timeout
        )
        # get error lines.
        uninstall_result.assert_exit_code(
            0,
            f"Failed to uninstall {packages}, "
            f"please check the package name and repo are correct or not.\n"
            + "\n".join(self.get_apt_error(uninstall_result.stdout))
            + "\n",
        )

    def _package_exists(self, package: str) -> bool:
        command = "dpkg --get-selections"
        result = self._node.execute(command, sudo=True, shell=True)
        # Not installed package not shown in the output
        # Uninstall package will show as deinstall
        # The 'hold' status means that when the operating system is upgraded, the
        # installer will not upgrade these packages,unless explicitly stated. If
        # package is hold status, it means this package exists.
        # vim                                             deinstall
        # vim-common                                      install
        # auoms                                           hold
        package_pattern = re.compile(f"{package}([ \t]+)(install|hold)")
        if len(list(filter(package_pattern.match, result.stdout.splitlines()))) == 1:
            return True
        return False

    def _is_package_in_repo(self, package: str) -> bool:
        command = f"apt-cache policy {package}"
        result = self._node.execute(command, sudo=True, shell=True)
        matched = get_matched_str(result.stdout, self._package_candidate_pattern)
        if matched:
            return False
        return True

    def _get_information(self) -> OsInformation:
        # try to set version info from /etc/os-release.
        cat = self._node.tools[Cat]
        cmd_result = cat.run(
            "/etc/os-release",
            expected_exit_code=0,
            expected_exit_code_failure_message="error on get os information",
        )

        vendor: str = ""
        release: str = ""
        codename: str = ""
        full_version: str = ""
        for row in cmd_result.stdout.splitlines():
            os_release_info = super()._os_info_pattern.match(row)
            if not os_release_info:
                continue
            if os_release_info.group("name") == "NAME":
                vendor = os_release_info.group("value")
            elif os_release_info.group("name") == "VERSION":
                codename = get_matched_str(
                    os_release_info.group("value"),
                    super()._distro_codename_pattern,
                )
            elif os_release_info.group("name") == "PRETTY_NAME":
                full_version = os_release_info.group("value")

        # version return from /etc/os-release is integer in debian
        # so get the precise version from /etc/debian_version
        # e.g.
        # marketplace image - credativ debian 9-backports 9.20190313.0
        # version from /etc/os-release is 9
        # version from /etc/debian_version is 9.8
        # marketplace image - debian debian-10 10-backports-gen2 0.20210201.535
        # version from /etc/os-release is 10
        # version from /etc/debian_version is 10.7
        cmd_result = cat.run(
            "/etc/debian_version",
            expected_exit_code=0,
            expected_exit_code_failure_message="error on get debian version",
        )
        release = cmd_result.stdout

        if vendor == "":
            raise LisaException("OS vendor information not found")
        if release == "":
            raise LisaException("OS release information not found")

        information = OsInformation(
            version=self._parse_version(release),
            vendor=vendor,
            release=release,
            codename=codename,
            full_version=full_version,
        )

        return information

    def _update_packages(self, packages: Optional[List[str]] = None) -> None:
        command = (
            "DEBIAN_FRONTEND=noninteractive apt-get upgrade -y "
            '-o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" '
        )
        if packages:
            command += " ".join(packages)
        self._node.execute(command, sudo=True, timeout=3600)


class Ubuntu(Debian):
    __lsb_os_info_pattern = re.compile(
        r"^(?P<name>.*):(\s+)(?P<value>.*?)?$", re.MULTILINE
    )
    # gnulinux-5.11.0-1011-azure-advanced-3fdd2548-1430-450b-b16d-9191404598fb
    # prefix: gnulinux
    # postfix: advanced-3fdd2548-1430-450b-b16d-9191404598fb
    __menu_id_parts_pattern = re.compile(
        r"^(?P<prefix>.*?)-.*-(?P<postfix>.*?-.*?-.*?-.*?-.*?-.*?)?$"
    )

    # The end of life releases come from
    # https://wiki.ubuntu.com/Releases?_ga=2.7226034.1862489468.1672129506-282537095.1659934740 # noqa: E501
    end_of_life_releases: List[str] = [
        "Ubuntu 22.10",
        "Ubuntu 21.10",
        "Ubuntu 21.04",
        "Ubuntu 20.10",
        "Ubuntu 19.10",
        "Ubuntu 19.04",
        "Ubuntu 18.10",
        "Ubuntu 17.10",
        "Ubuntu 17.04",
        "Ubuntu 16.10",
    ]

    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        return re.compile("^Ubuntu|ubuntu$")

    def replace_boot_kernel(self, kernel_version: str) -> None:
        # set installed kernel to default
        #
        # get boot entry id
        # positive example:
        #         menuentry 'Ubuntu, with Linux 5.11.0-1011-azure' --class ubuntu
        # --class gnu-linux --class gnu --class os $menuentry_id_option
        # 'gnulinux-5.11.0-1011-azure-advanced-3fdd2548-1430-450b-b16d-9191404598fb' {
        #
        # negative example:
        #         menuentry 'Ubuntu, with Linux 5.11.0-1011-azure (recovery mode)'
        # --class ubuntu --class gnu-linux --class gnu --class os $menuentry_id_option
        # 'gnulinux-5.11.0-1011-azure-recovery-3fdd2548-1430-450b-b16d-9191404598fb' {
        cat = self._node.tools[Cat]
        menu_id_pattern = re.compile(
            r"^.*?menuentry '.*?(?:"
            + kernel_version
            + r"[^ ]*?)(?<! \(recovery mode\))' "
            r".*?\$menuentry_id_option .*?'(?P<menu_id>.*)'.*$",
            re.M,
        )
        result = cat.run("/boot/grub/grub.cfg", sudo=True)
        submenu_id = get_matched_str(result.stdout, menu_id_pattern)
        assert submenu_id, (
            f"cannot find sub menu id from grub config by pattern: "
            f"{menu_id_pattern.pattern}"
        )
        self._log.debug(f"matched submenu_id: {submenu_id}")

        # get first level menu id in boot menu
        # input is the sub menu id like:
        # gnulinux-5.11.0-1011-azure-advanced-3fdd2548-1430-450b-b16d-9191404598fb
        # output is,
        # gnulinux-advanced-3fdd2548-1430-450b-b16d-9191404598fb
        menu_id = self.__menu_id_parts_pattern.sub(
            r"\g<prefix>-\g<postfix>", submenu_id
        )
        assert menu_id, f"cannot composite menu id from {submenu_id}"

        # composite boot menu in grub
        menu_entry = f"{menu_id}>{submenu_id}"
        self._log.debug(f"composited menu_entry: {menu_entry}")

        self._replace_default_entry(menu_entry)
        self._node.execute("update-grub", sudo=True)

        try:
            # install tool packages
            self.install_packages(
                [
                    f"linux-tools-{kernel_version}-azure",
                    f"linux-cloud-tools-{kernel_version}-azure",
                    f"linux-headers-{kernel_version}-azure",
                ]
            )
        except Exception as identifier:
            self._log.debug(
                f"ignorable error on install packages after replaced kernel: "
                f"{identifier}"
            )

    def wait_cloud_init_finish(self) -> None:
        # wait till cloud-init finish to run the init work include updating
        # /etc/apt/source.list file
        # not add expected_exit_code, since for other platforms
        # it may not have cloud-init
        self._node.execute("cloud-init status --wait", sudo=True)

    def _get_information(self) -> OsInformation:
        cmd_result = self._node.execute(
            cmd="lsb_release -a",
            shell=True,
            no_error_log=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="error on get os information",
        )
        assert cmd_result.stdout, "not found os information from 'lsb_release -a'"

        for row in cmd_result.stdout.splitlines():
            os_release_info = self.__lsb_os_info_pattern.match(row)
            if os_release_info:
                if os_release_info.group("name") == "Distributor ID":
                    vendor = os_release_info.group("value")
                elif os_release_info.group("name") == "Release":
                    release = os_release_info.group("value")
                elif os_release_info.group("name") == "Codename":
                    codename = os_release_info.group("value")
                elif os_release_info.group("name") == "Description":
                    full_version = os_release_info.group("value")

        if vendor == "":
            raise LisaException("OS vendor information not found")
        if release == "":
            raise LisaException("OS release information not found")

        information = OsInformation(
            version=self._parse_version(release),
            vendor=vendor,
            release=release,
            codename=codename,
            full_version=full_version,
        )

        return information

    def add_azure_core_repo(
        self, repo_name: Optional[AzureCoreRepo] = None, code_name: Optional[str] = None
    ) -> None:
        arch = self.get_kernel_information().hardware_platform
        arch_name = "arm64" if arch == "aarch64" else "amd64"
        if not code_name:
            code_name = self.information.codename
        repo_url = "http://packages.microsoft.com/repos/azurecore/"
        self.add_repository(
            repo=(f"deb [arch={arch_name}] {repo_url} {code_name} main"),
            keys_location=[
                "https://packages.microsoft.com/keys/microsoft.asc",
                "https://packages.microsoft.com/keys/msopentech.asc",
            ],
        )
        # If its architecture is aarch64 for bionic and xenial,
        # azurecore-multiarch repo is also needed
        if arch == "aarch64" and (code_name == "bionic" or code_name == "xenial"):
            repo_url = "http://packages.microsoft.com/repos/azurecore-multiarch/"
            self.add_repository(
                repo=(f"deb [arch={arch_name}] {repo_url} {code_name} main"),
                keys_location=[
                    "https://packages.microsoft.com/keys/microsoft.asc",
                    "https://packages.microsoft.com/keys/msopentech.asc",
                ],
            )

    def _replace_default_entry(self, entry: str) -> None:
        self._log.debug(f"set boot entry to: {entry}")
        sed = self._node.tools[Sed]
        sed.substitute(
            regexp="GRUB_DEFAULT=.*",
            replacement=f"GRUB_DEFAULT='{entry}'",
            file="/etc/default/grub",
            sudo=True,
        )

        # output to log for troubleshooting
        cat = self._node.tools[Cat]
        cat.run("/etc/default/grub")

    def _initialize_package_installation(self) -> None:
        self.wait_cloud_init_finish()
        super()._initialize_package_installation()


@dataclass
# Repositories:
#   FreeBSD: {
#     url             : "pkg+http://pkg.FreeBSD.org/FreeBSD:13:amd64/quarterly",
#     enabled         : yes,
#     priority        : 0,
#     mirror_type     : "SRV",
#     signature_type  : "FINGERPRINTS",
#     fingerprints    : "/usr/share/keys/pkg"
#   }
class FreeBSDRepositoryInfo(RepositoryInfo):
    # url for the repository.
    # Example: `pkg+http://pkg.FreeBSD.org/FreeBSD:13:amd64/quarterly`
    url: str

    # enabled for the repository. Examples : yes, no
    enabled: str


class FreeBSD(BSD):
    _freebsd_repository_info_pattern = re.compile(
        r"\s+(\w+):\s*{(?:[^}]*url\s*:\s*\"([^\"]+)\"[^}]*enabled\s*:\s*(\w+))+[^}]*}",
        re.DOTALL,
    )

    def get_repositories(self) -> List[RepositoryInfo]:
        self._initialize_package_installation()
        repo_list_str = self._node.execute("pkg -vv", sudo=True).stdout

        repositories: List[RepositoryInfo] = []
        for matched in self._freebsd_repository_info_pattern.finditer(
            repo_list_str, re.DOTALL
        ):
            if matched.group(3).lower() == "yes":
                repositories.append(
                    FreeBSDRepositoryInfo(
                        name=matched.group(1),
                        url=matched.group(2),
                        enabled=matched.group(3).lower(),
                    )
                )

        return repositories

    @retry(tries=10, delay=5)
    def _install_packages(
        self,
        packages: List[str],
        signed: bool = True,
        timeout: int = 600,
        extra_args: Optional[List[str]] = None,
    ) -> None:
        if self._first_time_installation:
            self._initialize_package_installation()
        self._first_time_installation = False
        command = f"env ASSUME_ALWAYS_YES=yes pkg install -y {' '.join(packages)}"
        install_result = self._node.execute(
            command, shell=True, sudo=True, timeout=timeout
        )
        # get error lines.
        install_result.assert_exit_code(
            0,
            f"Failed to install {packages}, "
            f"please check the package name and repo are correct or not.\n",
        )

    @retry(tries=10, delay=5)
    def _initialize_package_installation(self) -> None:
        result = self._node.execute("env ASSUME_ALWAYS_YES=yes pkg update", sudo=True)
        result.assert_exit_code(message="fail to run pkg update")

    def _update_packages(self, packages: Optional[List[str]] = None) -> None:
        command = "env ASSUME_ALWAYS_YES=yes pkg upgrade -y "
        if packages:
            command += " ".join(packages)
        self._node.execute(
            command,
            sudo=True,
            timeout=3600,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"fail to run {command}",
        )


class OpenBSD(BSD):
    ...


@dataclass
# dnf repolist is of the form `<id> <name>`
# Example:
# microsoft-azure-rhel8-eus  Microsoft Azure RPMs for RHEL8 Extended Update Support
class RPMRepositoryInfo(RepositoryInfo):
    # id for the repository, for example: microsoft-azure-rhel8-eus
    id: str


# Linux distros that use RPM.
class RPMDistro(Linux):
    # microsoft-azure-rhel8-eus  Microsoft Azure RPMs for RHEL8 Extended Update Support
    _rpm_repository_info_pattern = re.compile(r"(?P<id>\S+)\s+(?P<name>\S.*\S)\s*")

    # ex: dpdk-20.11-3.el8.x86_64 or dpdk-18.11.8-1.el7_8.x86_64
    _rpm_version_splitter_regex = re.compile(
        r"(?P<package_name>[a-zA-Z0-9\-_]+)-"
        r"(?P<major>[0-9]+)\."
        r"(?P<minor>[0-9]+)\.?"
        r"(?P<patch>[0-9]+)?"
        r"(?P<build>-[a-zA-Z0-9-_\.]+)?"
    )

    def get_repositories(self) -> List[RepositoryInfo]:
        if self._first_time_installation:
            self._initialize_package_installation()
            self._first_time_installation = False
        repo_list_str = self._node.execute(
            f"{self._dnf_tool()} repolist", sudo=True
        ).stdout.splitlines()

        # skip to the first entry in the output
        for index, repo_str in enumerate(repo_list_str):
            if repo_str.startswith("repo id"):
                header_index = index
                break
        repo_list_str = repo_list_str[header_index + 1 :]

        repositories: List[RepositoryInfo] = []
        for line in repo_list_str:
            repo_info = self._rpm_repository_info_pattern.search(line)
            if repo_info:
                repositories.append(
                    RPMRepositoryInfo(
                        name=repo_info.group("name"), id=repo_info.group("id").lower()
                    )
                )
        return repositories

    def add_repository(
        self,
        repo: str,
        no_gpgcheck: bool = True,
        repo_name: Optional[str] = None,
        keys_location: Optional[List[str]] = None,
    ) -> None:
        self._node.tools[YumConfigManager].add_repository(repo, no_gpgcheck)

    def add_azure_core_repo(
        self, repo_name: Optional[AzureCoreRepo] = None, code_name: Optional[str] = None
    ) -> None:
        self.add_repository("https://packages.microsoft.com/yumrepos/azurecore/")

    def clean_package_cache(self) -> None:
        self._node.execute(f"{self._dnf_tool()} clean all", sudo=True, shell=True)

    def _get_package_information(self, package_name: str) -> VersionInfo:
        rpm_info = self._node.execute(
            f"rpm -q {package_name}",
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Could not find package information for package {package_name}"
            ),
        )
        # rpm package should be of format (package_name)-(version)
        matches = self._rpm_version_splitter_regex.search(rpm_info.stdout)
        if not matches:
            raise LisaException(
                f"Could not parse package version {rpm_info} for {package_name}"
            )
        self._node.log.debug(f"Attempting to parse version string: {rpm_info.stdout}")
        version_info = self._get_version_info_from_named_regex_match(
            package_name, matches
        )
        return self._cache_and_return_version_info(package_name, version_info)

    def _install_packages(
        self,
        packages: List[str],
        signed: bool = True,
        timeout: int = 600,
        extra_args: Optional[List[str]] = None,
    ) -> None:
        add_args = self._process_extra_package_args(extra_args)
        command = f"{self._dnf_tool()} install {add_args} -y {' '.join(packages)}"
        if not signed:
            command += " --nogpgcheck"

        self._node.execute(
            command,
            shell=True,
            sudo=True,
            timeout=timeout,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"Failed to install {packages}.",
        )

        self._log.debug(f"{packages} is/are installed successfully.")

    def _uninstall_packages(
        self,
        packages: List[str],
        signed: bool = True,
        timeout: int = 600,
        extra_args: Optional[List[str]] = None,
    ) -> None:
        add_args = self._process_extra_package_args(extra_args)
        command = f"{self._dnf_tool()} remove {add_args} -y {' '.join(packages)}"
        if not signed:
            command += " --nogpgcheck"

        self._node.execute(
            command,
            shell=True,
            sudo=True,
            timeout=timeout,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"Failed to uninstall {packages}.",
        )

        self._log.debug(f"{packages} is/are uninstalled successfully.")

    def _package_exists(self, package: str) -> bool:
        command = f"{self._dnf_tool()} list installed {package}"
        result = self._node.execute(command, sudo=True)
        if result.exit_code == 0:
            for row in result.stdout.splitlines():
                if package in row:
                    return True

        return False

    def _is_package_in_repo(self, package: str) -> bool:
        command = f"{self._dnf_tool()} list {package} -y"
        result = self._node.execute(command, sudo=True, shell=True)
        return 0 == result.exit_code

    def _dnf_tool(self) -> str:
        return "dnf"

    def _update_packages(self, packages: Optional[List[str]] = None) -> None:
        command = f"{self._dnf_tool()} -y --nogpgcheck update "
        if packages:
            command += " ".join(packages)
        self._node.execute(command, sudo=True, timeout=3600)


class Fedora(RPMDistro):
    # Red Hat Enterprise Linux Server 7.8 (Maipo) => 7.8
    _fedora_release_pattern_version = re.compile(r"^.*release\s+([0-9\.]+).*$")

    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        return re.compile("^Fedora|fedora$")

    def get_kernel_information(self, force_run: bool = False) -> KernelInformation:
        kernel_information = super().get_kernel_information(force_run)
        # original parts: version_parts=['4', '18', '0', '305.40.1.el8_4.x86_64', '']
        # target parts: version_parts=['4', '18', '0', '305', '40', '1', 'el8_4',
        #   'x86_64']
        new_parts = kernel_information.version_parts[:3]
        # the default '1' is trying to build a meaningful Redhat version number.
        new_parts.extend(kernel_information.version_parts[3].split("."))
        kernel_information.version_parts = new_parts

        return kernel_information

    def install_epel(self) -> None:
        # Extra Packages for Enterprise Linux (EPEL) is a special interest group
        # (SIG) from the Fedora Project that provides a set of additional packages
        # for RHEL (and CentOS, and others) from the Fedora sources.

        major = self._node.os.information.version.major
        assert_that(major).described_as(
            "Fedora/RedHat version must be greater than 7"
        ).is_greater_than_or_equal_to(7)
        epel_release_rpm_name = f"epel-release-latest-{major}.noarch.rpm"
        self.install_packages(
            f"https://dl.fedoraproject.org/pub/epel/{epel_release_rpm_name}"
        )

        # replace $releasever to 8 for 8.x
        if major == 8 or major == 9:
            sed = self._node.tools[Sed]
            sed.substitute("$releasever", "8", "/etc/yum.repos.d/epel*.repo", sudo=True)

    def _verify_package_result(self, result: ExecutableResult, packages: Any) -> None:
        # yum returns exit_code=1 if DNF handled an error with installation.
        # We do not want to fail if exit_code=1, but warn since something may
        # potentially have gone wrong.
        if result.exit_code == 1:
            self._log.debug(f"DNF handled error with installation of {packages}")
        elif result.exit_code == 0:
            self._log.debug(f"{packages} is/are installed successfully.")
        else:
            raise LisaException(
                f"Failed to install {packages}. exit_code: {result.exit_code}"
            )

    def group_install_packages(self, group_name: str) -> None:
        # trigger to run _initialize_package_installation
        self._get_package_list(group_name)
        result = self._node.execute(f'yum -y groupinstall "{group_name}"', sudo=True)
        self._verify_package_result(result, group_name)

    def _get_information(self) -> OsInformation:
        cmd_result = self._node.execute(
            # Typical output of 'cat /etc/fedora-release' is -
            # Fedora release 22 (Twenty Two)
            cmd="cat /etc/fedora-release",
            no_error_log=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="error on get os information",
        )

        full_version = cmd_result.stdout
        if "Fedora" not in full_version:
            raise LisaException("OS version information not found")

        vendor = "Fedora"
        release = get_matched_str(full_version, self._fedora_release_pattern_version)
        codename = get_matched_str(full_version, self._distro_codename_pattern)

        information = OsInformation(
            version=self._parse_version(release),
            vendor=vendor,
            release=release,
            codename=codename,
            full_version=full_version,
        )

        return information


class Redhat(Fedora):
    # Red Hat Enterprise Linux Server release 6.9 (Santiago)
    # CentOS release 6.9 (Final)
    # CentOS Linux release 8.3.2011
    __legacy_redhat_information_pattern = re.compile(
        r"^(?P<vendor>.*?)?(?: Enterprise Linux Server)?(?: Linux)?"
        r"(?: release)? (?P<version>[0-9\.]+)(?: \((?P<codename>.*).*\))?$"
    )
    # Oracle Linux Server
    # Red Hat Enterprise Linux Server
    # Red Hat Enterprise Linux
    __vendor_pattern = re.compile(
        r"^(?P<vendor>.*?)?(?: Enterprise)?(?: Linux)?(?: Server)?$"
    )

    # Error: There are no enabled repositories in "/etc/yum.repos.d", "/etc/yum/repos.d", "/etc/distro.repos.d". # noqa: E501
    _no_repo_enabled = re.compile("There are no enabled repositories", re.M)

    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        return re.compile("^rhel|Red|Rocky|Scientific|acronis|Actifio$")

    def replace_boot_kernel(self, kernel_version: str) -> None:
        # Redhat kernel is replaced when installing RPM. For source code
        # installation, it's implemented in source code installer.
        ...

    def capture_system_information(self, saved_path: Path) -> None:
        super().capture_system_information(saved_path)
        self._node.shell.copy_back(
            self._node.get_pure_path("/etc/redhat-release"),
            saved_path / "redhat-release.txt",
        )

    def handle_rhui_issue(self) -> None:
        # there are some images contain multiple rhui packages, like below:
        # rhui-azure-rhel8-2.2-198.noarch
        # rhui-azure-rhel8-eus-2.2-198.noarch
        # we need to remove the non-eus version, otherwise, yum update will fail
        # for below reason:
        #   Error: Transaction test error:
        #   file /etc/cron.daily/rhui-update-client conflicts between attempted
        #   installs of rhui-azure-rhel8-eus-2.2-485.noarch and
        #   rhui-azure-rhel8-2.2-485.noarch
        rhui_pacakges = self._node.execute(
            "rpm -qa | grep -i rhui-azure",
            shell=True,
            sudo=True,
        ).stdout
        if "eus" in rhui_pacakges and len(rhui_pacakges.splitlines()) > 1:
            for rhui_package in rhui_pacakges.splitlines():
                if "eus" not in rhui_package:
                    self._node.execute(f"yum remove -y {rhui_package}", sudo=True)
        # We may hit issue when run any yum command, caused by out of date
        #  rhui-microsoft-azure-rhel package.
        # Use below command to update rhui-microsoft-azure-rhel package from microsoft
        #  repo to resolve the issue.
        # Details please refer https://docs.microsoft.com/en-us/azure/virtual-machines/workloads/redhat/redhat-rhui#azure-rhui-infrastructure # noqa: E501
        self._node.execute(
            "yum update -y --disablerepo='*' --enablerepo='*microsoft*' ",
            sudo=True,
        )

    @retry(tries=10, delay=5)
    def _initialize_package_installation(self) -> None:
        information = self._get_information()
        if "Red Hat" == information.vendor:
            self.handle_rhui_issue()

    def _install_packages(
        self,
        packages: List[str],
        signed: bool = True,
        timeout: int = 600,
        extra_args: Optional[List[str]] = None,
    ) -> None:
        add_args = self._process_extra_package_args(extra_args)
        command = f"yum install {add_args} -y {' '.join(packages)}"
        if not signed:
            command += " --nogpgcheck"

        install_result = self._node.execute(
            command, shell=True, sudo=True, timeout=timeout
        )
        if self._no_repo_enabled.search(install_result.stdout):
            raise RepoNotExistException(self._node.os)
        # RedHat will fail package installation is a single missing package is
        # detected, therefore we check the output to see if we were missing
        # a package. If so, fail. Otherwise we will warn in verify package result.
        if install_result.exit_code == 1:
            missing_packages = []
            for line in install_result.stdout.splitlines():
                if line.startswith("No match for argument:"):
                    package = line.split(":")[1].strip()
                    missing_packages.append(package)
            if missing_packages:
                raise MissingPackagesException(missing_packages)
        super()._verify_package_result(install_result, packages)

    def _package_exists(self, package: str) -> bool:
        command = f"yum list installed {package}"
        result = self._node.execute(command, sudo=True)
        if result.exit_code == 0:
            return True

        return False

    def _is_package_in_repo(self, package: str) -> bool:
        command = f"yum --showduplicates list {package}"
        result = self._node.execute(command, sudo=True, shell=True)
        return 0 == result.exit_code

    def _get_information(self) -> OsInformation:
        try:
            cmd_result = self._node.execute(
                cmd="cat /etc/redhat-release", no_error_log=True, expected_exit_code=0
            )
            full_version = cmd_result.stdout
            matches = self.__legacy_redhat_information_pattern.match(full_version)
            assert matches, f"cannot match version information from: {full_version}"
            assert matches.group("vendor")
            information = OsInformation(
                version=self._parse_version(matches.group("version")),
                vendor=matches.group("vendor"),
                release=matches.group("version"),
                codename=matches.group("codename"),
                full_version=full_version,
            )
        except Exception:
            information = super(Fedora, self)._get_information()

        # remove Linux Server in vendor
        information.vendor = get_matched_str(information.vendor, self.__vendor_pattern)

        return information

    def _update_packages(self, packages: Optional[List[str]] = None) -> None:
        command = "yum -y --nogpgcheck update "
        if packages:
            command += " ".join(packages)
        # older images cost much longer time when update packages
        # smaller sizes cost much longer time when update packages, e.g.
        #  Basic_A1, Standard_A5, Standard_A1_v2, Standard_D1
        # redhat rhel 7-lvm 7.7.2019102813 Basic_A1 cost 2371.568 seconds
        # redhat rhel 8.1 8.1.2020020415 Basic_A0 cost 2409.116 seconds
        output = self._node.execute(command, sudo=True, timeout=3600).stdout
        if self._no_repo_enabled.search(output):
            raise RepoNotExistException(self._node.os)

    def _dnf_tool(self) -> str:
        return "yum"


class CentOs(Redhat):
    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        return re.compile("^CentOS|Centos|centos|clear-linux-os$")

    def capture_system_information(self, saved_path: Path) -> None:
        super(Linux, self).capture_system_information(saved_path)
        self._node.shell.copy_back(
            self._node.get_pure_path("/etc/centos-release"),
            saved_path / "centos-release.txt",
        )

    def _initialize_package_installation(self) -> None:
        information = self._get_information()
        if 8 == information.version.major:
            # refer https://www.centos.org/centos-linux-eol/ CentOS 8 is EOL,
            # old repo mirror was moved to vault.centos.org
            # CentOS-AppStream.repo, CentOS-Base.repo may contain non-existed
            # repo use skip_if_unavailable to avoid installation issues brought
            #  in by above issue
            cmd_results = self._node.execute("yum repolist -v", sudo=True)
            if 0 != cmd_results.exit_code:
                self._node.tools[YumConfigManager].set_opt("skip_if_unavailable=true")


class Oracle(Redhat):
    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        # The name is "Oracle Linux Server", which doesn't support the default
        # full match.
        return re.compile("^Oracle")


class AlmaLinux(Redhat):
    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        return re.compile("^AlmaLinux")


class CBLMariner(RPMDistro):
    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        return re.compile("^Common Base Linux Mariner|mariner|azurelinux$")

    def __init__(self, node: Any) -> None:
        super().__init__(node)
        self._dnf_tool_name: str

    def _initialize_package_installation(self) -> None:
        self.set_kill_user_processes()

        result = self._node.execute("command -v dnf", no_info_log=True, shell=True)
        if result.exit_code == 0:
            self._dnf_tool_name = "dnf"
            return

        self._dnf_tool_name = "tdnf -q"

    def _dnf_tool(self) -> str:
        return self._dnf_tool_name

    def _package_exists(self, package: str) -> bool:
        self._initialize_package_installation()
        return super()._package_exists(package)

    def add_azure_core_repo(
        self, repo_name: Optional[AzureCoreRepo] = None, code_name: Optional[str] = None
    ) -> None:
        super().add_azure_core_repo(repo_name, code_name)
        release = self.information.release
        from lisa.tools import Curl

        curl = self._node.tools[Curl]
        curl.fetch(
            arg="-o /etc/yum.repos.d/mariner-extras.repo",
            execute_arg="",
            url=f"https://raw.githubusercontent.com/microsoft/CBL-Mariner/{release}"
            "/SPECS/mariner-repos/mariner-extras.repo",
            sudo=True,
        )

    # Disable KillUserProcesses to avoid test processes being terminated when
    # the SSH session is reset
    def set_kill_user_processes(self) -> None:
        sed = self._node.tools[Sed]
        sed.append(
            text="KillUserProcesses=no",
            file="/etc/systemd/logind.conf",
            sudo=True,
        )
        self._node.tools[Service].restart_service("systemd-logind")


@dataclass
# `zypper lr` repolist is of the form
# `<id>|<alias>|<name>|<enabled>|<gpg_check>|<refresh>`
# Example:
# # 4 | repo-oss            | Main Repository             | Yes     | (r ) Yes  | Yes
class SuseRepositoryInfo(RepositoryInfo):
    # id for the repository. Example: 4
    id: str

    # alias for the repository. Example: repo-oss
    alias: str

    # is repository enabled. Example: True/False
    enabled: bool

    # is gpg_check enabled. Example: True/False
    gpg_check: bool

    # is repository refreshed. Example: True/False
    refresh: bool


class Suse(Linux):
    # 55 | Web_and_Scripting_Module_x86_64:SLE-Module-Web-Scripting15-SP2-Updates                           | SLE-Module-Web-Scripting15-SP2-Updates                  | Yes     | ( p) Yes  | Yes # noqa: E501
    # 4 | repo-oss            | Main Repository             | Yes     | (r ) Yes  | Yes # noqa: E501
    _zypper_table_entry = re.compile(
        r"\s*(?P<id>\d+)\s+[|]\s+(?P<alias>\S.+\S)\s+\|\s+(?P<name>\S.+\S)\s+\|"
        r"\s+(?P<enabled>\S.*\S)\s+\|\s+(?P<gpg_check>\S.*\S)\s+\|"
        r"\s+(?P<refresh>\S.*\S)\s*"
    )
    # Warning: There are no enabled repositories defined.
    _no_repo_defined = re.compile("There are no enabled repositories defined.", re.M)
    # Name           : dpdk
    # Version        : 19.11.10-150400.4.7.1
    _suse_package_information_regex = re.compile(
        r"Name\s+: (?P<package_name>[a-zA-Z0-9:_\-\.]+)\r?\n"
        r"Version\s+: (?P<package_version>[a-zA-Z0-9:_\-\.~+]+)\r?\n"
    )
    _suse_version_splitter_regex = re.compile(
        r"([0-9]+:)?"  # some examples have a mystery number followed by a ':' (git)
        r"(?P<major>[0-9]+)\."  # major
        r"(?P<minor>[0-9]+)\."  # minor
        r"(?P<patch>[0-9]+)"  # patch
        r"-(?P<build>[a-zA-Z0-9-_\.~+]+)"  # build
    )
    _ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        return re.compile("^SUSE|opensuse-leap$")

    def get_repositories(self) -> List[RepositoryInfo]:
        # Parse output of command "zypper lr"
        # Example output:
        # 1 | Basesystem_Module_x86_64:SLE-Module-Basesystem15-SP2-Debuginfo-Pool                              | SLE-Module-Basesystem15-SP2-Debuginfo-Pool              | No      | ----      | ---- # noqa: E501
        # 2 | Basesystem_Module_x86_64:SLE-Module-Basesystem15-SP2-Debuginfo-Updates                           | SLE-Module-Basesystem15-SP2-Debuginfo-Updates           | No      | ----      | ---- # noqa: E501
        self._initialize_package_installation()
        output = filter_ansi_escape(self._node.execute("zypper lr", sudo=True).stdout)
        repo_list: List[RepositoryInfo] = []

        for line in output.splitlines():
            matched = self._zypper_table_entry.search(line)
            if matched:
                is_repository_enabled = (
                    True if "Yes" in matched.group("enabled") else False
                )
                is_gpg_check_enabled = (
                    True if "Yes" in matched.group("gpg_check") else False
                )
                is_repository_refreshed = (
                    True if "Yes" in matched.group("refresh") else False
                )
                if matched:
                    repo_list.append(
                        SuseRepositoryInfo(
                            name=matched.group("name"),
                            id=matched.group("id"),
                            alias=matched.group("alias"),
                            enabled=is_repository_enabled,
                            gpg_check=is_gpg_check_enabled,
                            refresh=is_repository_refreshed,
                        )
                    )
        return repo_list

    def add_repository(
        self,
        repo: str,
        no_gpgcheck: bool = True,
        repo_name: Optional[str] = None,
        keys_location: Optional[List[str]] = None,
    ) -> None:
        self._initialize_package_installation()
        cmd = "zypper ar"
        if no_gpgcheck:
            cmd += " -G "
        cmd += f" {repo} {repo_name}"
        cmd_result = self._node.execute(cmd=cmd, sudo=True)
        if "already exists. Please use another alias." not in cmd_result.stdout:
            cmd_result.assert_exit_code(0, f"fail to add repo {repo}")
        else:
            self._log.debug(f"repo {repo_name} already exist")

    def clean_package_cache(self) -> None:
        self._node.execute("zypper clean --all", sudo=True, shell=True)

    def add_azure_core_repo(
        self, repo_name: Optional[AzureCoreRepo] = None, code_name: Optional[str] = None
    ) -> None:
        self.add_repository(
            repo="https://packages.microsoft.com/yumrepos/azurecore/",
            repo_name="packages-microsoft-com-azurecore",
        )

    def _initialize_package_installation(self) -> None:
        self.wait_running_process("zypper")
        service = self._node.tools[Service]
        if service.check_service_exists("guestregister"):
            timeout = 120
            timer = create_timer()
            while timeout > timer.elapsed(False):
                if service.is_service_inactive("guestregister"):
                    break
                time.sleep(1)
        output = self._node.execute(
            "zypper --non-interactive --gpg-auto-import-keys refresh", sudo=True
        ).stdout
        if self._no_repo_defined.search(output):
            raise RepoNotExistException(
                self._node.os,
                "There are no enabled repositories defined in this image.",
            )

    def _install_packages(
        self,
        packages: List[str],
        signed: bool = True,
        timeout: int = 600,
        extra_args: Optional[List[str]] = None,
    ) -> None:
        add_args = self._process_extra_package_args(extra_args)
        command = f"zypper --non-interactive {add_args}"
        if not signed:
            command += " --no-gpg-checks "
        command += f" in {' '.join(packages)}"
        self.wait_running_process("zypper")
        install_result = self._node.execute(
            command, shell=True, sudo=True, timeout=timeout
        )
        if install_result.exit_code in (1, 100):
            raise LisaException(
                f"Failed to install {packages}. exit_code: {install_result.exit_code}, "
                f"stderr: {install_result.stderr}"
            )
        elif install_result.exit_code == 0:
            self._log.debug(f"{packages} is/are installed successfully.")
        else:
            self._log.debug(
                f"{packages} is/are installed."
                " A system reboot or package manager restart might be required."
            )

    def _update_packages(self, packages: Optional[List[str]] = None) -> None:
        command = "zypper --non-interactive --gpg-auto-import-keys update "
        if packages:
            command += " ".join(packages)
        self._node.execute(command, sudo=True, timeout=3600)

    def _package_exists(self, package: str) -> bool:
        command = f"zypper search --installed-only --match-exact {package}"
        result = self._node.execute(command, sudo=True, shell=True)
        return 0 == result.exit_code

    def _is_package_in_repo(self, package: str) -> bool:
        command = f"zypper search -s --match-exact {package}"
        result = self._node.execute(command, sudo=True, shell=True)
        return 0 == result.exit_code

    def _get_package_information(self, package_name: str) -> VersionInfo:
        # run update of package info
        zypper_info = self._node.execute(
            f"zypper info {package_name}",
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Could not find package information for package {package_name}"
            ),
        )
        output = self._ansi_escape.sub("", zypper_info.stdout)
        match = self._suse_package_information_regex.search(output)
        if not match:
            raise LisaException(
                "Package information parsing could not find regex match "
                f" for {package_name} using regex "
                f"{self._suse_package_information_regex.pattern}"
            )
        version_str = match.group("package_version")
        match = self._suse_version_splitter_regex.search(version_str)
        if not match:
            raise LisaException(
                f"Could not parse version info: {version_str} "
                "for package {package_name}"
            )
        self._node.log.debug(f"Attempting to parse version string: {version_str}")
        version_info = self._get_version_info_from_named_regex_match(
            package_name, match
        )
        return self._cache_and_return_version_info(package_name, version_info)


class SLES(Suse):
    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        return re.compile("^SLES|sles|sle-hpc|sle_hpc$")


class NixOS(Linux):
    pass


class OtherLinux(Linux):
    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        """
        FMOS - firemon firemon_sip_azure firemon_sip_azure_byol 9.1.3
        idms - linuxbasedsystemsdesignltd1580878904727 idmslinux
               idmslinux_nosla 2020.0703.1
        RecoveryOS - unitrends unitrends-enterprise-backup-azure ueb9-azure-trial 1.0.9
        sinefa - sinefa sinefa-probe sf-va-msa 26.6.3
        """
        return re.compile(
            "^Sapphire|Buildroot|OpenWrt|BloombaseOS|FMOS|idms|RecoveryOS|sinefa$"
        )
