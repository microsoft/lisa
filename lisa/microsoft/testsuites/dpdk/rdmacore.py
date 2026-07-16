from assertpy import assert_that
from microsoft.testsuites.dpdk.common import (
    DependencyInstaller,
    Installer,
    OsPackageDependencies,
    PackageManagerInstall,
    get_debian_backport_repo_args,
    unsupported_os_thrower,
)
from semver import VersionInfo

from lisa.operating_system import Debian, Fedora, Suse
from lisa.tools import Make, Pkgconfig

RDMA_CORE_MANA_DEFAULT_SOURCE = (
    "https://github.com/linux-rdma/rdma-core/"
    "releases/download/v50.1/rdma-core-50.1.tar.gz"
)
RDMA_CORE_SOURCE_DEPENDENCIES = DependencyInstaller(
    [
        OsPackageDependencies(
            matcher=lambda x: isinstance(x, Debian)
            # install linux-modules-extra-azure if it's available for mana_ib
            # older debian kernels won't have mana_ib packaged,
            # so skip the check on those kernels.
            and bool(x.get_kernel_information().version >= "5.15.0")
            and x.is_package_in_repo("linux-modules-extra-azure"),
            packages=["linux-modules-extra-azure"],
        ),
        OsPackageDependencies(
            matcher=lambda x: isinstance(x, Debian),
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
            matcher=lambda x: isinstance(x, Fedora),
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

RDMA_CORE_PACKAGE_MANAGER_DEPENDENCIES = DependencyInstaller(
    [
        OsPackageDependencies(
            matcher=lambda x: isinstance(x, Debian)
            # install linux-modules-extra-azure if it's available for mana_ib
            # older debian kernels won't have mana_ib packaged,
            # so skip the check on those kernels.
            and bool(x.get_kernel_information().version >= "5.15.0")
            and x.is_package_in_repo("linux-modules-extra-azure"),
            packages=["linux-modules-extra-azure"],
        ),
        OsPackageDependencies(
            matcher=lambda x: isinstance(x, Debian),
            packages=["ibverbs-providers", "libibverbs-dev"],
        ),
        OsPackageDependencies(
            matcher=lambda x: isinstance(x, Suse),
            packages=["rdma-core-devel", "librdmacm1"],
        ),
        OsPackageDependencies(
            matcher=lambda x: isinstance(x, Fedora),
            packages=["librdmacm-devel"],
        ),
        OsPackageDependencies(
            matcher=lambda x: isinstance(x, (Fedora, Debian, Suse)),
            packages=["rdma-core"],
            stop_on_match=True,
        ),
        OsPackageDependencies(matcher=unsupported_os_thrower),
    ]
)


class RdmaCorePackageManagerInstall(PackageManagerInstall):  # type: ignore[misc]
    def _setup_node(self) -> None:
        if isinstance(self._os, Fedora):
            self._os.install_epel()
        if isinstance(self._os, Debian):
            self._package_manager_extra_args = get_debian_backport_repo_args(self._os)
        super()._setup_node()

    def get_installed_version(self) -> VersionInfo:
        version: VersionInfo = self._os.get_package_information(
            "rdma-core", use_cached=False
        )
        return version

    def _check_if_installed(self) -> bool:
        exists = self._os.package_exists("rdma-core")
        return bool(exists)


# implement SourceInstall for DPDK
class RdmaCoreSourceInstaller(Installer):  # type: ignore[misc]
    def _check_if_installed(self) -> bool:
        # check if pkg-config info is available
        try:
            _ = self.get_installed_version()
        except AssertionError:
            # get_installed_version threw an AssertionError
            # PkgConfig info was not found;
            # so it's not a source installation.
            return False

        # check if the package was installed from apt, dnf, etc.
        package_manager_install = self._os.package_exists("rdma-core")
        # we don't want it to be installed from the package manager.
        return not package_manager_install

    def _setup_node(self) -> None:
        if isinstance(self._os, (Debian, Fedora, Suse)):
            if self._os.package_exists("rdma-core"):
                self._os.uninstall_packages("rdma-core")
        if isinstance(self._os, Fedora):
            self._os.group_install_packages("Development Tools")
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
        version: VersionInfo = self._node.tools[Pkgconfig].get_package_version(
            "libibverbs", update_cached=True
        )
        return version

    def _install(self) -> None:
        super()._install()
        node = self._node
        make = node.tools[Make]
        node.execute(
            "cmake -DIN_PLACE=0 -DNO_MAN_PAGES=1 -DCMAKE_INSTALL_PREFIX=/usr",
            shell=True,
            cwd=self.asset_path,
            sudo=True,
        )
        make.make_install(self.asset_path)
        # rdma-core installs some systemd services for infiniband that
        # we don't actually want enabled for these dpdk tests.
        #
        # this ends up preventing login via ssh for like 3 minutes
        # while it times out and restarts during the next boot.
        #
        # We're only using rdma for the ib verbs,
        # so we can safely just mask this service.
        mask_result = node.execute("systemctl mask rdma-ndd.service", sudo=True)
        if mask_result.exit_code != 0:
            node.log.debug(
                "Failed to mask rdma-ndd.service "
                f"(exit_code={mask_result.exit_code}). "
                f"stdout: {mask_result.stdout}, stderr: {mask_result.stderr}"
            )
