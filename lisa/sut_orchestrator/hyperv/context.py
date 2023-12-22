from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath


@dataclass
class NodeContext:
    vm_name: str = ""
    vhd_local_path = PurePosixPath()  # Local path on the machine where LISA is running
    vhd_remote_path = PureWindowsPath()  # Path on the hyperv server
