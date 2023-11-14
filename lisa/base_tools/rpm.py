from typing import cast

from lisa.executable import Tool


class Rpm(Tool):
    @property
    def command(self) -> str:
        return "rpm"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        from lisa.operating_system import Posix

        posix_os: Posix = cast(Posix, self.node.os)
        package_name = "rpm"
        posix_os.install_packages(package_name)
        return self._check_exists()

    def is_valid_package(self, file: str) -> bool:
        cmd_result = self.run(
            f'-qp "{file}"',
        )
        return cmd_result.exit_code == 0

    def get_file_size(self, file: str) -> int:
        cmd_result = self.run(
            "--queryformat='%{SIZE}' " f"-qp {file}",
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(f"fail to get size of file {file}"),
        )
        return int(cmd_result.stdout)

    def install_local_package(
        self, file: str, force: bool = False, nodeps: bool = False
    ) -> None:
        parameters = f'-ivh "{file}"'
        if force:
            parameters += " --force"
        if nodeps:
            parameters += " --nodeps"
        self.run(
            parameters,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(f"failed to install {file}"),
        )
