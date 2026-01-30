import json
import os
import time
from datetime import datetime
from dataclasses import dataclass, field
from dataclasses_json import dataclass_json
from pathlib import PurePath
from typing import Dict, Any, Optional, List, Type, cast

from lisa import schema
from lisa.tools import Echo, Git
from lisa.util import subclasses, parse_version

# from lisa.transformer import Transformer
from .deployment_transformer import (
    DeploymentTransformer,
    DeploymentTransformerSchema,
)
from .kernel_source_installer import (
    BaseLocation,
    BaseLocationSchema,
    SourceInstaller,
    SourceInstallerSchema,
    RepoLocation,
    RepoLocationSchema,
    _get_code_path,
)


@dataclass_json()
@dataclass
class RepoWorktreeSchema(RepoLocationSchema):
    worktree_name: str = ""
    worktree_repo: str = ""
    worktree_ref: str = ""
    worktree_local_branch: str = ""


@dataclass_json()
@dataclass
class KernelSourcePackagerSchema(DeploymentTransformerSchema, SourceInstallerSchema):
    use_cache: bool = field(default=False)
    cache_destination: str = field(default="/default", metadata={"required": False})


class KernelSourcePackager(DeploymentTransformer):
    _package_dir = "package_dir"
    _packages = "packages"

    @classmethod
    def type_name(cls) -> str:
        return "kernel_source_packager"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return KernelSourcePackagerSchema

    @property
    def _output_names(self) -> List[str]:
        return [
            self._package_dir,
            self._packages,
        ]

    def _information(self, package_dir: str, package_paths: str) -> Dict[str, Any]:
        image: bool = False
        headers: bool = False
        libc_dev: bool = False
        packages: List[str] = []
        for package_name in package_paths:
            if not package_name.endswith(".deb"):
                continue
            if "linux-image" in package_name:
                if "dbg" not in package_name:
                    image = True
                packages.append(PurePath(package_name).name)
            elif "linux-headers" in package_name:
                headers = True
                packages.append(PurePath(package_name).name)
            elif "libc-dev" in package_name:
                libc_dev = True
                packages.append(PurePath(package_name).name)

        return {
            "necessary_packages_exist": image and headers and libc_dev,
            "directory": package_dir,
            "packages": packages,
        }

    def _internal_run(self) -> Dict[str, Any]:
        runbook: KernelSourcePackagerSchema = self.runbook
        results: Dict[str, Any] = dict()
        assert runbook.location, "the repo must be defined"
        self._log.info(
            f"use_cache value: {runbook.use_cache} "
            f"(type: {type(runbook.use_cache)})"
        )
        node = self._node

        # Use SourceInstaller logic for build steps
        source_installer_runbook = SourceInstallerSchema(
            location=runbook.location,
            modifier=runbook.modifier,
            kernel_config_file=runbook.kernel_config_file,
        )
        source_installer = SourceInstaller(
            runbook=source_installer_runbook,
            node=node,
            parent_log=self._log,
        )

        source_installer._install_build_tools(node)

        # 1. Clone and checkout the source to get the actual commit_id and kernel_version
        factory = subclasses.Factory[BaseLocation](BaseLocation)
        source = factory.create_by_runbook(
            runbook=runbook.location, node=node, parent_log=self._log
        )
        self._code_path = source.get_source_code()
        assert node.shell.exists(
            self._code_path
        ), f"cannot find code path: {self._code_path}"
        self._log.info(f"kernel code path: {self._code_path}")

        # modify code
        source_installer._modify_code(node=node, code_path=self._code_path)

        git = self._node.tools["Git"]
        commit_id = git.get_latest_commit_id(cwd=self._code_path)

        # 2. Get kernel version
        result = node.execute(
            "make kernelversion 2>/dev/null", cwd=self._code_path, shell=True
        )
        result.assert_exit_code(0, f"failed on get kernel version: {result.stdout}")
        kernel_version = parse_version(result.stdout)

        ret = None
        if runbook.use_cache:
            self._log.info("Checking for cached kernel packages...")
            if self._check_cache(commit_id, kernel_version):
                self._log.info("Cache hit: using cached package.")
                ret = self._update_cache(commit_id=commit_id)
            else:
                self._log.info("Cache miss: building and packaging kernel.")
                ret = self._build_and_package(
                    source_installer, commit_id, kernel_version
                )
        else:
            self._log.info("No-cache mode: building and packaging kernel.")
            ret = self._build_and_package(source_installer, commit_id, kernel_version)

        if ret is None:
            raise Exception("No images retrieved. kernel_source_packager_error")
        if ret["necessary_packages_exist"]:
            cache_dir: str = ret["directory"]
            package_names: List[str] = ret["packages"]
            results = {
                self._package_dir: cache_dir,
                self._packages: package_names,
            }
        else:
            results = {}

        return results

    def _check_cache(
        self, commit_id: str, kernel_version: str, cache_json_path: str = ""
    ) -> bool:
        """
        Checks the cache JSON for an entry matching the given commit_id and kernel_version.
        If found, verifies that the package_path exists and contains a .deb file.
        Returns True if valid .deb package is present, else False.
        """
        node = self._node
        runbook: KernelSourcePackagerSchema = self.runbook
        if len(cache_json_path) == 0:
            cache_json_path = f"{runbook.cache_destination}/cache/kernel_cache.json"

        try:
            cache_content = node.execute(f"cat {cache_json_path}", shell=True)
            cache = json.loads(cache_content.stdout)
        except Exception as e:
            self._log.error(f"Failed to load cache: {e}")
            cache = []

        for entry in cache:
            if (
                entry.get("commit_id") == commit_id
                and entry.get("kernel_version") == kernel_version
                and entry.get("package_type") == "deb"
            ):
                package_paths = entry.get("package_paths")
                if not package_paths or not isinstance(package_paths, list):
                    return False
                # Check that at least one .deb file exists
                for package_path in package_paths:
                    if (
                        package_path.endswith(".deb")
                        and node.execute(
                            f"test -f {package_path}", shell=True
                        ).exit_code
                        == 0
                    ):
                        return True
                return False
        return False

    def _update_cache(
        self,
        cache_json_path: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        commit_id: Optional[str] = None,
        max_cache_size: int = 100,
    ) -> Optional[Dict[str, Any]]:
        """
        Updates the kernel cache JSON file.
        1. If metadata is provided, creates a new entry at the top (removes last if full).
        2. If only commit_id is provided, moves the entry to the top and updates last_used_time.
        Returns the package_paths of the updated or created entry, or None if not found.
        """
        node = self._node
        runbook: KernelSourcePackagerSchema = self.runbook
        if len(cache_json_path) == 0:
            cache_json_path = f"{runbook.cache_destination}/cache/kernel_cache.json"
        now = datetime.utcnow().isoformat() + "Z"
        # Load cache
        try:
            if node.shell.exists(PurePath(cache_json_path)):
                cache_content = node.execute(f"cat {cache_json_path}", shell=True)
                cache: List[Dict[str, Any]] = json.loads(cache_content.stdout)
            else:
                cache = []
        except Exception as e:
            self._log.error(f"Failed to load cache: {e}")
            cache = []

        updated = False
        package_paths = None

        if metadata:
            # Remove any existing entry with the same commit_id
            commit_id = metadata.get("commit_id")
            cache = [entry for entry in cache if entry.get("commit_id") != commit_id]
            # Set last_used_time
            metadata["last_used_time"] = now
            # Insert new entry at the top
            cache.insert(0, metadata)
            package_paths = metadata.get("package_paths")
            # Trim cache if over max size
            if len(cache) > max_cache_size:
                removed = cache.pop()
                self._log.info(
                    "Cache full. Removed oldest entry: "
                    f"{removed.get('commit_id', 'unknown')}"
                )
            self._log.info("Created new entry in cache.")
            updated = True

        elif commit_id:
            for idx, entry in enumerate(cache):
                if entry.get("commit_id") == commit_id:
                    entry["last_used_time"] = now
                    # Move entry to top
                    cache.pop(idx)
                    cache.insert(0, entry)
                    package_paths = entry.get("package_paths")
                    self._log.info("Updated last used time for cache entry.")
                    updated = True
                    break
            if not updated:
                self._log.warning(f"No cache entry found for commit_id: {commit_id}")

        # Save cache if updated
        if updated:
            try:
                cache_str = json.dumps(cache, indent=2)
                node.execute(
                    f"echo '{cache_str}' | sudo tee {cache_json_path}", shell=True
                )
            except Exception as e:
                self._log.error(f"Failed to write cache: {e}")

        # Find the main kernel image .deb (not headers or dbg)
        if not package_paths:
            raise Exception(
                f"No package_paths found in cache for the given commit_id-{commit_id}."
            )

        return self._information(
            f"{runbook.cache_destination}/cache/packages/commit_id-{commit_id}",
            package_paths,
        )

    def _build_and_package(
        self, source_installer, commit_id: str, kernel_version: str
    ) -> Optional[Dict[str, Any]]:
        """
        Builds the kernel from source (using already cloned and checked-out code),
        creates a deb package, collects metadata, moves the package to a commit-id-named folder,
        updates the cache, and returns the first package path.
        """
        node = self._node
        runbook: KernelSourcePackagerSchema = self.runbook

        # 1. Build tools already installed

        # 2. Use the already set self._code_path (repo is already cloned and checked out)
        assert node.shell.exists(
            self._code_path
        ), f"cannot find code path: {self._code_path}"
        self._log.info(f"kernel code path: {self._code_path}")

        # 2.5. Branch verification: ensure correct branch is checked out
        expected_branch = getattr(runbook, "ref", None)
        if expected_branch:
            git = node.tools["Git"]
            current_branch = git.get_current_branch(cwd=self._code_path)
            if current_branch != expected_branch:
                raise Exception(
                    f"Kernel source is on branch '{current_branch}', expected "
                    f"'{expected_branch}'."
                )
            self._log.info(f"Verified kernel source is on branch '{current_branch}'.")

        # 3. Build the kernel (reuse SourceInstaller, but do NOT install)
        source_installer._build_code(
            node=node,
            code_path=self._code_path,
            kconfig_file=runbook.kernel_config_file,
            kernel_version=kernel_version,
            use_ccache=True,
        )

        start_time = time.time()
        # 4. Package the kernel as a DEB package
        make = node.tools["Make"]
        make.make(arguments="bindeb-pkg", cwd=self._code_path, timeout=60 * 60 * 2)

        # 5. Find the generated .deb package(s)
        deb_dir = self._code_path.parent
        result = node.execute(
            f"find {str(deb_dir)} -maxdepth 1 -type f"
            f" -newermt @{int(start_time)} -printf '%f\n'"
        )

        if result.exit_code != 0:
            raise Exception(f"Failed to list .deb files in {deb_dir}: {result.stderr}")
        deb_files = [
            os.path.basename(line.strip()) for line in result.stdout.splitlines()
        ]

        if not deb_files:
            raise Exception(
                "No .deb package was generated in the kernel build process."
            )

        # 6. Move the .deb file(s) to the cache/packages/<commit_id> directory
        cache_root = f"{runbook.cache_destination}/cache"
        packages_dir = f"{cache_root}/packages"
        commit_dir = f"{packages_dir}/commit_id-{commit_id}"
        if not node.shell.exists(PurePath(commit_dir)):
            node.execute(f"sudo mkdir -p {commit_dir}", shell=True)
            node.execute(f"sudo chmod 777 {commit_dir}", shell=True)

        package_paths = []
        for deb_file in deb_files:
            src_path = f"{deb_dir}/{deb_file}"
            dest_path = f"{commit_dir}/{deb_file}"
            node.execute(f"sudo mv {src_path} {dest_path}", shell=True)
            package_paths.append(dest_path)

        # 7. Collect metadata for cache
        metadata = {
            "commit_id": commit_id,
            "kernel_version": kernel_version,
            "package_type": "deb",
            "package_paths": package_paths,  # Store all .deb paths as a list
            "build_time": datetime.utcnow().isoformat() + "Z",
            "builder_vm": node.name if hasattr(node, "name") else "unknown",
            "os_distribution": str(node.os),
            # "last_used_time" will be set by _update_cache
        }

        # 8. Update the cache and return the first package path
        return self._update_cache(metadata=metadata)


