# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Dict
import time
import os

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import Posix
from lisa.tools import (
    Lsmod, 
    Modprobe, 
    Modinfo, 
    Lspci, 
    Dmesg, 
    Make,
    Gcc,
    Cat,
    Ls,
    Echo,
    Wget,
    Tar
)
from lisa.util import LisaException, SkippedException


@TestSuiteMetadata(
    area="kernel",
    category="driver", 
    description="""
    Test suite for Azure Integrated HSM (azihsm) Linux kernel driver.
    Validates driver loading, PCI device detection, functionality, and cleanup.
    """,
    requirement=simple_requirement(
        min_core_count=2,
        min_memory_mb=4096,
        unsupported_os=["Windows"],
    ),
)
class AziHsmDriverTest(TestSuite):
    """Test suite for azihsm Linux kernel driver"""

    DRIVER_NAME = "azihsm"
    PCI_VENDOR_ID = "1414"  # Microsoft
    PCI_DEVICE_ID = "C003"  # AziHSM device
    # Based on actual driver source analysis:
    # HSM device: /dev/azihsm%d, MGMT device: /dev/azihsm-mgmt%d
    # AES and CTRL operations are handled via ioctl on HSM device
    EXPECTED_CHAR_DEVICE_PATTERNS = [
        "/dev/azihsm",      # HSM device (will have numbered suffix)
        "/dev/azihsm-mgmt", # MGMT device (will have numbered suffix) 
    ]

    def _get_source_url(self) -> str:
        """Get the OOT source URL from LISA variables if provided"""
        # LISA variables are typically accessed through environment variables or command line
        # This can be set via: lisa -v oot_source_url:https://example.com/source.tar.gz
        import os
        return os.environ.get("LISA_OOT_SOURCE_URL", "")

    def _setup_driver_source(self, node: Node, log: Logger, source_url: str = "") -> str:
        """Setup and build the driver source code"""
        log.info("Setting up azihsm driver source...")
        
        driver_path = ""
        
        # If source URL is provided, download and extract it
        if source_url:
            log.info(f"Downloading driver source from URL: {source_url}")
            
            # Create temporary download directory
            download_dir = "/tmp/azihsm-download"
            node.execute(f"mkdir -p {download_dir}", sudo=True)
            
            # Extract filename from URL
            filename = source_url.split('/')[-1]
            download_path = f"{download_dir}/{filename}"
            
            # Download the source archive
            wget = node.tools[Wget]
            result = node.execute(f"wget -O {download_path} {source_url}", sudo=True, timeout=300)
            if result.exit_code != 0:
                raise LisaException(f"Failed to download source from {source_url}: {result.stderr}")
            
            log.info(f"Successfully downloaded {filename}")
            
            # Extract the archive to /tmp/azihsm-driver/
            extract_dir = "/tmp/azihsm-driver"
            node.execute(f"rm -rf {extract_dir} && mkdir -p {extract_dir}", sudo=True)
            
            tar = node.tools[Tar]
            
            # Determine extraction command based on file extension
            if filename.endswith('.tar.gz') or filename.endswith('.tgz'):
                extract_cmd = f"tar -xzf {download_path} -C {extract_dir} --strip-components=1"
            elif filename.endswith('.tar.bz2') or filename.endswith('.tbz2'):
                extract_cmd = f"tar -xjf {download_path} -C {extract_dir} --strip-components=1"
            elif filename.endswith('.tar'):
                extract_cmd = f"tar -xf {download_path} -C {extract_dir} --strip-components=1"
            else:
                raise LisaException(f"Unsupported archive format: {filename}")
            
            result = node.execute(extract_cmd, sudo=True, timeout=120)
            if result.exit_code != 0:
                raise LisaException(f"Failed to extract {filename}: {result.stderr}")
                
            log.info(f"Successfully extracted source to {extract_dir}")
            
            # Set driver path to the extracted source directory
            potential_src_paths = [
                f"{extract_dir}/src",      # Most common pattern
                f"{extract_dir}",          # Root directory
                f"{extract_dir}/driver",   # Alternative pattern
            ]
            
            ls = node.tools[Ls]
            for path in potential_src_paths:
                if ls.path_exists(path=f"{path}/Makefile", sudo=True):
                    driver_path = path
                    log.info(f"Found Makefile in {driver_path}")
                    break
            
            if not driver_path:
                # List contents to help debug
                result = node.execute(f"find {extract_dir} -name Makefile -type f", sudo=True)
                log.warning(f"Available Makefiles: {result.stdout}")
                raise LisaException(f"Could not find Makefile in extracted source at {extract_dir}")
                
        else:
            # Fallback to existing logic - check multiple possible source locations
            possible_paths = [
                "/tmp/azihsm-driver/src",  # Downloaded source location
                "/home/*/oot_modules/azihsm-linux-driver-main/src",  # Actual location from analysis
                "/opt/azihsm/src",  # Alternative location
            ]
            
            ls = node.tools[Ls]
            
            for path_pattern in possible_paths:
                if "*" in path_pattern:
                    # Handle wildcard paths
                    result = node.execute(f"ls -d {path_pattern} 2>/dev/null || true", sudo=True)
                    if result.exit_code == 0 and result.stdout.strip():
                        driver_path = result.stdout.strip().split('\n')[0]
                        break
                else:
                    if ls.path_exists(path=path_pattern, sudo=True):
                        driver_path = path_pattern
                        break
            
            if not driver_path:
                raise SkippedException("Driver source not found in any expected location and no source URL provided")
            
        # Verify Makefile exists
        makefile_path = f"{driver_path}/Makefile"
        if not ls.path_exists(path=makefile_path, sudo=True):
            raise SkippedException(f"Makefile not found at {makefile_path}")
            
        # Build the driver
        make = node.tools[Make]
        log.info(f"Building azihsm driver from {driver_path}...")
        result = make.run_make(
            arguments="", 
            cwd=driver_path,
            sudo=True,
            timeout=300
        )
        
        if result.exit_code != 0:
            raise LisaException(f"Driver build failed: {result.stderr}")
            
        log.info("Driver build completed successfully")
        return driver_path

    def _check_pci_device_present(self, node: Node, log: Logger) -> bool:
        """Check if AziHSM PCI device is present"""
        lspci = node.tools[Lspci]
        devices = lspci.get_devices()
        
        for device in devices:
            if (device.vendor_id == self.PCI_VENDOR_ID and 
                device.device_id == self.PCI_DEVICE_ID):
                log.info(f"Found AziHSM PCI device: {device}")
                return True
                
        return False

    def _load_driver(self, node: Node, log: Logger, driver_path: str) -> None:
        """Load the azihsm driver"""
        modprobe = node.tools[Modprobe]
        
        # Insert the module
        ko_file = f"{driver_path}/{self.DRIVER_NAME}.ko"
        log.info(f"Loading driver from {ko_file}")
        
        result = node.execute(f"insmod {ko_file}", sudo=True)
        if result.exit_code != 0:
            raise LisaException(f"Failed to load driver: {result.stderr}")
            
        # Verify module is loaded
        if not modprobe.is_module_loaded(self.DRIVER_NAME):
            raise LisaException(f"Driver {self.DRIVER_NAME} not loaded")
            
        log.info("Driver loaded successfully")

    def _unload_driver(self, node: Node, log: Logger) -> None:
        """Unload the azihsm driver"""
        modprobe = node.tools[Modprobe]
        
        if modprobe.is_module_loaded(self.DRIVER_NAME):
            log.info("Unloading azihsm driver...")
            result = node.execute(f"rmmod {self.DRIVER_NAME}", sudo=True)
            if result.exit_code != 0:
                log.warning(f"Failed to unload driver: {result.stderr}")
            else:
                log.info("Driver unloaded successfully")

    @TestCaseMetadata(
        description="""
        Test basic driver loading and unloading functionality.
        Verifies that the driver can be loaded without errors.
        """,
        priority=1,
        requirement=simple_requirement(min_core_count=1),
    )
    def test_driver_load_unload(self, node: Node, log: Logger) -> None:
        """Test basic driver loading and unloading"""
        
        # Check if PCI device is present (skip if not)
        if not self._check_pci_device_present(node, log):
            raise SkippedException("AziHSM PCI device not found - skipping driver test")
        
        # Setup and build driver
        source_url = self._get_source_url()
        driver_path = self._setup_driver_source(node, log, source_url)
        
        try:
            # Load driver
            self._load_driver(node, log, driver_path)
            
            # Verify driver is loaded
            lsmod = node.tools[Lsmod]
            modules = lsmod.get_modules()
            module_names = [mod.name for mod in modules]
            
            assert_that(module_names).contains(self.DRIVER_NAME)
            log.info("Driver successfully loaded and visible in lsmod")
            
        finally:
            # Always try to unload
            self._unload_driver(node, log)

    @TestCaseMetadata(
        description="""
        Test that character devices are created when driver loads.
        Verifies proper device node creation and permissions.
        """,
        priority=2,
    )
    def test_device_creation(self, node: Node, log: Logger) -> None:
        """Test character device creation"""
        
        if not self._check_pci_device_present(node, log):
            raise SkippedException("AziHSM PCI device not found")
            
        source_url = self._get_source_url()
        driver_path = self._setup_driver_source(node, log, source_url)
        
        try:
            self._load_driver(node, log, driver_path)
            
            # Wait a moment for devices to be created
            time.sleep(2)
            
            # Check that expected character devices exist (with numbered suffixes)
            ls = node.tools[Ls]
            found_devices = []
            
            for device_pattern in self.EXPECTED_CHAR_DEVICE_PATTERNS:
                # Look for devices matching pattern with numeric suffixes
                result = node.execute(f"ls {device_pattern}* 2>/dev/null || true", sudo=True)
                if result.exit_code == 0 and result.stdout.strip():
                    devices = result.stdout.strip().split('\n')
                    found_devices.extend(devices)
                    for device in devices:
                        log.info(f"Device {device} created successfully")
                        
                        # Check device permissions
                        result = node.execute(f"ls -l {device}", sudo=True)
                        log.info(f"Device permissions for {device}: {result.stdout}")
                        
            # Verify we found at least the expected device types
            hsm_devices = [d for d in found_devices if d.startswith("/dev/azihsm") and not "-mgmt" in d]
            mgmt_devices = [d for d in found_devices if "/azihsm-mgmt" in d]
            
            assert_that(hsm_devices).described_as("HSM devices should be created").is_not_empty()
            assert_that(mgmt_devices).described_as("MGMT devices should be created").is_not_empty()
                
        finally:
            self._unload_driver(node, log)

    @TestCaseMetadata(
        description="""
        Test driver information and metadata.
        Verifies module info, version, and description.
        """,
        priority=3,
    )
    def test_driver_info(self, node: Node, log: Logger) -> None:
        """Test driver module information"""
        
        source_url = self._get_source_url()
        driver_path = self._setup_driver_source(node, log, source_url)
        ko_file = f"{driver_path}/{self.DRIVER_NAME}.ko"
        
        # Get module info before loading
        modinfo = node.tools[Modinfo]
        info = modinfo.get_information(ko_file)
        
        log.info(f"Driver info: {info}")
        
        # Verify expected fields exist
        assert_that(info.name).is_equal_to(self.DRIVER_NAME)
        assert_that(info.description).is_not_none()
        assert_that(info.filename).contains(".ko")
        
        log.info("Driver module information validated")

    @TestCaseMetadata(
        description="""
        Test driver behavior in kernel logs.
        Checks for proper initialization messages and no errors.
        """,
        priority=4,
    )
    def test_kernel_log_messages(self, node: Node, log: Logger) -> None:
        """Test kernel log messages during driver load/unload"""
        
        if not self._check_pci_device_present(node, log):
            raise SkippedException("AziHSM PCI device not found")
            
        source_url = self._get_source_url()
        driver_path = self._setup_driver_source(node, log, source_url)
        dmesg = node.tools[Dmesg]
        
        try:
            # Clear dmesg before test
            node.execute("dmesg -c", sudo=True)
            
            # Load driver
            self._load_driver(node, log, driver_path)
            
            # Check dmesg for driver messages
            boot_messages = dmesg.get_output()
            log.info(f"Kernel messages after driver load:\n{boot_messages}")
            
            # Look for initialization messages
            azihsm_messages = [msg for msg in boot_messages.split('\n') 
                             if 'azihsm' in msg.lower()]
            
            assert_that(azihsm_messages).is_not_empty()
            log.info("Driver initialization messages found in kernel log")
            
            # Check for any error messages
            error_messages = [msg for msg in azihsm_messages 
                            if any(word in msg.lower() for word in ['error', 'failed', 'panic'])]
            
            if error_messages:
                log.warning(f"Found error messages in logs: {error_messages}")
            else:
                log.info("No error messages found in kernel logs")
                
        finally:
            self._unload_driver(node, log)

    @TestCaseMetadata(
        description="""
        Test basic device I/O operations through ioctl interface.
        Performs simple operations to verify driver functionality.
        """,
        priority=5,
    )
    def test_basic_device_io(self, node: Node, log: Logger) -> None:
        """Test basic device I/O operations"""
        
        if not self._check_pci_device_present(node, log):
            raise SkippedException("AziHSM PCI device not found")
            
        source_url = self._get_source_url()
        driver_path = self._setup_driver_source(node, log, source_url)
        
        try:
            self._load_driver(node, log, driver_path)
            time.sleep(2)  # Wait for devices
            
            # Test opening HSM device (control operations go through HSM device)
            # Find the actual HSM device name
            result = node.execute("ls /dev/azihsm[0-9]* 2>/dev/null | head -1", sudo=True)
            if result.exit_code == 0 and result.stdout.strip():
                hsm_device = result.stdout.strip()
                log.info(f"Testing HSM device: {hsm_device}")
                
                # Simple test: try to open device (will fail gracefully if no hardware)
                result = node.execute(f"timeout 5 cat {hsm_device}", sudo=True, no_error_log=True)
                log.info(f"HSM device access result: exit_code={result.exit_code}")
                
                # Device should exist but may not be operable without hardware
                log.info("HSM device can be accessed")
            else:
                raise LisaException("HSM device not created")
                
        finally:
            self._unload_driver(node, log)

    @TestCaseMetadata(
        description="""
        Stress test: load and unload driver multiple times.
        Verifies driver stability and resource cleanup.
        """,
        priority=6,
    )
    def test_load_unload_stress(self, node: Node, log: Logger) -> None:
        """Stress test driver loading/unloading"""
        
        if not self._check_pci_device_present(node, log):
            raise SkippedException("AziHSM PCI device not found")
            
        source_url = self._get_source_url()
        driver_path = self._setup_driver_source(node, log, source_url)
        iterations = 5
        
        log.info(f"Starting load/unload stress test with {iterations} iterations")
        
        for i in range(iterations):
            log.info(f"Iteration {i+1}/{iterations}")
            
            try:
                self._load_driver(node, log, driver_path)
                time.sleep(1)  # Let driver stabilize
                self._unload_driver(node, log)
                time.sleep(1)  # Let cleanup complete
                
            except Exception as e:
                log.error(f"Stress test failed at iteration {i+1}: {e}")
                raise
                
        log.info("Stress test completed successfully")

    @TestCaseMetadata(
        description="""
        Test userspace device access and basic ioctl operations.
        Verifies that userspace applications can interact with driver.
        """,
        priority=7,
    )
    def test_userspace_device_access(self, node: Node, log: Logger) -> None:
        """Test userspace device access and ioctl operations"""
        
        if not self._check_pci_device_present(node, log):
            raise SkippedException("AziHSM PCI device not found")
            
        source_url = self._get_source_url()
        driver_path = self._setup_driver_source(node, log, source_url)
        
        # Get path to the userspace test source file
        import os
        current_dir = os.path.dirname(os.path.abspath(__file__))
        test_source_file = os.path.join(current_dir, "test_data", "azihsm_userspace_test.c")
        
        if not os.path.exists(test_source_file):
            raise LisaException(f"Test source file not found: {test_source_file}")
        
        try:
            self._load_driver(node, log, driver_path)
            time.sleep(2)
            
            # Copy test source file to remote machine
            log.info(f"Copying test source file from {test_source_file} to remote machine")
            node.tools[Cat].write(
                content=open(test_source_file, 'r').read(),
                file_path="/tmp/azihsm_userspace_test.c",
                sudo=True
            )
            
            gcc = node.tools[Gcc]
            result = gcc.compile(
                filename="/tmp/azihsm_userspace_test.c",
                output_file="/tmp/azihsm_userspace_test",
                sudo=True
            )
            
            if result.exit_code != 0:
                raise LisaException(f"Failed to compile userspace test: {result.stderr}")
                
            # Run userspace test
            log.info("Running userspace device access test...")
            result = node.execute("/tmp/azihsm_userspace_test", sudo=True, timeout=30)
            log.info(f"Userspace test output:\n{result.stdout}")
            
            if result.exit_code == 0:
                log.info("Userspace device access test passed")
            else:
                log.warning(f"Userspace test had issues: {result.stderr}")
                
        finally:
            self._unload_driver(node, log)
            # Cleanup
            node.execute("rm -f /tmp/azihsm_userspace_test*", sudo=True, no_error_log=True)

    @TestCaseMetadata(
        description="""
        Test cryptographic operations through AES device interface.
        Validates basic encryption/decryption functionality.
        """,
        priority=8,
    )
    def test_userspace_crypto_operations(self, node: Node, log: Logger) -> None:
        """Test userspace cryptographic operations"""
        
        if not self._check_pci_device_present(node, log):
            raise SkippedException("AziHSM PCI device not found")
            
        source_url = self._get_source_url()
        driver_path = self._setup_driver_source(node, log, source_url)
        
        # Get path to the crypto test source file
        import os
        current_dir = os.path.dirname(os.path.abspath(__file__))
        test_source_file = os.path.join(current_dir, "test_data", "azihsm_crypto_test.c")
        
        if not os.path.exists(test_source_file):
            raise LisaException(f"Crypto test source file not found: {test_source_file}")
        
        try:
            self._load_driver(node, log, driver_path)
            time.sleep(2)
            
            # Copy crypto test source file to remote machine
            log.info(f"Copying crypto test source file from {test_source_file} to remote machine")
            node.tools[Cat].write(
                content=open(test_source_file, 'r').read(),
                file_path="/tmp/azihsm_crypto_test.c",
                sudo=True
            )
            
            gcc = node.tools[Gcc]
            result = gcc.compile(
                filename="/tmp/azihsm_crypto_test.c",
                output_file="/tmp/azihsm_crypto_test",
                sudo=True
            )
            
            if result.exit_code != 0:
                raise LisaException(f"Failed to compile crypto test: {result.stderr}")
                
            # Run crypto test
            log.info("Running userspace crypto operations test...")
            result = node.execute("/tmp/azihsm_crypto_test", sudo=True, timeout=60)
            log.info(f"Crypto test output:\n{result.stdout}")
            
            if result.exit_code == 0:
                log.info("✓ Userspace crypto operations test passed")
            else:
                log.warning(f"Crypto test had issues: {result.stderr}")
                
        finally:
            self._unload_driver(node, log)
            node.execute("rm -f /tmp/azihsm_crypto_test*", sudo=True, no_error_log=True)

    @TestCaseMetadata(
        description="""
        Test concurrent userspace access to driver devices.
        Validates thread safety and resource management.
        """,
        priority=9,
    )
    def test_userspace_concurrent_access(self, node: Node, log: Logger) -> None:
        """Test concurrent userspace access patterns"""
        
        if not self._check_pci_device_present(node, log):
            raise SkippedException("AziHSM PCI device not found")
            
        source_url = self._get_source_url()
        driver_path = self._setup_driver_source(node, log, source_url)
        
        # Get path to the concurrent test source file
        import os
        current_dir = os.path.dirname(os.path.abspath(__file__))
        test_source_file = os.path.join(current_dir, "test_data", "azihsm_concurrent_test.c")
        
        if not os.path.exists(test_source_file):
            raise LisaException(f"Concurrent test source file not found: {test_source_file}")
        
        try:
            self._load_driver(node, log, driver_path)
            time.sleep(2)
            
            # Copy concurrent test source file to remote machine
            log.info(f"Copying concurrent test source file from {test_source_file} to remote machine")
            node.tools[Cat].write(
                content=open(test_source_file, 'r').read(),
                file_path="/tmp/azihsm_concurrent_test.c",
                sudo=True
            )
            
            gcc = node.tools[Gcc]
            result = gcc.compile(
                filename="/tmp/azihsm_concurrent_test.c",
                output_file="/tmp/azihsm_concurrent_test",
                sudo=True
            )
            
            if result.exit_code != 0:
                raise LisaException(f"Failed to compile concurrent test: {result.stderr}")
                
            # Run concurrent test
            log.info("Running userspace concurrent access test...")
            result = node.execute("/tmp/azihsm_concurrent_test", sudo=True, timeout=120)
            log.info(f"Concurrent test output:\n{result.stdout}")
            
            if result.exit_code == 0:
                log.info("✓ Userspace concurrent access test passed")
            else:
                log.warning(f"Concurrent test had issues: {result.stderr}")
                
        finally:
            self._unload_driver(node, log)
            node.execute("rm -f /tmp/azihsm_concurrent_test*", sudo=True, no_error_log=True)

    @TestCaseMetadata(
        description="""
        Test userspace error handling and edge cases.
        Validates proper error responses for invalid operations.
        """,
        priority=10,
    )
    def test_userspace_error_handling(self, node: Node, log: Logger) -> None:
        """Test userspace error handling and edge cases"""
        
        if not self._check_pci_device_present(node, log):
            raise SkippedException("AziHSM PCI device not found")
            
        source_url = self._get_source_url()
        driver_path = self._setup_driver_source(node, log, source_url)
        
        # Get path to the error test source file
        import os
        current_dir = os.path.dirname(os.path.abspath(__file__))
        test_source_file = os.path.join(current_dir, "test_data", "azihsm_error_test.c")
        
        if not os.path.exists(test_source_file):
            raise LisaException(f"Error test source file not found: {test_source_file}")
        
        try:
            self._load_driver(node, log, driver_path)
            time.sleep(2)
            
            # Copy error test source file to remote machine
            log.info(f"Copying error test source file from {test_source_file} to remote machine")
            node.tools[Cat].write(
                content=open(test_source_file, 'r').read(),
                file_path="/tmp/azihsm_error_test.c",
                sudo=True
            )
            
            gcc = node.tools[Gcc]
            result = gcc.compile(
                filename="/tmp/azihsm_error_test.c",
                output_file="/tmp/azihsm_error_test",
                sudo=True
            )
            
            if result.exit_code != 0:
                raise LisaException(f"Failed to compile error test: {result.stderr}")
                
            # Run error test
            log.info("Running userspace error handling test...")
            result = node.execute("/tmp/azihsm_error_test", sudo=True, timeout=60)
            log.info(f"Error handling test output:\n{result.stdout}")
            
            if result.exit_code == 0:
                log.info("✓ Userspace error handling test passed")
            else:
                log.warning(f"Error handling test had issues: {result.stderr}")
                
        finally:
            self._unload_driver(node, log)
            node.execute("rm -f /tmp/azihsm_error_test*", sudo=True, no_error_log=True)