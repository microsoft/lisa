from pathlib import Path
from typing import Optional

from lisa import TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.environment import EnvironmentStatus
from lisa.features import SerialConsole
from lisa.testsuite import simple_requirement
from lisa.util import LisaException, PassedException
from lisa.util.perf_timer import create_timer
from lisa.util.shell import wait_tcp_port_ready


@TestSuiteMetadata(
    area="provisioning",
    category="functional",
    description="""
    This test suite uses to test an environment provisioning correct or not.
    """,
    tags=[],
)
class Provisioning(TestSuite):
    TIME_OUT = 300

    @TestCaseMetadata(
        description="""
        This test try to connect to ssh port to check if a node is healthy.
        If ssh connected, the node is healthy enough. And check if it's healthy after
        reboot. Even not eable to reboot, it's passed with a warning.
        If the node can be rebooted, but there is panic detected, or not be able to
        connected. The case failed.
        """,
        priority=0,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Deployed,
            supported_features=[SerialConsole],
        ),
    )
    def smoke_test(self, case_name: str) -> None:
        node = self.environment.default_node
        case_path: Optional[Path] = None

        is_ready, tcp_error_code = wait_tcp_port_ready(
            node.public_address, node.public_port, log=self.log, timeout=self.TIME_OUT
        )
        if not is_ready:
            serial_console = node.features[SerialConsole]
            case_path = self._create_case_log_path(case_name)
            serial_console.check_panic(saved_path=case_path, stage="bootup")
            raise LisaException(
                f"cannot connect to [{node.public_address}:{node.public_port}], "
                f"error code: {tcp_error_code}, no panic found in serial log"
            )

        try:
            timer = create_timer()
            self.log.info(f"restarting {node.name}")
            node.reboot()
            self.log.info(f"node {node.name} rebooted in {timer}")
        except Exception as identifier:
            if not case_path:
                case_path = self._create_case_log_path(case_name)
            serial_console = node.features[SerialConsole]
            # if there is any panic, fail before parial passed
            serial_console.check_panic(saved_path=case_path, stage="reboot")

            # if node cannot be connected after reboot, it should be failed.
            if isinstance(identifier, LisaException) and str(identifier).startswith(
                "cannot connect to TCP port"
            ):
                raise LisaException(f"after reboot, {identifier}")
            raise PassedException(identifier)
