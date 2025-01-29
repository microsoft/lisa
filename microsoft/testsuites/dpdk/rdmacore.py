from assertpy import assert_that
from semver import VersionInfo

from lisa import UnsupportedCpuArchitectureException
from lisa.operating_system import Debian, Fedora, Suse
from lisa.tools import Make, Pkgconfig
from lisa.tools.lscpu import CpuArchitecture
from microsoft.testsuites.dpdk.common import (
    DependencyInstaller,
    Installer,
    OsPackageDependencies,
    PackageManagerInstall,
    get_debian_backport_repo_args,
    unsupported_os_thrower,
)

RDMA_CORE_MANA_DEFAULT_SOURCE = (
    "https://github.com/linux-rdma/rdma-core/"
    "releases/download/v50.1/rdma-core-50.1.tar.gz"
)
RDMA_CORE_I386_MANA_DEFAULT_SOURCE = (
    "https://github.com/linux-rdma/rdma-core/"
    "releases/download/v53.1/rdma-core-53.1.tar.gz"
)
RDMA_CORE_SOURCE_DEPENDENCIES = DependencyInstaller(
    [
        OsPackageDependencies(
            matcher=lambda os, _arch=None: isinstance(os, Debian)  # type: ignore
            # install linux-modules-extra-azure if it's available for mana_ib
            # older debian kernels won't have mana_ib packaged,
            # so skip the check on those kernels.
            and bool(os.get_kernel_information().version >= "5.15.0")
            and os.is_package_in_repo("linux-modules-extra-azure"),
            packages=["linux-modules-extra-azure"],
        ),
        OsPackageDependencies(
            matcher=lambda os, arch=None: isinstance(os, (Debian))  # type: ignore
            and arch == CpuArchitecture.I386,
            packages=[
                "python3-pyelftools",
                "libelf-dev:i386",
                "libnuma-dev:i386",
                "pkg-config",
                "python3-pip",
                "cmake",
                "libnl-3-dev:i386",
                "libnl-route-3-dev:i386",
                "meson",
                "gcc-i686-linux-gnu",
                "python3-dev:i386",
                "libudev-dev:i386",
                "libudev-dev",
                "libnl-3-dev",
                "libnl-route-3-dev",
                "libssl-dev",
                "libelf-dev",
            ],
        ),
        OsPackageDependencies(
            matcher=lambda os, arch=None: isinstance(os, (Debian))  # type: ignore
            and arch == CpuArchitecture.I386,
            # Weirdly, I've run into errors trying to
            packages=[
                "cython3:i386",
            ],
            stop_on_match=True,
        ),
        OsPackageDependencies(
            matcher=lambda os, _arch=None: isinstance(os, Debian),  # type: ignore
            packages=[
                "cmake",
                "libudev-dev",
                "libnl-3-dev",
                "libnl-route-3-dev",
                "ninja-build",
                "pkg-config",
                "valgrind",
                "python3-dev",
                "cython3",
                "python3-docutils",
                "pandoc",
                "libssl-dev",
                "libelf-dev",
                "python3-pip",
                "libnuma-dev",
            ],
            stop_on_match=True,
        ),
        OsPackageDependencies(
            matcher=lambda os, _arch=None: isinstance(os, Fedora),  # type: ignore
            packages=[
                "cmake",
                "libudev-devel",
                "libnl3-devel",
                "pkg-config",
                "valgrind",
                "python3-devel",
                "openssl-devel",
                "unzip",
                "elfutils-devel",
                "python3-pip",
                "tar",
                "wget",
                "dos2unix",
                "psmisc",
                "kernel-devel-$(uname -r)",
                "librdmacm-devel",
                "libmnl-devel",
                "kernel-modules-extra",
                "numactl-devel",
                "kernel-headers",
                "elfutils-libelf-devel",
                "libbpf-devel",
            ],
            stop_on_match=True,
        ),
        # FIXME: SUSE rdma-core build packages not implemented
        #        for source builds.
        OsPackageDependencies(matcher=unsupported_os_thrower),
    ]
)


RDMA_CORE_PACKAGE_DEPENDENCIES = DependencyInstaller(
    [
        OsPackageDependencies(
            matcher=lambda os, _=None: isinstance(os, Debian)  # type: ignore
            # install linux-modules-extra-azure if it's available for mana_ib
            # older debian kernels won't have mana_ib packaged,
            # so skip the check on those kernels.
            and bool(os.get_kernel_information().version >= "5.15.0")
            and os.is_package_in_repo("linux-modules-extra-azure"),
            packages=["linux-modules-extra-azure"],
        ),
        OsPackageDependencies(
            matcher=lambda os, _=None: isinstance(os, Debian),  # type: ignore
            packages=["ibverbs-providers", "libibverbs-dev"],
        ),
        OsPackageDependencies(
            matcher=lambda os, _=None: isinstance(os, Suse),  # type: ignore
            packages=["rdma-core-devel", "librdmacm1"],
        ),
        OsPackageDependencies(
            matcher=lambda os, _=None: isinstance(os, Fedora),  # type: ignore
            packages=["librdmacm-devel"],
        ),
        OsPackageDependencies(
            matcher=lambda os, _=None: isinstance(  # type: ignore
                os, (Fedora, Debian, Suse)
            ),
            packages=["rdma-core"],
            stop_on_match=True,
        ),
        OsPackageDependencies(matcher=unsupported_os_thrower),
    ]
)


