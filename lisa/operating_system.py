# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
import time
from dataclasses import dataclass
from functools import partial
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Iterable,
    List,
    Optional,
    Pattern,
    Type,
    Union,
)

from semver import VersionInfo

from lisa.base_tools import Cat, Wget
from lisa.executable import Tool
from lisa.util import BaseClassMixin, LisaException, get_matched_str
from lisa.util.logger import get_logger
from lisa.util.perf_timer import create_timer
from lisa.util.subclasses import Factory

if TYPE_CHECKING:
    from lisa.node import Node


_get_init_logger = partial(get_logger, name="os")
# Red Hat Enterprise Linux Server 7.8 (Maipo) => Maipo
_redhat_release_pattern_bracket = re.compile(r"^.*\(([^ ]*).*\)$")


@dataclass
# OsVersion - To have full distro info.
# GetOSVersion() method at below link was useful to get distro info.
# https://github.com/microsoft/lisa/blob/master/Testscripts/Linux/utils.sh
class OsVersion:
    # Vendor/Distributor
    vendor: str
    # Release/Version
    release: str = ""
    # Codename for the release
    codename: str = ""
    # Update available
    update: str = ""


class OperatingSystem:
    __lsb_release_pattern = re.compile(r"^Description:[ \t]+([\w]+)[ ]+$", re.M)
    __os_release_pattern_name = re.compile(
        r"^NAME=\"?([^\" \r\n]+)[^\" \n]*\"?\r?$", re.M
    )
    # For example, the ID and ID_LIKE in /etc/os-release of AlmaLinux is:
    # ID="almalinux"
    # ID_LIKE="rhel centos fedora"
    # The __os_release_pattern_id can match "almalinux"
    # The __os_release_pattern_idlike can match "rhel"
    __os_release_pattern_id = re.compile(r"^ID=\"?([^\" \r\n]+)[^\" \n]*\"?\r?$", re.M)
    __os_release_pattern_idlike = re.compile(
        r"^ID_LIKE=\"?([^\" \r\n]+)[^\"\n]*\"?\r?$", re.M
    )
    __redhat_release_pattern_header = re.compile(r"^([^ ]*) .*$")
    __debian_issue_pattern = re.compile(r"^([^ ]+) ?.*$")
    __release_pattern = re.compile(r"^DISTRIB_ID='?([^ \n']+).*$", re.M)
    __suse_release_pattern = re.compile(r"^(SUSE).*$", re.M)

    __posix_factory: Optional[Factory[Any]] = None

    def __init__(self, node: "Node", is_posix: bool) -> None:
        super().__init__()
        self._node: Node = node
        self._is_posix = is_posix
        self._log = get_logger(name="os", parent=self._node.log)
        self._os_version: Optional[OsVersion] = None

    @classmethod
    def create(cls, node: "Node") -> Any:
        log = _get_init_logger(parent=node.log)
        result: Optional[OperatingSystem] = None

        detected_info = ""
        if node.shell.is_posix:
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
        log.debug(
            f"detected OS: '{result.__class__.__name__}' by pattern '{detected_info}'"
        )
        return result

    @property
    def is_windows(self) -> bool:
        return not self._is_posix

    @property
    def is_posix(self) -> bool:
        return self._is_posix

    @property
    def os_version(self) -> OsVersion:
        if not self._os_version:
            self._os_version = self._get_os_version()

        return self._os_version

    @classmethod
    def _get_detect_string(cls, node: Any) -> Iterable[str]:
        typed_node: Node = node
        cmd_result = typed_node.execute(cmd="lsb_release -d", no_error_log=True)
        yield get_matched_str(cmd_result.stdout, cls.__lsb_release_pattern)

        cmd_result = typed_node.execute(cmd="cat /etc/os-release", no_error_log=True)
        yield get_matched_str(cmd_result.stdout, cls.__os_release_pattern_name)
        yield get_matched_str(cmd_result.stdout, cls.__os_release_pattern_id)
        cmd_result_os_release = cmd_result

        # for RedHat, CentOS 6.x
        cmd_result = typed_node.execute(
            cmd="cat /etc/redhat-release", no_error_log=True
        )
        yield get_matched_str(cmd_result.stdout, cls.__redhat_release_pattern_header)
        yield get_matched_str(cmd_result.stdout, _redhat_release_pattern_bracket)

        # for FreeBSD
        cmd_result = typed_node.execute(cmd="uname", no_error_log=True)
        yield cmd_result.stdout

        # for Debian
        cmd_result = typed_node.execute(cmd="cat /etc/issue", no_error_log=True)
        yield get_matched_str(cmd_result.stdout, cls.__debian_issue_pattern)

        # note, cat /etc/*release doesn't work in some images, so try them one by one
        # try best for other distros, like Sapphire
        cmd_result = typed_node.execute(cmd="cat /etc/release", no_error_log=True)
        yield get_matched_str(cmd_result.stdout, cls.__release_pattern)

        # try best for other distros, like VeloCloud
        cmd_result = typed_node.execute(cmd="cat /etc/lsb-release", no_error_log=True)
        yield get_matched_str(cmd_result.stdout, cls.__release_pattern)

        # try best for some suse derives, like netiq
        cmd_result = typed_node.execute(cmd="cat /etc/SuSE-release", no_error_log=True)
        yield get_matched_str(cmd_result.stdout, cls.__suse_release_pattern)

        # try best from distros'family through ID_LIKE
        yield get_matched_str(
            cmd_result_os_release.stdout, cls.__os_release_pattern_idlike
        )

    def _get_os_version(self) -> OsVersion:
        raise NotImplementedError


