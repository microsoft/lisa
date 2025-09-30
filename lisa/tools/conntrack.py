from lisa.executable import Tool
from lisa.util import LisaException


class Conntrack(Tool):
    @property
    def command(self) -> str:
        return "conntrack"

    @property
    def can_install(self) -> bool:
        return True
    
    def install(self) -> bool:
        self.node.os.install_packages("conntrack")
        return self._check_exists()
    
    def create_entry(
        self,
        src_ip: str = "10.0.0.0",
        dst_ip: str = "10.0.0.1",
        protonum: int = 6,
        timeout: int = 0,
        mark: str = ""
    ) -> None:

        cmd = f"-I -s {src_ip} -d {dst_ip} --protonum {str(protonum)}"

        if timeout > 0:
            cmd += f" --timeout {str(timeout)}"
        if mark:
            cmd += f" --mark {mark}"
        
        result = self.run(
            cmd, 
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"Failed to create conntrack entry from {src_ip} to {dst_ip} with mark {mark}"
        )


    def update_entry(
        self, 
        mark: str = ""
    ) -> None:
        
        cmd = "-U"

        if mark:
            cmd += f" --mark {mark}"
        
        result = self.run(
            cmd, 
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"Failed to update conntrack entry with mark {mark}"
        )