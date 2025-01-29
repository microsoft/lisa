# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePath
from typing import Any, Callable, Dict, List, Optional, Sequence, Type, Union
from urllib.parse import urlparse

from assertpy import assert_that
from semver import VersionInfo
from urllib3.util.url import parse_url

from lisa import Node
from lisa.executable import Tool
from lisa.operating_system import Debian, Fedora, Oracle, Posix, Suse, Ubuntu
from lisa.tools import Git, Lscpu, Tar, Wget
from lisa.tools.lscpu import CpuArchitecture
from lisa.util import UnsupportedCpuArchitectureException, UnsupportedDistroException

DPDK_STABLE_GIT_REPO = "https://dpdk.org/git/dpdk-stable"
# 32bit test relies on newer versions of DPDK.
# Release candidates are not in stable, so use the github mirror.
DPDK_32BIT_DEFAULT_BRANCH = "v24.11"
# MANA testing requires newer versions of DPDK.
DPDK_MANA_DEFAULT_BRANCH = "v24.11"
# azure routing table magic subnet prefix
# signals 'route all traffic on this subnet'
AZ_ROUTE_ALL_TRAFFIC = "0.0.0.0/0"

ARCH_COMPATIBILITY_MATRIX = {
    CpuArchitecture.X64: [CpuArchitecture.X64],
    CpuArchitecture.I386: [CpuArchitecture.I386, CpuArchitecture.X64],
    CpuArchitecture.ARM64: [CpuArchitecture.ARM64],
}


# Attempt to clean up the DPDK package dependency mess
# Make a Installer class that implements the common steps
# for installing DPDK/rdma-core, either from source or the package manager.
# This generic class will get implemented in DpdkTestpmd and RdmaCore.
# This should help us cover the various installation cases in a nice way,
# and allow us to only re-implement the bits we need for each project.
class OsPackageDependencies:
    # A class to reduce the isinstance() trees that are
    # sprinkled everywhere.
    # Caller provides a function to match an OS and
    # the packages to install on that OS.
    def __init__(
        self,
        matcher: Callable[[Posix, Optional[CpuArchitecture]], bool],
        packages: Optional[Sequence[Union[str, Tool, Type[Tool]]]] = None,
        stop_on_match: bool = False,
    ) -> None:
        self.matcher = matcher
        self.packages = packages
        self.stop_on_match = stop_on_match


class DependencyInstaller:
    # provide a list of OsPackageDependencies for a project
    def __init__(
        self,
        requirements: List[OsPackageDependencies],
        arch: Optional[CpuArchitecture] = None,
    ) -> None:
        self.requirements = requirements
        self._arch = arch

    # evaluate the list of package dependencies,
    def install_required_packages(
        self,
        node: Node,
        extra_args: Union[List[str], None],
        arch: Optional[CpuArchitecture] = None,
    ) -> None:
        os = node.os
        assert isinstance(os, Posix), (
            "DependencyInstaller is not compatible with this OS: "
            f"{os.information.vendor} {os.information.release}"
        )
        # find the match for an OS, install the packages.
        # stop on list end or if exclusive_match parameter is true.
        packages: List[Union[str, Tool, Type[Tool]]] = []
        for requirement in self.requirements:
            if requirement.matcher(os, arch):
                if requirement.packages is not None and len(requirement.packages) > 0:
                    packages += requirement.packages
                if requirement.stop_on_match:
                    break

        os.install_packages(packages=packages, extra_args=extra_args)

        # NOTE: It is up to the caller to raise an exception on an invalid OS
        # see unsupported_os_thrower as a catch-all 'list end' function


class Downloader:
    def __init__(self, node: Node) -> None:
        self._node = node

    def download(self) -> PurePath:
        raise NotImplementedError("Downloader not implemented.")


class GitDownloader(Downloader):
    _git_repo: str = ""
    _git_ref: str = ""

    def __init__(
        self,
        node: Node,
        git_repo: str,
        git_ref: str,
    ) -> None:
        super().__init__(node)
        self._git_repo = git_repo
        self._git_ref = git_ref

    # checkout the git repository into the working path
    def download(self) -> PurePath:
        # NOTE: fail on exists is set to True.
        # The expectation is that the parent Installer class should
        # remove any lingering installations
        self.asset_path = self._node.tools[Git].clone(
            self._git_repo,
            cwd=self._node.get_working_path(),
            ref=self._git_ref,
            fail_on_exists=False,
        )
        return self.asset_path