class RepoWorktree(BaseLocation):
    @classmethod
    def type_name(cls) -> str:
        return "worktree"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return RepoWorktreeSchema

    def get_source_code(self) -> PurePath:
        runbook: RepoWorktreeSchema = cast(RepoWorktreeSchema, self.runbook)

        code_path = _get_code_path(runbook.path, self._node, "repo_code")

        # expand env variables
        echo = self._node.tools[Echo]
        git = self._node.tools[Git]

        echo_result = echo.run(str(code_path), shell=True)
        code_path = self._node.get_pure_path(echo_result.stdout)

        if not self._node.shell.exists(code_path):
            self._log.debug(f"creating dir: {code_path}")
            self._node.execute(f"mkdir -p {code_path}", sudo=True)
            self._node.execute(f"chmod 0777 {code_path}", sudo=True)

        repo_name = os.path.basename(runbook.repo.rstrip("/")).removesuffix(".git")
        if not self._node.shell.exists(code_path / repo_name):
            self._log.info(f"cloning code from {runbook.repo} to {code_path}...")
            code_path = git.clone(
                url=runbook.repo,
                cwd=code_path,
                fail_on_exists=runbook.fail_on_code_exists,
                auth_token=runbook.auth_token,
                timeout=1800,
            )
        else:
            code_path = code_path / repo_name

        # check if the 'repo' is already a remote url
        remote_exists = False
        remote = ""
        remotes = git.remote_list(code_path)
        self._log.debug(f"existing remotes: {remotes}")
        for remote in remotes:
            if runbook.worktree_repo == git.remote_get_url(code_path, remote):
                remote_exists = True
                break

        if not remote_exists:
            remote = runbook.worktree_name
            self._log.info(f"adding remote {remote} for {runbook.worktree_repo}")
            git.remote_add(cwd=code_path, name=remote, url=runbook.worktree_repo)
        git.fetch(
            cwd=code_path,
            remote=remote,
        )

        target_path = code_path
        target_ref = runbook.ref
        if runbook.worktree_name:
            worktree_path = code_path.parent / runbook.worktree_name
            git.worktree_prune(cwd=code_path)
            if not git.worktree_exists(cwd=code_path, path=str(worktree_path)):
                self._log.info(
                    f"creating a new worktree at {worktree_path} "
                    f"pointing at {remote}/{runbook.worktree_ref}"
                )
                git.worktree_add(
                    cwd=code_path,
                    path=worktree_path,
                    remote=remote,
                    remote_ref=runbook.worktree_ref,
                    new_branch=runbook.worktree_local_branch,
                    track=True,
                )

                latest_commit_id = git.get_latest_commit_id(cwd=worktree_path)
                self._log.info(f"Kernel HEAD is now at : {latest_commit_id}")
                return worktree_path

            # worktree exists
            target_ref = runbook.worktree_ref
            target_path = worktree_path

        if target_ref:
            if git.get_current_branch(cwd=target_path) == target_ref:
                git.pull(cwd=target_path)

            git.checkout(ref=target_ref, cwd=target_path)
            self._log.info(f"checkout code from: '{target_ref}'")

        latest_commit_id = git.get_latest_commit_id(cwd=target_path)
        self._log.info(f"Kernel HEAD is now at : {latest_commit_id}")

        return target_path
