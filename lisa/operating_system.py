import re
from functools import partial
from typing import TYPE_CHECKING, Any, List, Optional, Type, Union

from lisa.executable import Tool
from lisa.util import LisaException
from lisa.util.logger import get_logger

if TYPE_CHECKING:
    from lisa.node import Node

_get_init_logger = partial(get_logger, name="os")


class OperatingSystem:
    __lsb_release_pattern = re.compile(r"^Description:[ \t]+([\w]+)[ ]+")
    __os_release_pattern = re.compile(r"^NAME=\"?([\w]+)[^\" ]*\"?", re.M)

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
        if typed_node.shell.is_linux:
            lsb_output = typed_node.execute("lsb_release -d")
            if lsb_output.stdout:
                os_info = cls.__lsb_release_pattern.findall(lsb_output.stdout)
                if os_info and os_info[0] == "Ubuntu":
                    result = Ubuntu(typed_node)
            if not result:
                os_release_output = typed_node.execute("cat /etc/os-release")
                if os_release_output.stdout:
                    os_info = cls.__os_release_pattern.findall(os_release_output.stdout)
                    if os_info and os_info[0] == "CentOS":
                        result = CentOs(typed_node)
            if not result:
                raise LisaException(
                    f"unknown linux distro {lsb_output.stdout}\n"
                    f" {os_release_output.stdout}\n"
                    f"support it in operating_system"
                )
        else:
            result = Windows(typed_node)
        log.debug(f"detected OS: {result.__class__.__name__}")
        return result

    @property
    def is_windows(self) -> bool:
        return not self._is_linux

    @property
    def is_linux(self) -> bool:
        return self._is_linux


class Windows(OperatingSystem):
    def __init__(self, node: Any) -> None:
        super().__init__(node, is_linux=False)


class Linux(OperatingSystem):
    def __init__(self, node: Any) -> None:
        super().__init__(node, is_linux=True)

    def _install_packages(self, packages: Union[List[str]]) -> None:
        raise NotImplementedError()

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
        self._install_packages(package_names)


class Ubuntu(Linux):
    def __init__(self, node: Any) -> None:
        super().__init__(node)
        self._first_time: bool = True

    def _install_packages(self, packages: Union[List[str]]) -> None:
        if self._first_time:
            self._first_time = False
            self._node.execute("sudo apt-get update")

        command = (
            f"sudo DEBIAN_FRONTEND=noninteractive "
            f"apt-get -y install {' '.join(packages)}"
        )
        self._node.execute(command)


class CentOs(Linux):
    def __init__(self, node: Any) -> None:
        super().__init__(node)
        self._first_time: bool = True

    def _install_packages(self, packages: Union[List[str]]) -> None:
        if self._first_time:
            self._first_time = False
            self._node.execute("sudo yum update")

        self._node.execute(
            f"sudo DEBIAN_FRONTEND=noninteractive yum install -y {' '.join(packages)}"
        )
