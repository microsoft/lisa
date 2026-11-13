# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import base64
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, cast

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.tools import Kill
from lisa.util import LisaException

# Subset of HV_STATUS_* values from include/hyperv/hvgdk_mini.h, used only to
# make reports readable. Unknown values are still reported by their hex code.
HV_STATUS_NAMES: Dict[int, str] = {
    0x2: "HV_STATUS_INVALID_HYPERCALL_CODE",
    0x3: "HV_STATUS_INVALID_HYPERCALL_INPUT",
    0x4: "HV_STATUS_INVALID_ALIGNMENT",
    0x5: "HV_STATUS_INVALID_PARAMETER",
    0x6: "HV_STATUS_ACCESS_DENIED",
    0x7: "HV_STATUS_INVALID_PARTITION_STATE",
    0x8: "HV_STATUS_OPERATION_DENIED",
    0x9: "HV_STATUS_UNKNOWN_PROPERTY",
    0xA: "HV_STATUS_PROPERTY_VALUE_OUT_OF_RANGE",
    0xB: "HV_STATUS_INSUFFICIENT_MEMORY",
    0xD: "HV_STATUS_INVALID_PARTITION_ID",
    0xE: "HV_STATUS_INVALID_VP_INDEX",
    0x10: "HV_STATUS_NOT_FOUND",
    0x11: "HV_STATUS_INVALID_PORT_ID",
    0x12: "HV_STATUS_INVALID_CONNECTION_ID",
    0x13: "HV_STATUS_INSUFFICIENT_BUFFERS",
    0x14: "HV_STATUS_NOT_ACKNOWLEDGED",
    0x15: "HV_STATUS_INVALID_VP_STATE",
    0x1D: "HV_STATUS_NO_RESOURCES",
    0x20: "HV_STATUS_PROCESSOR_FEATURE_NOT_SUPPORTED",
    0x41: "HV_STATUS_INVALID_LP_INDEX",
    0x50: "HV_STATUS_INVALID_REGISTER_VALUE",
    0x71: "HV_STATUS_OPERATION_FAILED",
    0x78: "HV_STATUS_TIME_OUT",
    0x79: "HV_STATUS_CALL_PENDING",
}


@dataclass
class HypercallTraceSession:
    pid: str
    script_path: str
    output_path: str
    stderr_path: str
    probes: List[str] = field(default_factory=list)


@dataclass
class HypercallTraceResult:
    # Raw hypervisor status codes seen in hv_result_to_errno(), e.g.
    # "0x000b(HV_STATUS_INSUFFICIENT_MEMORY)" -> hit count.
    hv_status: Dict[str, int] = field(default_factory=dict)
    # Failing return values from hv_call_* wrappers (non-zero) and mshv ioctl
    # handlers (negative errno), e.g. "hv_call_create_vp=-12" -> hit count.
    call_errors: Dict[str, int] = field(default_factory=dict)


