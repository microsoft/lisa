from lisa.executable import Tool


class YumConfigManager(Tool):
    @property
    def command(self) -> str:
        return "yum-config-manager"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        package_name = "yum-utils"
        self.node.os.install_packages(package_name)  # type: ignore
        return self._check_exists()

    def add_repository(
        self,
        repo: str,
        no_gpgcheck: bool = True,
    ) -> None:
        cmd = f'{self.command} --add-repo "{repo}"'
        if no_gpgcheck:
            cmd += " --nogpgcheck"
        self.node.execute(
            cmd=cmd,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to add repository",
        )

    def set_opt(
        self,
        opts: str,
    ) -> None:
        self.run(
            f"--save --setopt={opts}",
            sudo=True,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"fail to set opts {opts}",
        )
