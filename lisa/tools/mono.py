from typing import Any

from lisa.base_tools import Wget
from lisa.executable import Tool
from lisa.operating_system import Ubuntu
from lisa.tools import Echo
from lisa.util import UnsupportedDistroException

from .ls import Ls


class Mono(Tool):
    @property
    def command(self) -> str:
        return "mono"

    @property
    def can_install(self) -> bool:
        return True

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self.nuget_path = "/usr/local/bin/nuget.exe"
        self._ensure_nuget_installed()

    def _ensure_nuget_installed(self) -> None:
        ls = self.node.tools[Ls]
        if not ls.path_exists(self.nuget_path, sudo=True):
            self.node.tools[Wget].get(
                url="https://dist.nuget.org/win-x86-commandline/latest/nuget.exe",
                file_path="/usr/local/bin",
                filename="nuget.exe",
                executable=True,
                sudo=True,
            )

    def install(self) -> bool:
        if isinstance(self.node.os, Ubuntu):
            self._install_mono_on_ubuntu()
        else:
            raise UnsupportedDistroException(os=self.node.os)
        return self._check_exists()

    def _install_mono_on_ubuntu(self) -> None:
        if isinstance(self.node.os, Ubuntu):
            required_packages = [
                "dirmngr",
                "gnupg",
                "apt-transport-https",
                "ca-certificates",
            ]
            self.node.os.install_packages(required_packages)

            mono_repo_entry = (
                "deb https://download.mono-project.com/repo/"
                f"ubuntu stable-{self.node.os.information.codename} main"
            )
            self.node.tools[Echo].write_to_file(
                value=mono_repo_entry,
                file=self.node.get_pure_path(
                    "/etc/apt/sources.list.d/mono-official-stable.list"
                ),
                sudo=True,
            )

            # the key 3FA7E0328081BFF6A14DA29AA6A19B38D3D831EF is for mono repo
            # https://www.mono-project.com/download/stable/#download-lin-ubuntu
            self.node.os.add_key(
                server_name="hkp://keyserver.ubuntu.com:80",
                key="3FA7E0328081BFF6A14DA29AA6A19B38D3D831EF",
            )
            self.node.os.install_packages("mono-devel")

    def remove_source(self, name: str, source: str, nuget_path: str = "") -> None:
        self._run_nuget_command(
            f"sources remove -Name {name} -Source {source}", nuget_path
        )

    def add_source(
        self,
        name: str,
        source: str,
        user_name: str,
        password: str,
        nuget_path: str = "",
    ) -> None:
        self._run_nuget_command(
            f"sources add -Name {name} -Source {source} "
            f"-username {user_name} -password {password}",
            nuget_path,
        )

    def install_package(
        self, package_name: str, version: str, source: str, nuget_path: str = ""
    ) -> None:
        self._run_nuget_command(
            f"install {package_name} -Version {version} -Source {source}", nuget_path
        )

    def _run_nuget_command(self, command: str, nuget_path: str) -> None:
        path = nuget_path or self.nuget_path
        self.run(f"{path} {command}")
