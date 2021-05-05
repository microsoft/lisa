from assertpy import assert_that  # type: ignore

from pathlib import Path
import time

from lisa import Environment, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.executable import CustomScript, CustomScriptBuilder
from lisa.testsuite import simple_requirement
from lisa.operating_system import Windows
from lisa.util.perf_timer import create_timer


# TODO: move to microsoft test suite folder
# TODO: hoping eventually there is a node.nics list to get these from rather than hardcoding
NIC_NAMES = ["eth0", "eth1", "eth2"]

# TODO: check kernel version with uname -r and kernel config


@TestSuiteMetadata(
    area="xdp",
    category="functional",
    description="""
    This test suite run XDP Testcases.
    """,
    requirement=simple_requirement(unsupported_os=[Windows]),
)
class xdpdump(TestSuite):
    xdpdump_prefix = "xdpdumpOut"
    ping_prefix = "pingOut"
    nodes_nics_ips = dict()

    def before_suite(self, **kwargs) -> None:
        # Upload scripts required by testsuite
        self._xdp_script = CustomScriptBuilder(
            Path(__file__).parent.joinpath("scripts"),
            [
                "xdpdumpsetup.sh",
                "xdputils.sh",
                "utils.sh",
                "enable_passwordless_root.sh",
                "enable_root.sh",
                "XDP-Action.sh",
                "XDP-MTUVerify.sh",
            ],
            command="sudo",
        )

    # TODO: most logging should be debug level
    @TestCaseMetadata(
        description="""
        this test case run tests if xdp program load and unloads correctly.
        """,
        priority=1,  # TODO: add 1 to each test priority, determine appropriate priority
        requirement=simple_requirement(
            min_nic_count=2
        ),  # TODO: windows unsupported add to each test case
    )
    def verify_xdp_compliance(self, environment: Environment, node: Node) -> None:
        script: CustomScript = node.tools[self._xdp_script]
        # Get Extra NIC name

        self.setup_xdpdump(environment, [node])

        # TODO: Download remote log files
        self.log.info(node.execute("ls -la", cwd=script.get_tool_path()).stdout)
        state = node.execute("cat state.txt", cwd=script.get_tool_path())
        self.log.info(f"Final state after test execution:{state.stdout}")

        # self.log.info("Check result")
        # # TODO: Handle Skip test result
        # assert_that(state.stdout).is_equal_to("TestCompleted")
        # assert_that(
        #     result.exit_code, "xdpdumpsetup.sh script exit code should be 0"
        # ).is_zero()  # TODO: description decl

    @TestCaseMetadata(
        description="""
        Test verifies xdp is working with SRIOV-enabled NIC and synthetic NIC
        """,
        priority=1,
        requirement=simple_requirement(min_count=1, min_nic_count=2),
    )
    def verify_sriov_failsafe(self, environment: Environment, node: Node) -> None:
        log_suffix = "sriov_failsafe"
        self.setup_xdpdump(environment, [node])
        self.upload_constants_sh(
            environment,
            node,
            {
                "nicName": NIC_NAMES[0],
                "ip": node.internal_address,
            },
        )

        test_node = environment.nodes[0]  # TODO: duplicate, just use node

        ping_process = self.run_ping_cmd(
            test_node, test_node.public_address, NIC_NAMES[0], log_suffix
        )

        xdpdump_process = self.run_xdpdump_cmd(node, NIC_NAMES[0], log_suffix)
        while xdpdump_process.is_running():
            result = test_node.execute(
                f"bash -c 'tail -2 ~/{self.xdpdump_prefix}_{log_suffix}.txt | head -1'"
            )
            self.log.info(result.stdout)

        result = test_node.execute(
            f"bash -c 'tail -2 ~/{self.xdpdump_prefix}_{log_suffix}.txt | head -1'"
        )
        assert_that(
            result.stdout,
            description="xdpdump output did not contain failsafe string 'unloading xdp program'",
        ).is_equal_to("unloading xdp program...")

        assert_that(ping_process.is_running).described_as(
            "ping process did not exit during test verify_sriov_failsafe."
        ).is_false()

    @TestCaseMetadata(
        description="""
        Verifies xdp working with 2 SRIOV-enabled nics i.e. eth1 and eth2
        """,
        priority=1,
        requirement=simple_requirement(min_count=2, min_nic_count=2),
    )
    def verify_xdp_multiple_nics(self, environment: Environment, node: Node) -> None:
        server_node = environment.nodes[0]
        client_node = environment.nodes[1]
        self.setup_xdpdump(environment, [server_node, client_node])
        for node in [server_node, client_node]:
            self.upload_constants_sh(
                environment,
                node,
                {
                    "nicName": NIC_NAMES[0],
                    "ip": node.internal_address,
                },
            )

        # populate Node->NIC->IP info dictionary
        node_nic_ips = dict()
        for node in [client_node, server_node]:
            # TODO: this should validate the nic names
            result = node.execute(
                f"bash -c \"ls /sys/class/net/ | grep -w '{NIC_NAMES[0]}\\|{NIC_NAMES[1]}'\""
            )
            self.log.info(result.stdout)
            node_nic_ips[node] = self.gather_nic_ips(
                node, NIC_NAMES
            )  # TODO: NIC_NAMES use

        self.log.info("Gathering NIC IP info for nodes:")
        self.log.info(node_nic_ips)

        # run XDP+PING tests on multiple nics
        xdp_one, ping_one = self.run_xdp_ping(
            client_node,
            node_nic_ips[server_node][NIC_NAMES[0]],
            NIC_NAMES[1],
            NIC_NAMES[1],
        )
        # TODO: The original test used a hardcoded ip 10.0.5.2? need to ask about that
        xdp_two, ping_two = self.run_xdp_ping(
            client_node,
            node_nic_ips[server_node][NIC_NAMES[1]],
            NIC_NAMES[2],
            NIC_NAMES[2],
        )

        # wait w 5m total timeout for ping/xdpdump processes
        processes = [xdp_one, xdp_two, ping_one, ping_two]
        timeout = 300
        timer = create_timer()
        results = dict()
        while timer.elapsed(stop=False) < timeout and len(processes) > 0:
            remove_procs = []
            for proc in processes:
                if not proc.is_running():
                    results[proc] = proc.wait_result()
                    remove_procs.append(proc)
            if remove_procs:
                for proc in remove_procs:
                    processes.remove(proc)
            # self.log.info("waiting on xdpdump results...")
            time.sleep(1)

        assert_that(
            len(processes), description="Process timed out during xdp_ping"
        ).is_zero()

        self.log.info(
            f"Checking results from xdpping run on client: {client_node.public_address} {NIC_NAMES[1]} {NIC_NAMES[2]}"
        )
        log_result_nic1 = self.check_log_result(
            client_node, self.xdpdump_prefix, NIC_NAMES[1]
        )
        log_result_nic2 = self.check_log_result(
            client_node, self.xdpdump_prefix, NIC_NAMES[2]
        )
        assert_that(log_result_nic1).is_equal_to("unloading xdp program...")
        assert_that(log_result_nic2).is_equal_to("unloading xdp program...")

        xdp_nic1_log = self.get_log_file(client_node, self.xdpdump_prefix, NIC_NAMES[1])
        xdp_nic2_log = self.get_log_file(client_node, self.xdpdump_prefix, NIC_NAMES[2])
        ping_nic1_log = self.get_log_file(client_node, self.ping_prefix, NIC_NAMES[1])
        ping_nic2_log = self.get_log_file(client_node, self.ping_prefix, NIC_NAMES[2])

        # TODO: ^ these logs are downloaded and placed in a log dir in the old runner

        self.log.info(f"xdp {NIC_NAMES[1]} log content:")
        self.log.info(xdp_nic1_log)
        self.log.info(f"xdp {NIC_NAMES[2]} log content:")
        self.log.info(xdp_nic2_log)
        self.log.info(f"ping {NIC_NAMES[1]} log content:")
        self.log.info(ping_nic1_log)
        self.log.info(f"ping {NIC_NAMES[2]} log content:")
        self.log.info(ping_nic2_log)

        self.check_xdptest_state(client_node)

    @TestCaseMetadata(
        description="""
            Test case verifies XDP is able to perform DROP, FWD, ABORT actions.
        """,
        priority=1,
        requirement=simple_requirement(min_count=2, min_nic_count=2),
    )
    def verify_xdp_action(self, environment: Environment) -> None:
        server_node = environment.nodes[0]
        client_node = environment.nodes[1]
        self.setup_xdpdump(environment, [server_node, client_node])

        # values from original test:
        #   ` Add-Content -Value "ip=$($receiverVMData.InternalIP)" -Path $constantsFile
        #     Add-Content -Value "client=$($receiverVMData.InternalIP)" -Path $constantsFile
        #     Add-Content -Value "server=$($senderVMData.InternalIP)" -Path $constantsFile
        #     Add-Content -Value "clientSecondIP=$($receiverVMData.SecondInternalIP)" -Path $constantsFile
        #     Add-Content -Value "serverSecondIP=$($senderVMData.SecondInternalIP)" -Path $constantsFile
        #     Add-Content -Value "nicName=$iFaceName" -Path $constantsFile
        node_nic_ips = dict()
        for node in [server_node, client_node]:
            node_nic_ips[node] = self.gather_nic_ips(
                node, NIC_NAMES[:2]
            )  # TODO: NIC_NAMES use

        for action in ["DROP", "TX", "ABORTED"]:
            constants = {
                "nicName": NIC_NAMES[0],
                "client": f'"{client_node.internal_address}"',
                "server": f'"{server_node.internal_address}"',
                "clientSecondIP": f'"{node_nic_ips[client_node][NIC_NAMES[1]]}"',
                "serverSecondIP": f'"{node_nic_ips[server_node][NIC_NAMES[1]]}"',
                "ip": f'"{client_node.internal_address}"',
                "ACTION": action,
            }
            self.upload_constants_sh(environment, client_node, constants)
            self.log.info(
                f"Running XDP Action: {action} on server node {client_node.internal_address}"
            )
            script: CustomScript = client_node.tools[self._xdp_script]
            result = client_node.execute(
                "bash -c 'source xdputils.sh; ./XDP-Action.sh'",
                sudo=True,
                cwd=script.get_tool_path(),
            )
            self.log.info(result.stdout)

    @TestCaseMetadata(
        description="""
            This script deploys the VM and verify XDP working with various MTU sizes (1500, 2000, 3506) which are easily configurable in XML.
            Also, it will verify error caught by kernel "hv_netvsc" for MTU greater than Maximum MTU on Azure.
        """,
        priority=0,
        requirement=simple_requirement(min_count=2, min_nic_count=2),
    )
    def verify_xdp_mtu(self, environment: Environment, node: Node) -> None:
        server_node = environment.nodes[0]
        client_node = environment.nodes[1]
        self.setup_xdpdump(environment, [server_node, client_node])

        script: CustomScript = client_node.tools[self._xdp_script]

        # values from original test:
        #   ` Add-Content -Value "ip=$($receiverVMData.InternalIP)" -Path $constantsFile
        #     Add-Content -Value "client=$($receiverVMData.InternalIP)" -Path $constantsFile
        #     Add-Content -Value "server=$($senderVMData.InternalIP)" -Path $constantsFile
        #     Add-Content -Value "clientSecondIP=$($receiverVMData.SecondInternalIP)" -Path $constantsFile
        #     Add-Content -Value "serverSecondIP=$($senderVMData.SecondInternalIP)" -Path $constantsFile
        #     Add-Content -Value "nicName=$iFaceName" -Path $constantsFile

        node_nic_ips = dict()
        for node in [server_node, client_node]:
            node_nic_ips[node] = self.gather_nic_ips(
                node, NIC_NAMES[:2]
            )  # TODO: NIC_NAMES use

        constants = {
            "nicName": NIC_NAMES[0],
            "client": f'"{client_node.internal_address}"',
            "server": f'"{server_node.internal_address}"',
            "clientSecondIP": f'"{node_nic_ips[client_node][NIC_NAMES[1]]}"',
            "serverSecondIP": f'"{node_nic_ips[server_node][NIC_NAMES[1]]}"',
            "ip": f'"{client_node.internal_address}"',
            "mtuSizes": '"1000 1500 2000 2500 3000"',
        }
        self.log.info(constants)
        self.upload_constants_sh(environment, client_node, constants)
        result = client_node.execute(
            "bash -c 'source ./xdputils.sh; ./XDP-MTUVerify.sh 2>&1 '",
            cwd=script.get_tool_path(),
        )
        self.log.info(result.stdout)
        assert_that(result.exit_code).described_as(
            "XDP-MTUVerify did not exit correctly."
        ).is_zero()

    # Utility functions follow:
    def gather_nic_ips(self, node: Node, nic_names: list[str]) -> dict[str, str]:
        awk_cmd = "awk '{print $2}'"
        nic_ips = dict()
        for nic in nic_names:
            result = node.execute(
                f"ifconfig {nic} | grep 'inet ' | {awk_cmd}", shell=True
            )  # TODO: ifconfig tool add
            assert_that(result.exit_code == 0 and result.stdout != "")
            nic_ips[nic] = result.stdout
        return nic_ips

    def constants_path(self, environment: Environment):
        return Path.joinpath(environment.log_path, "constants.sh")

    def generate_constants_sh(self, environment: Environment, defs: dict[str, str]):
        constants = ""
        for key in defs:
            constants += f"{key}={defs[key]}\n"
        with open(str(self.constants_path(environment)), "wb") as constants_file:
            constants_file.write(constants.encode("ascii"))

    def upload_constants_sh(
        self, environment: Environment, node: Node, defs: dict[str, str]
    ):
        self.log.info("Uploading constants.sh")
        script = node.tools[self._xdp_script]
        self.generate_constants_sh(environment, defs)
        node.shell.copy(
            self.constants_path(environment),
            script.get_tool_path().joinpath("constants.sh"),
        )
        self.log.info(
            node.execute(
                "bash -c 'cat ./constants.sh'", cwd=script.get_tool_path()
            ).stdout
        )

    def update_constants_sh(
        self, environment: Environment, node: Node, defs: dict[str, str]
    ):
        script = node.tools[self._xdp_script]
        self.generate_constants_sh(environment, defs)
        node.shell.copy(
            Path("constants.sh"), script.get_tool_path().joinpath("constants_update.sh")
        )
        node.execute(
            "bash -c 'cat ./constants_update.sh >> ./constants.sh'",
            cwd=script.get_tool_path(),
        )

    # TODO: snake case all the parameter names
    def check_log_result(self, node: Node, log_prefix: str, log_suffix: str):
        result = node.execute(f"bash -c 'tail -1 ~/{log_prefix}_{log_suffix}.txt'")
        assert_that(
            result.exit_code == 0 and result.stdout.strip() != ""
        )  # TODO: assert_that fixes
        assert_that("No such file or directory" not in result.stdout)
        return result.stdout

    def get_log_file(self, node: Node, log_prefix: str, log_suffix: str):
        # self.log.info(node.execute("bash -c 'ls -la ~'").stdout)
        result = node.execute(f"bash -c 'cat ~/{log_prefix}_{log_suffix}.txt'")
        assert_that(result.exit_code == 0 and result.stdout.strip() != "")
        return result.stdout.strip()

    def generate_ping_cmd(self, dest_ip: Node, nic_name: str, log_suffix: str):
        base_cmd = f"ping -I {nic_name} -c 30 {dest_ip} > ~/{self.ping_prefix}_{log_suffix}.txt"
        return base_cmd

    def disable_lro(self, node: Node, nic_name: str):
        self.log.info(
            f"Disabling LRO on node at {node.public_address}/{node.internal_address}"
        )
        result = node.execute(f"ethtool -K {nic_name} lro off", sudo=True)
        assert_that(result.exit_code == 0)
        self.log.info(result.stdout)

    def check_xdptest_state(self, node: Node):
        script_path = node.tools[self._xdp_script].get_tool_path()
        result = node.execute(f"bash -c 'cat state.txt'", cwd=script_path)
        assert_that(result.stdout).is_equal_to("TestCompleted")
        self.log.info("Test completed successfully")

    def generate_xdpdump_cmd(self, nic_name: str, log_suffix: str):
        return f"cd bpf-samples/xdpdump && timeout 10 ./xdpdump -i {nic_name} > ~/{self.xdpdump_prefix}_{log_suffix}.txt"

    def run_xdpdump_cmd(self, node: Node, nic_name: str, log_suffix: str):
        # run xdpdump command async and return the process object
        xdpdump_cmd = self.generate_xdpdump_cmd(nic_name, log_suffix)
        self.log.info(
            f"Running command: {xdpdump_cmd} on node {node.public_address}/{node.internal_address}"
        )
        script_path = node.tools[self._xdp_script].get_tool_path()
        self.disable_lro(node, nic_name)  # xdp has to run w LRO disabled
        return node.execute_async(
            f"bash -c '{xdpdump_cmd}'", cwd=script_path, sudo=True
        )

    def run_ping_cmd(
        self, origin: Node, dest_ip: str, nic_name: str, log_suffix: str
    ):  # TODO: ping tool instead of cmd string
        ping_cmd = self.generate_ping_cmd(dest_ip, nic_name, log_suffix)
        return origin.execute_async(f'bash -c "{ping_cmd}"')

    def run_xdp_ping(self, origin: Node, dest_ip: str, nic_name: str, log_suffix: str):
        ping_process = self.run_ping_cmd(origin, dest_ip, nic_name, log_suffix)
        xdp_process = self.run_xdpdump_cmd(origin, nic_name, log_suffix)
        return xdp_process, ping_process

    def generate_keys_paths(
        self, environment: Environment, node: Node
    ) -> tuple[Path, Path]:
        local_path = environment.log_path.joinpath("keys.tgz.b64")
        remote_path = node.remote_working_path.joinpath("keys.tgz.b64")
        return local_path, remote_path

    def copy_and_install_keys_to_node(self, environment: Environment, node: Node):
        self.log.info(f"Copying keys to node : {node.internal_address}")
        local_path, remote_path = self.generate_keys_paths(environment, node)
        node.shell.copy(local_path, remote_path)
        result = node.execute("bash -c 'ls -la '", cwd=node.remote_working_path)
        self.log.info(result.stdout)
        result = node.execute(
            f"bash -c 'cat keys.tgz.b64 | base64 -d --ignore-garbage | tar -xzvf -'",
            cwd=node.remote_working_path,
        )
        result = node.execute("bash -c 'ls -la '", cwd=node.remote_working_path)
        self.log.debug(result.stdout)
        result = node.execute(
            "bash -c 'ssh-agent ssh-add'", cwd=node.remote_working_path
        )
        self.log.info(result.stdout)

    def setup_keys_on_main_node(self, environment: Environment, node: Node) -> None:
        result = node.execute("bash -c 'echo | ssh-keygen -N \"\"'")
        self.log.info(result.stdout)
        result = node.execute("bash -c 'ls -la ~/.ssh'")
        self.log.info(result.stdout)
        result = node.execute("bash -c 'ssh-agent ssh-add'")
        self.log.info(result.stdout)
        result = node.execute(
            "bash -c 'tar -czvf ~/keys.tgz ~/.ssh/id_rsa ~/.ssh/id_rsa.pub'"
        )
        self.log.info(result.stdout)
        result = node.execute("bash -c 'cat ~/keys.tgz | base64' ")
        self.log.info(result.stdout)
        local_path, remote_path = self.generate_keys_paths(environment, node)  # type: ignore
        with open(str(local_path), "wb") as keyfile:
            keyfile.write(result.stdout.encode("ascii"))

    def setup_xdpdump(self, environment: Environment, nodes: list[Node]):
        main_node = nodes[0]
        self.setup_keys_on_main_node(environment, main_node)
        for node in nodes:
            self.copy_and_install_keys_to_node(environment, node)
        for node in nodes:
            self.log.info("Setting up environment before test case")
            script: CustomScript = node.tools[self._xdp_script]
            # setup constants.sh
            self.upload_constants_sh(
                environment,
                node,
                {"nicName": NIC_NAMES[0], "ip": f'"{node.internal_address}"'},
            )

            synth_interface = script.run(
                "bash -c 'source ./xdputils.sh;get_extra_synth_nic'"
            ).stdout
            self.log.info("synth interface: " + synth_interface)
            assert_that(synth_interface).is_not_none()
            assert_that(synth_interface).described_as(
                "output should not be empty"
            ).is_not_equal_to("")

            # Start setup script with parameters
            result = node.execute(
                f"./xdpdumpsetup.sh {node.internal_address} {synth_interface}",
                cwd=script.get_tool_path(),
            )
            self.log.info(result.stdout)
            self.log.debug(
                node.execute(
                    "bash -c 'cat ~/xdpdumpout.txt'", cwd=script.get_tool_path()
                ).stdout
            )

            assert_that(result.exit_code).described_as(
                "xdpdump did not terminate correctly, check xdpdumpout.txt for more info"
            ).is_zero()
            result = node.execute(
                f"bash -c 'source ./utils.sh; collect_VM_properties ~/VM_Properties.csv'",
                cwd=script.get_tool_path(),
            )
            self.log.info(result.stdout)
            self.log.debug(
                "found vm_properties:\n"
                + node.execute("bash -c 'cat ~/VM_Properties.csv'").stdout
            )