# Common parent for isinstance matching
class RdmaCoreInstaller(Installer):
    ...


class RdmaCorePackageManagerInstall(RdmaCoreInstaller, PackageManagerInstall):
    def _setup_node(self) -> None:
        if isinstance(self._os, Fedora):
            self._os.install_epel()
        if isinstance(self._os, Debian):
            self._package_manager_extra_args = get_debian_backport_repo_args(self._os)
        super()._setup_node()

    def get_installed_version(self) -> VersionInfo:
        return self._os.get_package_information("rdma-core", use_cached=False)

    def _check_if_installed(self) -> bool:
        return self._os.package_exists("rdma-core")


# implement SourceInstall for DPDK
class RdmaCoreSourceInstaller(RdmaCoreInstaller):
    def _check_if_installed(self) -> bool:
        try:
            package_manager_install = self._os.package_exists("rdma-core")
            # _get_installed_version for source install throws
            # if package is not found. So we don't need the result,
            # if the function doesn't throw, the version was found.
            _ = self.get_installed_version()
            # this becomes '(not package manager installed) and
            #                _get_installed_version() doesn't throw'
            return not package_manager_install
        except AssertionError:
            # _get_installed_version threw an AssertionError
            # so PkgConfig info was not found
            return False

    def _setup_node(self) -> None:
        self._pkg_config_path = None
        if isinstance(self._os, (Debian, Fedora, Suse)):
            self._os.uninstall_packages("rdma-core")
        if isinstance(self._os, Fedora):
            self._os.group_install_packages("Development Tools")
        if not self._arch or self._arch in [CpuArchitecture.ARM64, CpuArchitecture.X64]:
            self._cmake_command = (
                "cmake -DIN_PLACE=0 -DNO_MAN_PAGES=1 -DCMAKE_INSTALL_PREFIX=/usr"
            )
        # Only support this 32bit build on one distro family.
        elif isinstance(self._os, Debian) and self._arch == CpuArchitecture.I386:
            self._pkg_config_path = "/usr/local/lib/i386-linux-gnu/pkgconfig"
            # enable 32bit packages, needed for dependencies
            self._node.execute(
                "dpkg --add-architecture i386",
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message="Could not enable i386 packages.",
            )
            self._node.execute(
                "apt update",
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Apt update after enabling i386 failed"
                ),
            )
            self._cmake_command = (
                "cmake "
                "-DIN_PLACE=0 -DNO_MAN_PAGES=1 -DCMAKE_INSTALL_PREFIX=/usr "
                "-DCMAKE_C_COMPILER=/usr/bin/i686-linux-gnu-gcc -DCMAKE_C_FLAGS=-m32"
            )
        else:
            # Will hit this when adding a new CPU Architecture,
            # so hello to whoever is adding RISC-V :)
            raise UnsupportedCpuArchitectureException(arch=self._arch)
        super()._setup_node()

    def _uninstall(self) -> None:
        # undo source installation (thanks ninja)
        if not self._check_if_installed():
            return
        self._node.tools[Make].run(
            parameters="uninstall", shell=True, sudo=True, cwd=self.asset_path
        )
        working_path = str(self._node.get_working_path())
        assert_that(str(self.asset_path)).described_as(
            "RDMA Installer source path was empty during attempted cleanup!"
        ).is_not_empty()
        assert_that(str(self.asset_path)).described_as(
            "RDMA Installer source path was set to root dir "
            "'/' during attempted cleanup!"
        ).is_not_equal_to("/")
        assert_that(str(self.asset_path)).described_as(
            f"RDMA Installer source path {self.asset_path} was set to "
            f"working path '{working_path}' during attempted cleanup!"
        ).is_not_equal_to(working_path)
        # remove source code directory
        self._node.execute(f"rm -rf {str(self.asset_path)}", shell=True)

    def get_installed_version(self) -> VersionInfo:
        return self._node.tools[Pkgconfig].get_package_version(
            "libibverbs", update_cached=True, pkg_config_path=self._pkg_config_path
        )

    def _install(self) -> None:
        super()._install()
        node = self._node
        make = node.tools[Make]
        node.execute(
            self._cmake_command,
            shell=True,
            cwd=self.asset_path,
            sudo=True,
        )
        make.make_install(self.asset_path)
