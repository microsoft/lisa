from dataclasses import dataclass


@dataclass
class NodeContext:
    vm_name: str = ""
    vhd_local_path: str = ""  # Local path on the machine where LISA is running
    vhd_remote_path: str = ""  # Path on the hyperv server
