import re
from functools import partial
from typing import TYPE_CHECKING, Any, Iterable, List, Optional, Pattern, Type, Union

from lisa.executable import Tool
from lisa.util import LisaException, get_matched_str
from lisa.util.logger import get_logger
from lisa.util.subclasses import BaseClassMixin, Factory

if TYPE_CHECKING:
    from lisa.node import Node


_get_init_logger = partial(get_logger, name="os")


class OperatingSystem:
    __lsb_release_pattern = re.compile(r"^Description:[ \t]+([\w]+)[ ]+$", re.M)
    __os_release_pattern_name = re.compile(r"^NAME=\"?([^\" \n]+)[^\" \n]*\"?$", re.M)
    __os_release_pattern_id = re.compile(r"^ID=\"?([^\" \n]+)[^\" \n]*\"?$", re.M)
    __redhat_release_pattern_header = re.compile(r"^([^ ]*) .*$")
    __redhat_release_pattern_bracket = re.compile(r"^.*\(([^ ]*).*\)$")
    __debian_issue_pattern = re.compile(r"^([^ ]+) ?.*$")
    __release_pattern = re.compile(r"^DISTRIB_ID='?([^ \n']+).*$", re.M)
    __suse_release_pattern = re.compile(r"^(SUSE).*$", re.M)

    __linux_factory: Optional[Factory[Any]] = None

    def __init__(self, node: Any, is_linux: bool) -> None:
        super().__init__()
        self._node: Node = node
        self._is_linux = is_linux
        self._log = get_logger(name="os", parent=self._node.log)

    @classmethod
    def create(cls, node: Any) -> Any:
        typed_node: Node = node
        log = _get_init_logger(parent=typed_node.log)
        result: Optional[OperatingSystem] = None

        detected_info = ""
        if typed_node.shell.is_linux:
            # delay create factory to make sure it's late than loading extensions
            if cls.__linux_factory is None:
                cls.__linux_factory = Factory[Linux](Linux)
                cls.__linux_factory.initialize()
            # cast type for easy to use
            linux_factory: Factory[Linux] = cls.__linux_factory

            matched = False
            os_infos: List[str] = []
            for os_info_item in cls._get_detect_string(node):
                if os_info_item:
                    os_infos.append(os_info_item)
                for sub_type in linux_factory.values():
                    linux_type: Type[Linux] = sub_type
                    pattern = linux_type.name_pattern()
                    if pattern.findall(os_info_item):
                        detected_info = os_info_item
                        result = linux_type(typed_node)
                        matched = True
                        break
                if matched:
                    break

            if not os_infos:
                raise LisaException(
                    "unknown linux distro, no os info found. "
                    "it may cause by not support basic commands like `cat`"
                )
            elif not result:
                raise LisaException(
                    f"unknown linux distro names '{os_infos}', "
                    f"support it in operating_system."
                )
        else:
            result = Windows(typed_node)
        log.debug(
            f"detected OS: '{result.__class__.__name__}' by pattern '{detected_info}'"
        )
        return result

    @property
    def is_windows(self) -> bool:
        return not self._is_linux

    @property
    def is_linux(self) -> bool:
        return self._is_linux

    @classmethod
    def _get_detect_string(cls, node: Any) -> Iterable[str]:
        typed_node: Node = node
        cmd_result = typed_node.execute(cmd="lsb_release -d", no_error_log=True)
        yield get_matched_str(cmd_result.stdout, cls.__lsb_release_pattern)

        cmd_result = typed_node.execute(cmd="cat /etc/os-release", no_error_log=True)
        yield get_matched_str(cmd_result.stdout, cls.__os_release_pattern_name)
        yield get_matched_str(cmd_result.stdout, cls.__os_release_pattern_id)

        # for RedHat, CentOS 6.x
        cmd_result = typed_node.execute(
            cmd="cat /etc/redhat-release", no_error_log=True
        )
        yield get_matched_str(cmd_result.stdout, cls.__redhat_release_pattern_header)
        yield get_matched_str(cmd_result.stdout, cls.__redhat_release_pattern_bracket)

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


class Windows(OperatingSystem):
    def __init__(self, node: Any) -> None:
        super().__init__(node, is_linux=False)


class Linux(OperatingSystem, BaseClassMixin):
    def __init__(self, node: Any) -> None:
        super().__init__(node, is_linux=True)
        self._first_time_installation: bool = True

    @classmethod
    def type_name(cls) -> str:
        return cls.__name__

    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        return re.compile(f"^{cls.type_name()}$")

    def _install_packages(self, packages: Union[List[str]]) -> None:
        raise NotImplementedError()

    def _initialize_package_installation(self) -> None:
        # sub os can override it, but it's optional
        pass

    def install_packages(
        self, packages: Union[str, Tool, Type[Tool], List[Union[str, Tool, Type[Tool]]]]
    ) -> None:
        package_names: List[str] = []
        if not isinstance(packages, list):
            packages = [packages]

        assert isinstance(packages, list), f"actual:{type(packages)}"
        for item in packages:
            if isinstance(item, str):
                package_names.append(item)
            elif isinstance(item, Tool):
                package_names.append(item.package_name)
            else:
                assert isinstance(item, type), f"actual:{type(item)}"
                # Create a temp object, it doesn't trigger install.
                # So they can be installed together.
                tool = item.create(self._node)
                package_names.append(tool.package_name)
        if self._first_time_installation:
            self._first_time_installation = False
            self._initialize_package_installation()
        self._install_packages(package_names)


class Ubuntu(Linux):
    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        return re.compile("^Ubuntu|ubuntu$")

    def _initialize_package_installation(self) -> None:
        self._node.execute("sudo apt-get update")

    def _install_packages(self, packages: Union[List[str]]) -> None:
        command = (
            f"sudo DEBIAN_FRONTEND=noninteractive "
            f"apt-get -y install {' '.join(packages)}"
        )
        self._node.execute(command)


class Debian(Ubuntu):
    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        return re.compile("^debian|Forcepoint|Kali$")


class Unix(Linux):
    """
    The inherits may look weird, which put Linux first.
    Let's check later, if it need to be reversed.
    """

    pass


class FreeBSD(Unix):
    pass


class Redhat(Linux):
    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        return re.compile("^rhel|Red|Scientific|acronis|Actifio$")

    def _install_packages(self, packages: Union[List[str]]) -> None:
        self._node.execute(
            f"sudo DEBIAN_FRONTEND=noninteractive yum install -y {' '.join(packages)}"
        )


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
        return re.compile("^SLES|SUSE|sles|sle-hpc|sle_hpc$")

    def _initialize_package_installation(self) -> None:
        self._node.execute("zypper --non-interactive --gpg-auto-import-keys update")

    def _install_packages(self, packages: Union[List[str]]) -> None:
        command = f"sudo zypper --non-interactive in  {' '.join(packages)}"
        self._node.execute(command)


class NixOS(Linux):
    pass


class OtherLinux(Linux):
    @classmethod
    def name_pattern(cls) -> Pattern[str]:
        return re.compile("^Sapphire|Buildroot|OpenWrt$")