# parent class for tarball source installations
class TarDownloader(Downloader):
    def __init__(
        self,
        node: Node,
        tar_url: str,
    ) -> None:
        super().__init__(node)
        self._tar_url = tar_url
        self._is_remote_tarball = tar_url.startswith("https://")

    # fetch the tarball (or copy it to the node)
    # then extract it
    def download(self) -> PurePath:
        node = self._node
        work_path = self._node.get_working_path()
        is_tarball = False
        for suffix in [".tar.gz", ".tar.bz2", ".tar"]:
            if self._tar_url.endswith(suffix):
                is_tarball = True
                break
        assert_that(is_tarball).described_as(
            (
                "Source path is not a .tar[.gz|.bz2] file. "
                f"Tar url was set to: {self._tar_url} "
            )
        ).is_true()
        if self._is_remote_tarball:
            tarfile = node.tools[Wget].get(
                self._tar_url, overwrite=False, file_path=str(node.get_working_path())
            )
            remote_path = node.get_pure_path(tarfile)
            self.tar_filename = remote_path.name
        else:
            self.tar_filename = PurePath(self._tar_url).name
            remote_path = work_path.joinpath(self.tar_filename)
            node.shell.copy(
                local_path=PurePath(self._tar_url),
                node_path=remote_path,
            )
        tar_root_folder = node.tools[Tar].get_root_folder(str(remote_path))
        # create tarfile dest dir
        self.asset_path = work_path.joinpath(tar_root_folder)
        # unpack into the dest dir
        # force name as tarfile name
        # add option to skip files which already exist on disk
        # in the event we have already extracted this specific tar
        node.tools[Tar].extract(
            file=str(remote_path),
            dest_dir=str(work_path),
            gzip=True,
            skip_existing_files=True,
        )
        return self.asset_path


class Installer:
    # Generic 'Installer' parent class for DpdkTestpmd/rdma-core
    # NOTE: This should not be instantiated directly.
    _err_msg = "not implemented for this installation type."

    # setup the node before starting
    # ex: updating the kernel, enabling features, checking drivers, etc.
    # First we download the assets to ensure asset_path is set
    # even if we end up skipping re-installation
    def _setup_node(self) -> None:
        self._download_assets()

    # check if the package is already installed:
    # Is the package installed from source? Or from the package manager?
    # Does the version match the one we want if we need a specific one?
    def _check_if_installed(self) -> bool:
        raise NotImplementedError(f"_check_if_installed {self._err_msg}")

    # setup the installation (install Ninja, Meson, etc)
    def _download_assets(self) -> None:
        if self._downloader:
            self.asset_path = self._downloader.download()
        else:
            self._node.log.debug("No downloader assigned to installer.")

    # do the build and installation
    def _install(self) -> None:
        pass

    # remove an installation
    def _uninstall(self) -> None:
        raise NotImplementedError(f"_clean_previous_installation {self._err_msg}")

    # install the dependencies
    def _install_dependencies(self) -> None:
        if self._os_dependencies is not None:
            self._os_dependencies.install_required_packages(
                self._node, extra_args=self._package_manager_extra_args, arch=self._arch
            )

    # define how to check the installed version
    def get_installed_version(self) -> VersionInfo:
        raise NotImplementedError(f"get_installed_version {self._err_msg}")

    def _should_install(
        self,
        required_version: Optional[VersionInfo] = None,
        required_arch: Optional[CpuArchitecture] = None,
    ) -> bool:
        return (
            (not self._check_if_installed())
            # NOTE: Taking advantage of longer-than-expected lifetimes here.
            # If the tool still exists we ~should~ be able to check the old version
            # from a previous test environment.
            # At the moment, we use create() to force re-initialization.
            # If we ever fix things so that we use .get,
            # we will need this check. So add it now.q
            or bool(self._arch and required_arch != self._arch)
            or (
                required_version is not None
                and required_version > self.get_installed_version()
            )
        )

    # run the defined setup and installation steps.
    def do_installation(
        self,
        required_version: Optional[VersionInfo] = None,
        required_arch: Optional[CpuArchitecture] = None,
    ) -> None:
        self._setup_node()
        if self._should_install(
            required_version=required_version, required_arch=required_arch
        ):
            self._uninstall()
            self._install_dependencies()
            self._install()

    def __init__(
        self,
        node: Node,
        os_dependencies: Optional[DependencyInstaller] = None,
        downloader: Optional[Downloader] = None,
        arch: Optional[CpuArchitecture] = None,
    ) -> None:
        self._node = node
        if not isinstance(self._node.os, Posix):
            raise UnsupportedDistroException(
                self._node.os, "Installer parent class requires Posix OS."
            )
        self._os: Posix = self._node.os
        self._package_manager_extra_args: List[str] = []
        self._os_dependencies = os_dependencies
        self._downloader = downloader
        self._arch = arch
        if self._arch:
            # avoid building/running arm64 on i386, etc
            system_arch = self._node.tools[Lscpu].get_architecture()
            if system_arch not in ARCH_COMPATIBILITY_MATRIX[self._arch]:
                raise UnsupportedCpuArchitectureException(system_arch)