class Windows(OperatingSystem):
    __windows_version_pattern = re.compile(
        r"^OS Version:[\"\']?\s+(?P<value>.*?)[\"\']?$"
    )

    def __init__(self, node: Any) -> None:
        super().__init__(node, is_posix=False)

    def _get_os_version(self) -> OsVersion:
        os_version = OsVersion("Microsoft Corporation")
        cmd_result = self._node.execute(
            cmd='systeminfo | findstr /B /C:"OS Version"',
            no_error_log=True,
        )
        if cmd_result.exit_code == 0 and cmd_result.stdout != "":
            os_version.release = get_matched_str(
                cmd_result.stdout, self.__windows_version_pattern
            )
            if os_version.release == "":
                raise LisaException("OS version information not found")
        else:
            raise LisaException(
                "Error getting OS version info from systeminfo command"
                f"exit_code: {cmd_result.exit_code} stderr: {cmd_result.stderr}"
            )
        return os_version


class Posix(OperatingSystem, BaseClassMixin):
    BASEVERSION = re.compile(
        r"""[vV]?
        (?P<major>0|[1-9]\d*)
        (\.\-\_
        (?P<minor>0|[1-9]\d*)
        (\.\-\_
        (?P<patch>0|[1-9]\d*)
        )?
        )?""",
        re.VERBOSE,
    )

    __os_info_pattern = re.compile(
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
    # This regex gets the codename for the ditsro
    __distro_codename_pattern = re.compile(r"^.*\(([^)]+)")

    def __init__(self, node: Any) -> None:
        super().__init__(node, is_posix=True)
        self._first_time_installation: bool = True

    @classmethod
    def type_name(cls) -> str:
        return cls.__name__

    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        return re.compile(f"^{cls.type_name()}$")

    @property
    def release_version(self) -> VersionInfo:
        release_version = self._get_os_version().release
        if VersionInfo.isvalid(release_version):
            return VersionInfo.parse(release_version)

        return self._coerce_version(release_version)

    def _coerce_version(self, version: str) -> VersionInfo:
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
        match = self.BASEVERSION.search(version)
        if not match:
            raise LisaException("The OS version release is not in a valid format")

        ver: Dict[str, Any] = {
            key: 0 if value is None else int(value)
            for key, value in match.groupdict().items()
        }
        release_version = VersionInfo(**ver)
        rest = match.string[match.end() :]  # noqa:E203
        release_version.build = rest

        return release_version

    def _install_packages(
        self, packages: Union[List[str]], signed: bool = True
    ) -> None:
        raise NotImplementedError()

    def _update_packages(self, packages: Optional[Union[List[str]]] = None) -> None:
        raise NotImplementedError()

    def _package_exists(self, package: str, signed: bool = True) -> bool:
        raise NotImplementedError()

    def _initialize_package_installation(self) -> None:
        # sub os can override it, but it's optional
        pass

    def _get_os_version(self) -> OsVersion:
        os_version = OsVersion("")
        # try to set OsVersion from info in /etc/os-release.
        cmd_result = self._node.execute(cmd="cat /etc/os-release", no_error_log=True)
        if cmd_result.exit_code != 0:
            raise LisaException(
                "Error in running command 'cat /etc/os-release'"
                f"exit_code: {cmd_result.exit_code} stderr: {cmd_result.stderr}"
            )

        for row in cmd_result.stdout.splitlines():
            os_release_info = self.__os_info_pattern.match(row)
            if not os_release_info:
                continue
            if os_release_info.group("name") == "NAME":
                os_version.vendor = os_release_info.group("value")
            elif os_release_info.group("name") == "VERSION_ID":
                os_version.release = os_release_info.group("value")
            elif os_release_info.group("name") == "VERSION":
                os_version.codename = get_matched_str(
                    os_release_info.group("value"),
                    self.__distro_codename_pattern,
                )

        if os_version.vendor == "":
            raise LisaException("OS version information not found")

        return os_version

    def _get_package_list(
        self, packages: Union[str, Tool, Type[Tool], List[Union[str, Tool, Type[Tool]]]]
    ) -> List[str]:
        package_names: List[str] = []
        if not isinstance(packages, list):
            packages = [packages]

        assert isinstance(packages, list), f"actual:{type(packages)}"
        for item in packages:
            package_names.append(self.__resolve_package_name(item))
        if self._first_time_installation:
            self._first_time_installation = False
            self._initialize_package_installation()
        return package_names

    def _install_package_from_url(
        self,
        package: str,
        signed: bool = True,
    ) -> None:
        """
        Used if the package to be installed needs to be downloaded from a url first.
        """
        # when package is URL, download the package first at the working path.
        wget_tool = self._node.tools[Wget]
        pkg = wget_tool.get(package, str(self._node.working_path))
        self.install_packages(pkg, signed)

    def install_packages(
        self,
        packages: Union[str, Tool, Type[Tool], List[Union[str, Tool, Type[Tool]]]],
        signed: bool = True,
    ) -> None:
        package_names = self._get_package_list(packages)
        self._install_packages(package_names, signed)

    def package_exists(
        self, package: Union[str, Tool, Type[Tool]], signed: bool = True
    ) -> bool:
        """
        Query if a package/tool is installed on the node.
        Return Value - bool
        """
        package_name = self.__resolve_package_name(package)
        return self._package_exists(package_name)

    def update_packages(
        self, packages: Union[str, Tool, Type[Tool], List[Union[str, Tool, Type[Tool]]]]
    ) -> None:
        package_names = self._get_package_list(packages)
        self._update_packages(package_names)

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


class Linux(Posix):
    ...


class Debian(Linux):
    __lsb_os_info_pattern = re.compile(
        r"^(?P<name>.*):(\s+)(?P<value>.*?)?$", re.MULTILINE
    )

    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        return re.compile("^debian|Forcepoint|Kali$")

    def get_apt_error(self, stdout: str) -> List[str]:
        error_lines: List[str] = []
        for line in stdout.splitlines(keepends=False):
            if line.startswith("E: "):
                error_lines.append(line)
        return error_lines

    def wait_running_package_process(self) -> None:
        # wait for 5 minutes
        timeout = 60 * 5
        timer = create_timer()
        while timeout > timer.elapsed(False):
            cmd_result = self._node.execute("pidof dpkg")
            if cmd_result.exit_code == 1:
                # not found dpkg process, it's ok to exit.
                break
            time.sleep(1)

        if timeout < timer.elapsed():
            raise Exception("timeout to wait previous dpkg process stop.")

    def _initialize_package_installation(self) -> None:
        self.wait_running_package_process()
        self._node.execute("apt-get update", sudo=True)

    def _install_packages(
        self, packages: Union[List[str]], signed: bool = True
    ) -> None:
        command = (
            f"DEBIAN_FRONTEND=noninteractive "
            f"apt-get -y install {' '.join(packages)}"
        )
        if not signed:
            command += " --allow-unauthenticated"

        self.wait_running_package_process()
        install_result = self._node.execute(command, sudo=True)
        # get error lines.
        if install_result.exit_code != 0:
            install_result.assert_exit_code(
                0,
                f"Failed to install {packages}, "
                f"please check the package name and repo are correct or not.\n"
                + "\n".join(self.get_apt_error(install_result.stdout))
                + "\n",
            )

    def _package_exists(self, package: str, signed: bool = True) -> bool:
        command = "dpkg --get-selections"
        result = self._node.execute(command, sudo=True, shell=True)
        package_pattern = re.compile(f"{package}([ \t]+)install")
        # Not installed package not shown in the output
        # Uninstall package will show as deinstall
        # vim                                             deinstall
        # vim-common                                      install
        if len(list(filter(package_pattern.match, result.stdout.splitlines()))) == 1:
            return True
        return False

    def _get_os_version(self) -> OsVersion:
        os_version = OsVersion("")
        cmd_result = self._node.execute(
            cmd="lsb_release -a", shell=True, no_error_log=True
        )
        if cmd_result.exit_code == 0 and cmd_result.stdout != "":
            for row in cmd_result.stdout.splitlines():
                os_release_info = self.__lsb_os_info_pattern.match(row)
                if os_release_info:
                    if os_release_info.group("name") == "Distributor ID":
                        os_version.vendor = os_release_info.group("value")
                    elif os_release_info.group("name") == "Release":
                        os_version.release = os_release_info.group("value")
                    elif os_release_info.group("name") == "Codename":
                        os_version.codename = os_release_info.group("value")
            if os_version.vendor == "":
                raise LisaException("OS version information not found")
        else:
            raise LisaException(
                f"Command 'lsb_release -a' failed. "
                f"exit_code:{cmd_result.exit_code} stderr: {cmd_result.stderr}"
            )

        return os_version

    def _update_packages(self, packages: Optional[Union[List[str]]] = None) -> None:
        command = (
            "DEBIAN_FRONTEND=noninteractive apt-get upgrade -y "
            '-o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" '
        )
        if packages:
            command += " ".join(packages)
        self._node.execute(command, sudo=True, timeout=3600)


class Ubuntu(Debian):
    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        return re.compile("^Ubuntu|ubuntu$")

    def set_boot_entry(self, entry: str) -> None:
        self._log.debug(f"set boot entry to: {entry}")
        self._node.execute(
            f"sed -i.bak \"s/GRUB_DEFAULT=.*/GRUB_DEFAULT='{entry}'/g\" "
            f"/etc/default/grub",
            sudo=True,
            shell=True,
        )

        # output to log for troubleshooting
        cat = self._node.tools[Cat]
        cat.run("/etc/default/grub")


class FreeBSD(BSD):
    ...


class OpenBSD(BSD):
    ...


class Fedora(Linux):
    # Red Hat Enterprise Linux Server 7.8 (Maipo) => 7.8
    _fedora_release_pattern_version = re.compile(r"^.*release\s+([0-9\.]+).*$")

    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        return re.compile("^Fedora|fedora$")

    def _install_packages(
        self, packages: Union[List[str]], signed: bool = True
    ) -> None:
        command = f"dnf install -y {' '.join(packages)}"
        if not signed:
            command += " --nogpgcheck"

        install_result = self._node.execute(command, sudo=True)
        install_result.assert_exit_code(0, f"Failed to install {packages}.")

        self._log.debug(f"{packages} is/are installed successfully.")

    def _package_exists(self, package: str, signed: bool = True) -> bool:
        command = f"dnf list installed {package}"
        result = self._node.execute(command, sudo=True)
        if result.exit_code == 0:
            for row in result.stdout.splitlines():
                if package in row:
                    return True

        return False

    def _get_os_version(self) -> OsVersion:
        os_version = OsVersion("")
        cmd_result = self._node.execute(
            # Typical output of 'cat /etc/fedora-release' is -
            # Fedora release 22 (Twenty Two)
            cmd="cat /etc/fedora-release",
            no_error_log=True,
        )
        if cmd_result.exit_code == 0 and cmd_result.stdout != "":
            if "Fedora" not in cmd_result.stdout:
                raise LisaException("OS version information not found")
            os_version.vendor = "Fedora"
            os_version.release = get_matched_str(
                cmd_result.stdout, self._fedora_release_pattern_version
            )
            os_version.codename = get_matched_str(
                cmd_result.stdout, self.__distro_codename_pattern
            )
        else:
            raise LisaException(
                "Error in running command 'cat /etc/fedora-release'"
                f"exit_code: {cmd_result.exit_code} stderr: {cmd_result.stderr}"
            )

        return os_version


class Redhat(Fedora):
    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        return re.compile("^rhel|Red|AlmaLinux|Rocky|Scientific|acronis|Actifio$")

    def _initialize_package_installation(self) -> None:
        cmd_result = self._node.execute("yum makecache", sudo=True)
        os_version = self._get_os_version()
        # We may hit issue when run any yum command, caused by out of date
        #  rhui-microsoft-azure-rhel package.
        # Use below command to update rhui-microsoft-azure-rhel package from microsoft
        #  repo to resolve the issue.
        # Details please refer https://docs.microsoft.com/en-us/azure/virtual-machines/workloads/redhat/redhat-rhui#azure-rhui-infrastructure # noqa: E501
        if "Red Hat" == os_version.vendor and cmd_result.exit_code != 0:
            cmd_result = self._node.execute(
                "yum update -y --disablerepo='*' --enablerepo='*microsoft*' ", sudo=True
            )
            cmd_result = self._node.execute("yum makecache", sudo=True)

    def _install_packages(
        self, packages: Union[List[str]], signed: bool = True
    ) -> None:
        command = f"yum install -y {' '.join(packages)}"
        if not signed:
            command += " --nogpgcheck"

        install_result = self._node.execute(command, sudo=True)
        # yum returns exit_code=1 if package is already installed.
        # We do not want to fail if exit_code=1.
        if install_result.exit_code == 1:
            self._log.debug(f"{packages} is/are already installed.")
        elif install_result.exit_code == 0:
            self._log.debug(f"{packages} is/are installed successfully.")
        else:
            raise LisaException(
                f"Failed to install {packages}. exit_code: {install_result.exit_code}, "
                f"stderr: {install_result.stderr}"
            )

    def _package_exists(self, package: str, signed: bool = True) -> bool:
        command = f"yum list installed {package}"
        result = self._node.execute(command, sudo=True)
        if result.exit_code == 0:
            return True

        return False

    def _get_os_version(self) -> OsVersion:
        os_version = OsVersion("")
        cmd_result = self._node.execute(
            cmd="cat /etc/redhat-release", no_error_log=True
        )
        if cmd_result.exit_code == 0 and cmd_result.stdout != "":
            for vendor in [
                "Red Hat",
                "CentOS",
                "XenServer",
                "AlmaLinux",
                "Rocky Linux",
            ]:
                if vendor not in cmd_result.stdout:
                    continue
                os_version.vendor = vendor
                os_version.release = get_matched_str(
                    cmd_result.stdout,
                    Fedora._fedora_release_pattern_version,
                )
                os_version.codename = get_matched_str(
                    cmd_result.stdout,
                    _redhat_release_pattern_bracket,
                )
                break
            if os_version.vendor == "":
                raise LisaException("OS version information not found")
        else:
            raise LisaException(
                "Error in running command 'cat /etc/redhat-release'"
                f"exit_code: {cmd_result.exit_code} stderr: {cmd_result.stderr}"
            )

        return os_version

    def _update_packages(self, packages: Optional[Union[List[str]]] = None) -> None:
        command = "yum -y --nogpgcheck update "
        if packages:
            command += " ".join(packages)
        # older images cost much longer time when update packages
        # smaller sizes cost much longer time when update packages, e.g.
        #  Basic_A1, Standard_A5, Standard_A1_v2, Standard_D1
        # redhat rhel 7-lvm 7.7.2019102813 Basic_A1 cost 2371.568 seconds
        # redhat rhel 8.1 8.1.2020020415 Basic_A0 cost 2409.116 seconds
        self._node.execute(command, sudo=True, timeout=3600)


class CentOs(Redhat):
    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        return re.compile("^CentOS|Centos|centos|clear-linux-os$")


class Oracle(Redhat):
    pass


class CoreOs(Redhat):
    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        return re.compile("^coreos|Flatcar|flatcar$")


class Suse(Linux):
    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        return re.compile("^SLES|SUSE|sles|sle-hpc|sle_hpc|opensuse-leap$")

    def _initialize_package_installation(self) -> None:
        self._node.execute(
            "zypper --non-interactive --gpg-auto-import-keys refresh", sudo=True
        )

    def _install_packages(
        self, packages: Union[List[str]], signed: bool = True
    ) -> None:
        command = f"zypper --non-interactive in {' '.join(packages)}"
        if not signed:
            command += " --no-gpg-checks"
        install_result = self._node.execute(command, sudo=True)
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

    def _update_packages(self, packages: Optional[Union[List[str]]] = None) -> None:
        command = "zypper --non-interactive --gpg-auto-import-keys update "
        if packages:
            command += " ".join(packages)
        self._node.execute(command, sudo=True, timeout=3600)


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
