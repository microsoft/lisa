from lisa.base_tools import Service 
from lisa.executable import Tool
from lisa.util import LisaException


class Ipset(Tool):
    @property
    def command(self) -> str:
        return "ipset"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        self.node.os.install_packages("ipset")
        return self._check_exists()

    def create_ipset(
        self,
        set_name: str,
        set_type: str = "ip"
    ) -> None:
        
        cmd = f"create {set_name} hash:{set_type}"

        self.run(
            cmd,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"Failed to create ipset {set_name}",
        )
    
    def add_ip(
        self,
        set_name: str,
        ip_address: str
    ) -> None:
        
        cmd = f"add {set_name} {ip_address}"

        self.run(
            cmd,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"Failed to add ip {ip_address} to ipset {set_name}"
        )