# Base class for package manager installation
class PackageManagerInstall(Installer):
    def __init__(
        self,
        node: Node,
        os_dependencies: DependencyInstaller,
        arch: Optional[CpuArchitecture],
    ) -> None:
        super().__init__(node, os_dependencies)

    # uninstall from the package manager
    def _uninstall(self) -> None:
        if not (isinstance(self._os, Posix) and self._check_if_installed()):
            return
        if self._os_dependencies is not None:
            for os_package_check in self._os_dependencies.requirements:
                if (
                    os_package_check.matcher(self._os, self._arch)
                    and os_package_check.packages
                ):
                    self._os.uninstall_packages(os_package_check.packages)
                    if os_package_check.stop_on_match:
                        break

    # verify packages on the node have been installed by
    # the package manager
    def _check_if_installed(self) -> bool:
        # WARNING: Don't use this for long lists of packages.
        # For dpdk, pkg-manager install is only for 'dpdk' and 'dpdk-dev'
        # This will take too long if it's more than a few packages.
        if self._os_dependencies is not None:
            for os_package_check in self._os_dependencies.requirements:
                if (
                    os_package_check.matcher(self._os, self._arch)
                    and os_package_check.packages
                ):
                    for pkg in os_package_check.packages:
                        if not self._os.package_exists(pkg):
                            return False
                    if os_package_check.stop_on_match:
                        break
        return True


# force specific default sources for arch tests (os-independent)
def force_dpdk_default_source_variables(
    variables: Dict[str, Any], build_arch: Optional[CpuArchitecture] = None
) -> None:
    if build_arch:
        variables["build_arch"] = build_arch

    if build_arch == CpuArchitecture.I386:
        if not variables.get("dpdk_branch", None):
            # assign a default branch with needed MANA commits for 32bit test
            variables["dpdk_branch"] = DPDK_32BIT_DEFAULT_BRANCH
    if not variables.get("dpdk_source", None):
        variables["dpdk_source"] = DPDK_STABLE_GIT_REPO


# force source builds for distros and environments which need a later verison.
# ie. ubuntu 18.04 and MANA
def set_default_dpdk_source(node: Node, variables: Dict[str, Any]) -> None:
    # DPDK packages 17.11 which is EOL and doesn't have the
    # net_vdev_netvsc pmd used for simple handling of hyper-v
    # guests. Force stable source build on this platform.
    # Default to 20.11 unless another version is provided by the
    # user. 20.11 is the latest dpdk version for 18.04.
    if isinstance(node.os, Ubuntu) and node.os.information.version < "20.4.0":
        variables["dpdk_source"] = variables.get("dpdk_source", DPDK_STABLE_GIT_REPO)
        variables["dpdk_branch"] = variables.get("dpdk_branch", "v20.11")
    # MANA runs need a later version of DPDK
    if node.nics.is_mana_device_present():
        variables["dpdk_source"] = variables.get("dpdk_source", DPDK_STABLE_GIT_REPO)
        variables["dpdk_branch"] = variables.get(
            "dpdk_branch", DPDK_MANA_DEFAULT_BRANCH
        )


_UBUNTU_LTS_VERSIONS = ["24.4.0", "22.4.0", "20.4.0", "18.4.0"]


# see https://ubuntu.com/about/release-cycle
def is_ubuntu_latest_or_prerelease(distro: Ubuntu) -> bool:
    return bool(distro.information.version >= max(_UBUNTU_LTS_VERSIONS))


# see https://ubuntu.com/about/release-cycle
def is_ubuntu_lts_version(distro: Ubuntu) -> bool:
    major = str(distro.information.version.major)
    minor = str(distro.information.version.minor)
    # check for major+minor version match
    return any(
        [
            major == x.split(".", maxsplit=1)[0] and minor == x.split(".")[1]
            for x in _UBUNTU_LTS_VERSIONS
        ]
    )


# check if it's a lts release outside the initial 2 year lts window
def ubuntu_needs_backports(os: Ubuntu) -> bool:
    return not is_ubuntu_latest_or_prerelease(os) and is_ubuntu_lts_version(os)