class Bpftrace(Tool):
    # hv_do_hypercall() is inline, so it cannot be probed. All failing
    # hypercalls in the mshv root driver funnel the raw HV status through
    # hv_result_to_errno(), which is the closest hook to the real hypercall
    # return code.
    _STATUS_PROBE = "kprobe:hv_result_to_errno"
    # Return probes grouped by return convention.
    _RET_PROBE_GROUPS = [
        # hv_call_* return 0 on success or a negative errno.
        ("kprobe:hv_call_*", "(int32)retval != 0"),
        # mshv ioctl handlers return a negative errno on failure.
        ("kprobe:mshv_*ioctl*", "(int32)retval < 0"),
    ]

    # @hv_status[11]: 3
    # @call_err[kretprobe:hv_call_create_vp, -12]: 1
    _MAP_LINE = re.compile(r"^@(?P<map>\w+)\[(?P<key>.+)\]:\s*(?P<count>\d+)\s*$")

    @property
    def command(self) -> str:
        return "bpftrace"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("bpftrace")
        return self._check_exists()

    def list_probes(self, pattern: str) -> List[str]:
        result = self.run(
            f"-l '{pattern}'",
            shell=True,
            sudo=True,
            force_run=True,
            no_error_log=True,
        )
        return sorted(
            {
                line.strip()
                for line in result.stdout.splitlines()
                if line.strip().startswith("kprobe:")
            }
        )

    def build_hypercall_script(self, cgroup_path: str = "") -> str:
        # Probes fire system-wide, when a cgroup is given, only events from
        # tasks in that cgroup are counted.
        scope = f'cgroup == cgroupid("{cgroup_path}")' if cgroup_path else ""
        lines: List[str] = []
        if self.list_probes(self._STATUS_PROBE):
            status_filter = f" /{scope}/" if scope else ""
            lines.append(
                f"{self._STATUS_PROBE}{status_filter} "
                "{ @hv_status[arg0 & 0xffff] = count(); }"
            )
        for pattern, predicate in self._RET_PROBE_GROUPS:
            ret_probes = [
                probe.replace("kprobe:", "kretprobe:", 1)
                for probe in self.list_probes(pattern)
            ]
            if ret_probes:
                ret_filter = f"{scope} && ({predicate})" if scope else predicate
                lines.append(
                    ",\n".join(ret_probes)
                    + f" /{ret_filter}/ "
                    + "{ @call_err[probe, (int32)retval] = count(); }"
                )
        if not lines:
            raise LisaException(
                "none of the mshv/hv_call kprobes are available on this kernel"
            )
        return "\n".join(lines) + "\n"

    def start_hypercall_trace(
        self,
        work_dir: str,
        tag: str,
        attach_timeout: int = 60,
        cgroup_path: str = "",
    ) -> HypercallTraceSession:
        script = self.build_hypercall_script(cgroup_path)
        script_path = f"{work_dir}/{tag}.bt"
        output_path = f"{work_dir}/{tag}.out"
        stderr_path = f"{work_dir}/{tag}.err"
        encoded = base64.b64encode(script.encode()).decode()
        self.node.execute(
            f"echo {encoded} | base64 -d > {script_path} && "
            f": > {output_path} && : > {stderr_path}",
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="failed to prepare bpftrace session",
        )
        result = self.node.execute(
            f"nohup {self.command} -o {output_path} {script_path} "
            f"< /dev/null > {stderr_path} 2>&1 & echo $!",
            shell=True,
            sudo=True,
            expected_exit_code=0,
        )
        pid = result.stdout.strip().splitlines()[-1].strip()
        session = HypercallTraceSession(
            pid=pid,
            script_path=script_path,
            output_path=output_path,
            stderr_path=stderr_path,
            probes=[line for line in script.splitlines() if line.strip()],
        )

        # bpftrace prints "Attaching N probes..." once probes are live, only
        # then is it safe to start the workload.
        deadline = time.time() + attach_timeout
        while time.time() < deadline:
            status = self._read(stderr_path) + self._read(output_path)
            if "Attaching" in status:
                return session
            if not self._is_alive(pid):
                raise LisaException(f"bpftrace exited before attaching: {status}")
            time.sleep(1)
        self.stop_hypercall_trace(session)
        raise LisaException("bpftrace did not attach probes in time")

    def stop_hypercall_trace(
        self, session: HypercallTraceSession, timeout: int = 60
    ) -> HypercallTraceResult:
        if not self._is_alive(session.pid):
            raise LisaException(
                "bpftrace exited before the trace was stopped: "
                f"{self._read(session.stderr_path).strip()}"
            )
        self.node.tools[Kill].by_pid(session.pid, signum=2, ignore_not_exist=True)
        deadline = time.time() + timeout
        while time.time() < deadline and self._is_alive(session.pid):
            time.sleep(1)
        if self._is_alive(session.pid):
            self.node.tools[Kill].by_pid(session.pid, ignore_not_exist=True)
            raise LisaException(
                f"bpftrace did not exit within {timeout}s of SIGINT and was "
                "killed, trace output is incomplete"
            )
        return self.parse_output(self._read(session.output_path))

    @classmethod
    def parse_output(cls, output: str) -> HypercallTraceResult:
        result = HypercallTraceResult()
        for line in output.splitlines():
            match = cls._MAP_LINE.match(line.strip())
            if not match:
                continue
            count = int(match.group("count"))
            key = match.group("key")
            if match.group("map") == "hv_status":
                code = int(key, 0)
                name = HV_STATUS_NAMES.get(code, "")
                label = f"0x{code:04x}" + (f"({name})" if name else "")
                result.hv_status[label] = result.hv_status.get(label, 0) + count
            elif match.group("map") == "call_err":
                probe, _, retval = key.rpartition(",")
                func = probe.strip().split(":", 1)[-1]
                label = f"{func}={retval.strip()}"
                result.call_errors[label] = result.call_errors.get(label, 0) + count
        return result

    def _is_alive(self, pid: str) -> bool:
        return (
            self.node.execute(f"kill -0 {pid}", sudo=True, no_error_log=True).exit_code
            == 0
        )

    def _read(self, path: str) -> str:
        return self.node.execute(
            f"cat {path}", sudo=True, shell=True, no_error_log=True
        ).stdout
