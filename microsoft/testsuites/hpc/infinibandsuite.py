# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from assertpy import assert_that

from lisa import (
    Environment,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.features import Infiniband, Sriov
from lisa.sut_orchestrator.azure.tools import Waagent
from lisa.tools import Find, KernelConfig, Modprobe, Ssh
from lisa.util import (
    LisaException,
    SkippedException,
    UnsupportedDistroException,
    UnsupportedKernelException,
)
from lisa.util.parallel import run_in_parallel


@TestSuiteMetadata(
    area="hpc",
    category="functional",
    description="""
    Tests the functionality of infiniband.
    """,
)
class InfinibandSuite(TestSuite):
    @TestCaseMetadata(
        description="""
        This test case will
        1. List all available network interfaces
        2. Check if InfiniBand cards are present
        3. Ensure the first InfiniBand card is named starting with "ib0"
        """,
        priority=2,
        requirement=simple_requirement(supported_features=[Infiniband]),
    )
    def verify_ib_naming(self, log: Logger, node: Node) -> None:
        ib_interfaces = node.features[Infiniband].get_ib_interfaces()
        ib_first_device_name = [x.nic_name for x in ib_interfaces]

        if not ib_first_device_name:
            raise LisaException("This node has no IB devices available.")
        if "ib0" not in ib_first_device_name:
            raise LisaException("The first IB device on this node is not named ib0.")
        log.info("IB device naming/ordering has been verified successfully!")

    @TestCaseMetadata(
        description="""
        This test case will
        1. Determine whether the VM has Infiniband over SR-IOV
        2. Ensure waagent is configures with OS.EnableRDMA=y
        3. Check that appropriate drivers are present
        """,
        priority=2,
        requirement=simple_requirement(
            network_interface=Sriov(), supported_features=[Infiniband]
        ),
    )
    def verify_hpc_over_sriov(self, log: Logger, node: Node) -> None:
        try:
            infiniband = node.features[Infiniband]
        except (UnsupportedDistroException, UnsupportedKernelException) as err:
            raise SkippedException(err)

        assert_that(infiniband.is_over_sriov()).described_as(
            "Based on VM SKU information we expected Infiniband over SR-IOV,"
            " but no matching devices were found."
        ).is_true()

        waagent = node.tools[Waagent]
        assert_that(waagent.is_rdma_enabled()).described_as(
            "Found waagent configuration of OS.EnableRDMA=y "
            "was missing or commented out"
        ).is_true()
        log.debug("Verified waagent config OS.EnableRDMA=y set successfully")

        modprobe = node.tools[Modprobe]
        expected_modules = [
            "mlx5_ib",
            "ib_uverbs",
            "ib_core",
            "mlx5_core",
            "mlx_compat",
            "rdma_cm",
            "iw_cm",
            "ib_cm",
        ]

        for module in expected_modules:
            assert_that(modprobe.is_module_loaded(module)).described_as(
                f"Module {module} is not loaded."
            ).is_true()

    @TestCaseMetadata(
        description="""
        This test case will
        1. Determine whether the VM has Infiniband over Network Direct
        2. Ensure waagent is configures with OS.EnableRDMA=y
        3. Check that appropriate drivers are present
        """,
        priority=2,
        requirement=simple_requirement(supported_features=[Infiniband]),
    )
    def verify_hpc_over_nd(self, log: Logger, node: Node) -> None:
        try:
            self._check_nd_enabled(node)
        except UnsupportedDistroException as err:
            raise SkippedException(err)

        try:
            infiniband = node.features[Infiniband]
        except (UnsupportedDistroException, UnsupportedKernelException) as err:
            raise SkippedException(err)

        if not infiniband.is_over_nd():
            raise SkippedException("Inifiniband over ND was not detected.")

        waagent = node.tools[Waagent]
        assert_that(waagent.is_rdma_enabled()).described_as(
            "Found waagent configuration of OS.EnableRDMA=y "
            "was missing or commented out"
        ).is_true()
        log.debug("Verified waagent config OS.EnableRDMA=y set successfully")

        modprobe = node.tools[Modprobe]
        expected_modules = ["mlx5_ib", "hv_networkdirect"]

        for module in expected_modules:
            assert_that(modprobe.is_module_loaded(module)).described_as(
                f"Module {module} is not loaded."
            ).is_true()

    @TestCaseMetadata(
        description="""
        This test case will
        1. Identify the infiniband devices and their cooresponding network interfaces
        2. Run several ping-pong tests to check RDMA / Infiniband functionality
        """,
        priority=1,
        requirement=simple_requirement(
            supported_features=[Infiniband],
            min_count=2,
        ),
    )
    def verify_ping_pong(self, environment: Environment, log: Logger) -> None:
        # Constants
        ping_pong_tests = ["ibv_rc_pingpong", "ibv_uc_pingpong", "ibv_ud_pingpong"]

        server_node = environment.nodes[0]
        client_node = environment.nodes[1]

        # Ensure RDMA is setup
        try:
            client_infiniband, server_infiniband = run_in_parallel(
                [
                    lambda: client_node.features[Infiniband],
                    lambda: server_node.features[Infiniband],
                ]
            )
        except (UnsupportedDistroException, UnsupportedKernelException) as err:
            raise SkippedException(err)

        server_ib_interfaces = server_infiniband.get_ib_interfaces()
        client_ib_interfaces = client_infiniband.get_ib_interfaces()

        client_ib_device_name = client_ib_interfaces[0].ib_device_name

        for interface in server_ib_interfaces:
            ib_device_name = interface.ib_device_name
            ip_addr = interface.ip_addr

            for test in ping_pong_tests:
                server_process = server_node.execute_async(
                    f"{test} -g 0 -d {ib_device_name}"
                )
                client_process = client_node.execute_async(
                    f"{test} -g 0 -d {client_ib_device_name} {ip_addr}"
                )

                client_result = client_process.wait_result()
                client_result.assert_exit_code(
                    0,
                    f"Client ping-pong test {test} failed with exit code "
                    f"{client_result.exit_code} and output {client_result.stdout}",
                )

                server_result = server_process.wait_result()
                server_result.assert_exit_code(
                    0,
                    f"Server ping-pong test {test} failed with exit code "
                    f"{server_result.exit_code} and output {server_result.stdout}",
                )

    @TestCaseMetadata(
        description="""
            This test case will
            1. Ensure RDMA is setup
            2. Install Intel MPI
            3. Set up ssh keys of server/client connection
            4. Run MPI pingpong tests
            5. Run other MPI tests
            """,
        priority=4,
        requirement=simple_requirement(
            supported_features=[Infiniband],
            min_count=2,
        ),
    )
    def verify_intel_mpi(self, environment: Environment, log: Logger) -> None:
        server_node = environment.nodes[0]
        client_node = environment.nodes[1]

        # Ensure RDMA is setup
        try:
            client_ib, server_ib = run_in_parallel(
                [
                    lambda: client_node.features[Infiniband],
                    lambda: server_node.features[Infiniband],
                ]
            )
        except (UnsupportedDistroException, UnsupportedKernelException) as err:
            raise SkippedException(err)

        run_in_parallel([server_ib.install_intel_mpi, client_ib.install_intel_mpi])

        # Restart the ssh sessions for changes to /etc/security/limits.conf
        # to take effect
        server_node.close()
        client_node.close()

        # Get the ip adresses and device name of ib device
        server_ib_interfaces = server_ib.get_ib_interfaces()
        client_ib_interfaces = client_ib.get_ib_interfaces()
        server_nic_name = server_ib_interfaces[0].nic_name
        server_ip = server_ib_interfaces[0].ip_addr
        client_ip = client_ib_interfaces[0].ip_addr

        # Test relies on machines being able to ssh into each other
        server_ssh = server_node.tools[Ssh]
        client_ssh = client_node.tools[Ssh]
        server_ssh.enable_public_key(client_ssh.generate_key_pairs())
        client_ssh.enable_public_key(server_ssh.generate_key_pairs())
        server_ssh.add_known_host(client_ip)
        client_ssh.add_known_host(server_ip)

        # Note: Using bash because script is not supported by Dash
        # sh points to dash on Ubuntu
        server_node.execute(
            "bash /opt/intel/oneapi/mpi/2021.1.1/bin/mpirun "
            f"-hosts {server_ip},{server_ip} -iface {server_nic_name} -ppn 1 -n 2 "
            "-env I_MPI_FABRICS=shm:ofi -env SECS_PER_SAMPLE=600 "
            "-env FI_PROVIDER=mlx -env I_MPI_DEBUG=5 -env I_MPI_PIN_DOMAIN=numa "
            "/opt/intel/oneapi/mpi/2021.1.1/bin/IMB-MPI1 pingpong",
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed intra-node pingpong test "
            "with intel mpi",
        )

        server_node.execute(
            "bash /opt/intel/oneapi/mpi/2021.1.1/bin/mpirun "
            f"-hosts {server_ip},{client_ip} -iface {server_nic_name} -ppn 1 -n 2 "
            "-env I_MPI_FABRICS=shm:ofi -env SECS_PER_SAMPLE=600 "
            "-env FI_PROVIDER=mlx -env I_MPI_DEBUG=5 -env I_MPI_PIN_DOMAIN=numa "
            "/opt/intel/oneapi/mpi/2021.1.1/bin/IMB-MPI1 pingpong",
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed inter-node pingpong test "
            "with intel mpi",
        )

        tests = ["IMB-MPI1 allreduce", "IMB-RMA", "IMB-NBC"]
        for test in tests:
            server_node.execute(
                "bash /opt/intel/oneapi/mpi/2021.1.1/bin/mpirun "
                f"-hosts {server_ip},{client_ip} -iface {server_nic_name} -ppn 22 "
                "-n 44 -env I_MPI_FABRICS=shm:ofi -env SECS_PER_SAMPLE=600 "
                "-env FI_PROVIDER=mlx -env I_MPI_DEBUG=5 -env I_MPI_PIN_DOMAIN=numa "
                f"/opt/intel/oneapi/mpi/2021.1.1/bin/{test}",
                expected_exit_code=0,
                expected_exit_code_failure_message=f"Failed {test} test with intel mpi",
                timeout=3000,
            )

    @TestCaseMetadata(
        description="""
            This test case will
            1. Ensure RDMA is setup
            2. Install Open MPI
            3. Set up ssh keys of server/client connection
            4. Run MPI pingpong tests
            5. Run other MPI tests
            """,
        priority=4,
        requirement=simple_requirement(
            supported_features=[Infiniband],
            min_count=2,
        ),
    )
    def verify_open_mpi(self, environment: Environment, log: Logger) -> None:
        server_node = environment.nodes[0]
        client_node = environment.nodes[1]

        # Ensure RDMA is setup
        try:
            client_ib, server_ib = run_in_parallel(
                [
                    lambda: client_node.features[Infiniband],
                    lambda: server_node.features[Infiniband],
                ]
            )
        except (UnsupportedDistroException, UnsupportedKernelException) as err:
            raise SkippedException(err)

        run_in_parallel([server_ib.install_open_mpi, client_ib.install_open_mpi])

        server_node.execute("ldconfig", sudo=True)
        client_node.execute("ldconfig", sudo=True)

        # Restart the ssh sessions for changes to /etc/security/limits.conf
        # to take effect
        server_node.close()
        client_node.close()

        # Get the ip adresses and device name of ib device
        server_ib_interfaces = server_ib.get_ib_interfaces()
        client_ib_interfaces = client_ib.get_ib_interfaces()
        server_ip = server_ib_interfaces[0].ip_addr
        client_ip = client_ib_interfaces[0].ip_addr

        # Test relies on machines being able to ssh into each other
        server_ssh = server_node.tools[Ssh]
        client_ssh = client_node.tools[Ssh]
        server_ssh.enable_public_key(client_ssh.generate_key_pairs())
        client_ssh.enable_public_key(server_ssh.generate_key_pairs())
        server_ssh.add_known_host(client_ip)
        client_ssh.add_known_host(server_ip)

        # Ping Pong test
        find = server_node.tools[Find]
        find_results = find.find_files(
            server_node.get_pure_path("/usr"), "IMB-MPI1", sudo=True
        )
        assert_that(len(find_results)).described_as(
            "Could not find location of IMB-MPI1 for Open MPI"
        ).is_greater_than(0)
        test_path = find_results[0]
        assert_that(test_path).described_as(
            "Could not find location of IMB-MPI1 for Open MPI"
        ).is_not_empty()
        server_node.execute(
            f"/usr/local/bin/mpirun --host {server_ip},{server_ip} "
            "-n 2 --mca btl self,vader,openib --mca btl_openib_cq_size 4096 "
            "--mca btl_openib_allow_ib 1 --mca "
            f"btl_openib_warn_no_device_params_found 0 {test_path} pingpong",
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed intra-node ping pong test "
            "with Open MPI",
        )

        # IMB-MPI Tests
        find_results = find.find_files(
            server_node.get_pure_path("/usr"), "IMB-MPI1", sudo=True
        )
        assert_that(len(find_results)).described_as(
            "Could not find location of Open MPI test: IMB-MPI1"
        ).is_greater_than(0)
        test_path = find_results[0]
        assert_that(test_path).described_as(
            "Could not find location of Open MPI test: IMB-MPI1"
        ).is_not_empty()
        server_node.execute(
            f"/usr/local/bin/mpirun --host {server_ip},{client_ip} "
            "-n 2 --mca btl self,vader,openib --mca btl_openib_cq_size 4096 "
            "--mca btl_openib_allow_ib 1 --mca "
            f"btl_openib_warn_no_device_params_found 0 {test_path}",
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed " "IMB-MPI1 test with Open MPI",
        )

    @TestCaseMetadata(
        description="""
            This test case will
            1. Ensure RDMA is setup
            2. Install IBM MPI
            3. Set up ssh keys of server/client connection
            4. Run MPI pingpong tests
            """,
        priority=4,
        requirement=simple_requirement(
            supported_features=[Infiniband],
            min_count=2,
        ),
    )
    def verify_ibm_mpi(self, environment: Environment, log: Logger) -> None:
        server_node = environment.nodes[0]
        client_node = environment.nodes[1]

        # Ensure RDMA is setup
        try:
            client_ib, server_ib = run_in_parallel(
                [
                    lambda: client_node.features[Infiniband],
                    lambda: server_node.features[Infiniband],
                ]
            )
        except (UnsupportedDistroException, UnsupportedKernelException) as err:
            raise SkippedException(err)

        run_in_parallel([server_ib.install_ibm_mpi, client_ib.install_ibm_mpi])

        # Restart the ssh sessions for changes to /etc/security/limits.conf
        # to take effect
        server_node.close()
        client_node.close()

        # Get the ip adresses and device name of ib device
        server_ib_interfaces = server_ib.get_ib_interfaces()
        client_ib_interfaces = client_ib.get_ib_interfaces()
        server_ip = server_ib_interfaces[0].ip_addr
        client_ip = client_ib_interfaces[0].ip_addr

        # Test relies on machines being able to ssh into each other
        server_ssh = server_node.tools[Ssh]
        client_ssh = client_node.tools[Ssh]
        server_ssh.enable_public_key(client_ssh.generate_key_pairs())
        client_ssh.enable_public_key(server_ssh.generate_key_pairs())
        server_ssh.add_known_host(client_ip)
        client_ssh.add_known_host(server_ip)

        # if it is hpc image, use module tool load mpi/hpcx
        # then run pingpong test
        if server_ib.is_hpc_image:
            command_str_1 = (
                "bash -c 'source /usr/share/modules/init/bash && module load mpi/hpcx "
                f"&& mpirun --host {server_ip}:1,{server_ip}:1 -np 2 -x "
                f"MPI_IB_PKEY={server_ib.get_pkey()} -x LD_LIBRARY_PATH "
                "/opt/ibm/platform_mpi/help/ping_pong 4096'"
            )
            command_str_2 = (
                "bash -c 'source /usr/share/modules/init/bash && module load mpi/hpcx "
                f"&& mpirun --host {server_ip}:1,{client_ip}:1 -np 2 -x "
                f"MPI_IB_PKEY={server_ib.get_pkey()} -x LD_LIBRARY_PATH "
                "/opt/ibm/platform_mpi/help/ping_pong 4096'"
            )
        else:
            command_str_1 = (
                "/opt/ibm/platform_mpi/bin/mpirun "
                f"-hostlist {server_ip}:1,{server_ip}:1 -np 2 -e "
                f"MPI_IB_PKEY={server_ib.get_pkey()} -ibv /opt/ibm/platform_mpi/help/"
                "ping_pong 4096"
            )
            command_str_2 = (
                "/opt/ibm/platform_mpi/bin/mpirun "
                f"-hostlist {server_ip}:1,{client_ip}:1 -np 2 -e "
                f"MPI_IB_PKEY={server_ib.get_pkey()} -ibv /opt/ibm/platform_mpi/help/"
                "ping_pong 4096"
            )
        server_node.execute(
            command_str_1,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Infiniband intra-node ping pong "
            "test failed with IBM MPI",
        )
        server_node.execute(
            command_str_2,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Infiniband inter-node ping pong "
            "test failed with IBM MPI",
        )

    @TestCaseMetadata(
        description="""
            This test case will
            1. Ensure RDMA is setup
            2. Install MVAPICH MPI
            3. Set up ssh keys of server/client connection
            4. Run MPI pingpong tests
            5. Run other MPI tests
            """,
        priority=4,
        requirement=simple_requirement(
            supported_features=[Infiniband],
            min_count=2,
        ),
    )
    def verify_mvapich_mpi(self, environment: Environment, log: Logger) -> None:
        server_node = environment.nodes[0]
        client_node = environment.nodes[1]

        # Ensure RDMA is setup
        try:
            client_ib, server_ib = run_in_parallel(
                [
                    lambda: client_node.features[Infiniband],
                    lambda: server_node.features[Infiniband],
                ]
            )
        except (UnsupportedDistroException, UnsupportedKernelException) as err:
            raise SkippedException(err)

        run_in_parallel([server_ib.install_mvapich_mpi, client_ib.install_mvapich_mpi])

        # Restart the ssh sessions for changes to /etc/security/limits.conf
        # to take effect
        server_node.close()
        client_node.close()

        # Get the ip adresses and device name of ib device
        server_ib_interfaces = server_ib.get_ib_interfaces()
        client_ib_interfaces = client_ib.get_ib_interfaces()
        server_ip = server_ib_interfaces[0].ip_addr
        client_ip = client_ib_interfaces[0].ip_addr

        # Test relies on machines being able to ssh into each other
        server_ssh = server_node.tools[Ssh]
        client_ssh = client_node.tools[Ssh]
        server_ssh.enable_public_key(client_ssh.generate_key_pairs())
        client_ssh.enable_public_key(server_ssh.generate_key_pairs())
        server_ssh.add_known_host(client_ip)
        client_ssh.add_known_host(server_ip)

        # Run MPI tests
        find = server_node.tools[Find]
        test_names = ["IMB-MPI1", "IMB-RMA", "IMB-NBC"]
        for test in test_names:
            find_results = find.find_files(
                server_node.get_pure_path("/usr"), test, sudo=True
            )
            assert_that(len(find_results)).described_as(
                f"Could not find location of MVAPICH MPI test: {test}"
            ).is_greater_than(0)
            test_path = find_results[0]
            assert_that(test_path).described_as(
                f"Could not find location of MVAPICH MPI test: {test}"
            ).is_not_empty()
            server_node.execute(
                f"/usr/local/bin/mpirun --hosts {server_ip},{client_ip} "
                f"-n 2 -ppn 1 {test_path}",
                expected_exit_code=0,
                expected_exit_code_failure_message=f"Failed {test} test "
                "with MVAPICH MPI",
            )

    def _check_nd_enabled(self, node: Node) -> None:
        # non-SRIOV RDMA VM sizes need hv_network_direct driver to initialize device
        # non-SRIOV RDMA VM sizes will be upgraded to SR-IOV sooner
        # recent images remove this module, so skip case in this situation
        if not node.tools[KernelConfig].is_enabled("CONFIG_HYPERV_INFINIBAND_ND"):
            raise UnsupportedDistroException(
                node.os, "hv_network_direct module is not enabled"
            )