def check_dpdk_support(node: Node) -> None:
    # check requirements according to:
    # https://docs.microsoft.com/en-us/azure/virtual-network/setup-dpdk
    supported = False
    arch = node.tools[Lscpu].get_architecture()
    if arch == CpuArchitecture.ARM64 and not isinstance(node.os, Ubuntu):
        raise UnsupportedDistroException(
            node.os, "ARM64 tests are only supported on Ubuntu + failsafe."
        )
    if isinstance(node.os, Debian):
        if isinstance(node.os, Ubuntu):
            node.log.debug(
                "Checking Ubuntu release: "
                f"is_latest_or_prerelease? ({is_ubuntu_latest_or_prerelease(node.os)})"
                f" is_lts_version? ({is_ubuntu_lts_version(node.os)})"
            )
            # TODO: undo special casing for 18.04 when it's usage is less common
            supported = (
                node.os.information.version == "18.4.0"
                or is_ubuntu_latest_or_prerelease(node.os)
                or is_ubuntu_lts_version(node.os)
            )
        else:
            supported = node.os.information.version >= "11.0.0"
    elif isinstance(node.os, Fedora) and not isinstance(node.os, Oracle):
        supported = node.os.information.version >= "7.5.0"
    elif isinstance(node.os, Suse):
        supported = node.os.information.version >= "15.0.0"
    else:
        # this OS is not supported
        raise UnsupportedDistroException(
            node.os, "This OS is not supported by the DPDK test suite for Azure."
        )
    # verify MANA driver is available for the kernel version
    if (
        isinstance(node.os, (Debian, Fedora, Suse, Fedora))
        and node.nics.is_mana_device_present()
    ):
        # NOTE: Kernel backport examples are available for lower kernels.
        # HOWEVER: these are not suitable for general testing and should be installed
        # in the image _before_ starting the test.
        # ex: make a SIG image first using the kernel build transformer.
        if node.os.get_kernel_information().version < "5.15.0":
            raise UnsupportedDistroException(
                node.os, "MANA driver is not available for kernel < 5.15"
            )
    if not supported:
        raise UnsupportedDistroException(
            node.os, "This OS version is EOL and is not supported for DPDK on Azure"
        )


def is_url_for_tarball(url: str) -> bool:
    # fetch the resource from the url
    # ex. get example/thing.tar from www.github.com/example/thing.tar.gz
    url_path = urlparse(url).path
    if not url_path:
        return False
    suffixes = PurePath(url_path).suffixes
    if not suffixes:
        return False
    # check if '.tar' in [ '.tar', '.gz' ]
    return ".tar" in suffixes


def is_url_for_git_repo(url: str) -> bool:
    parsed_url = parse_url(url)
    scheme = parsed_url.scheme
    path = parsed_url.path
    if not (scheme and path):
        return False
    # investigate the rest of the URL as a path
    path_check = PurePath(path)
    check_for_git_https = scheme in ["http", "https"] and (
        path_check.suffixes == [".git"]
        or any([x in path_check.parts for x in ["git", "_git"]])
    )
    return scheme == "git" or check_for_git_https


# utility matcher to throw an OS error type for a match.
def unsupported_os_thrower(os: Posix, arch: Optional[CpuArchitecture]) -> bool:
    if arch:
        message_suffix = f"OS and Architecture ({arch})"
    else:
        message_suffix = "OS"
    raise UnsupportedDistroException(
        os,
        message=f"Installer did not define dependencies for this {message_suffix}",
    )


# utility matcher to throw an OS error when i386 is not supported
def i386_not_implemented_thrower(os: Posix, arch: Optional[CpuArchitecture]) -> bool:
    if arch and arch == CpuArchitecture.I386:
        raise NotImplementedError(
            "i386 is not implemented for this (installer,OS) combo."
        )
    return False


def get_debian_backport_repo_args(os: Debian) -> List[str]:
    # ex: 'bionic-backports' or 'buster-backports'
    # these backport repos are available for the older OS's
    # and include backported fixes which need to be opted into.
    # So filter out recent OS's and
    # add the backports repo for older ones, if it should be available.
    if not isinstance(os, Debian):
        return []
    # don't enable backport args for releases which don't need/have them.
    if isinstance(os, Ubuntu) and not ubuntu_needs_backports(os):
        return []
    repos = os.get_repositories()
    backport_repo = f"{os.information.codename}-backports"
    if any([backport_repo in repo.name for repo in repos]):
        return [f"-t {backport_repo}"]
    return []


# NOTE: mana_ib was added in 6.2 and backported to 5.15
# this ends up lining up with kernels that need to be updated before
# starting our DPDK tests. This function is not meant for general use
# outside of the DPDK suite.
def update_kernel_from_repo(node: Node) -> None:
    assert isinstance(
        node.os, (Debian, Fedora, Suse)
    ), f"DPDK test does not support OS type: {type(node.os)}"
    if (
        isinstance(node.os, Debian)
        and node.os.get_kernel_information().version < "6.5.0"
    ):
        package = "linux-azure"
    elif (
        isinstance(node.os, (Fedora, Suse))
        and node.os.get_kernel_information().version < "5.15.0"
    ):
        package = "kernel"
    else:
        return
    if node.os.is_package_in_repo(package):
        node.os.install_packages(package)
        node.reboot()
    else:
        node.log.debug(f"Kernel update package '{package}' was not found.")
