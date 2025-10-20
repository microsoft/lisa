# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""
Console diagnostics utilities for debugging serial console logging issues.
"""

from typing import Optional

from lisa.node import Node
from lisa.util.logger import Logger


def dump_console_routing(node: Node, log: Logger) -> None:
    """
    Dump guest's console routing configuration for debugging.
    
    This helps diagnose why console logs might be empty by showing:
    - Kernel cmdline (should have console=ttyS0 or console=hvc0)
    - Getty services status (serial-getty@ttyS0 or serial-getty@hvc0)
    - Any console-related systemd units
    """
    log.info("[CONSOLE DIAG] Dumping guest console routing configuration...")
    
    # 1. Check kernel cmdline
    try:
        result = node.execute("cat /proc/cmdline", shell=True, sudo=False)
        if result.exit_code == 0:
            cmdline = result.stdout.strip()
            log.info(f"[CONSOLE DIAG] Kernel cmdline: {cmdline}")
            
            # Check for console parameters
            if "console=ttyS0" in cmdline:
                log.info("[CONSOLE DIAG] ✓ Found console=ttyS0 (UART serial)")
            elif "console=hvc0" in cmdline:
                log.info("[CONSOLE DIAG] ✓ Found console=hvc0 (virtio-console)")
            else:
                log.warning(
                    "[CONSOLE DIAG] ⚠ No console=ttyS0 or console=hvc0 in cmdline! "
                    "Output may not reach serial console."
                )
            
            if "earlycon" in cmdline:
                log.info("[CONSOLE DIAG] ✓ Found earlycon (early boot messages enabled)")
            else:
                log.info("[CONSOLE DIAG] No earlycon found (early boot messages may be missing)")
                
        else:
            log.warning(f"[CONSOLE DIAG] Failed to read /proc/cmdline: {result.stderr}")
    except Exception as e:
        log.warning(f"[CONSOLE DIAG] Exception reading cmdline: {e}")
    
    # 2. Check serial-getty@ttyS0 service
    try:
        result = node.execute(
            "systemctl status serial-getty@ttyS0.service 2>&1 || true",
            shell=True,
            sudo=False
        )
        if result.stdout:
            log.info(f"[CONSOLE DIAG] serial-getty@ttyS0 status:\n{result.stdout[:500]}")
            if "active (running)" in result.stdout.lower():
                log.info("[CONSOLE DIAG] ✓ serial-getty@ttyS0 is running")
            elif "inactive" in result.stdout.lower() or "not found" in result.stdout.lower():
                log.info("[CONSOLE DIAG] serial-getty@ttyS0 is not active (may be using hvc0)")
    except Exception as e:
        log.warning(f"[CONSOLE DIAG] Exception checking serial-getty@ttyS0: {e}")
    
    # 3. Check serial-getty@hvc0 service
    try:
        result = node.execute(
            "systemctl status serial-getty@hvc0.service 2>&1 || true",
            shell=True,
            sudo=False
        )
        if result.stdout:
            log.info(f"[CONSOLE DIAG] serial-getty@hvc0 status:\n{result.stdout[:500]}")
            if "active (running)" in result.stdout.lower():
                log.info("[CONSOLE DIAG] ✓ serial-getty@hvc0 is running")
    except Exception as e:
        log.warning(f"[CONSOLE DIAG] Exception checking serial-getty@hvc0: {e}")
    
    # 4. Check available serial devices
    try:
        result = node.execute(
            "ls -la /dev/ttyS* /dev/hvc* 2>&1 || true",
            shell=True,
            sudo=False
        )
        if result.stdout:
            log.info(f"[CONSOLE DIAG] Available console devices:\n{result.stdout}")
    except Exception as e:
        log.warning(f"[CONSOLE DIAG] Exception listing console devices: {e}")
    
    # 5. Check dmesg for console initialization
    try:
        result = node.execute(
            "dmesg | grep -i 'console\\|serial\\|ttyS0\\|hvc0' | tail -20",
            shell=True,
            sudo=True
        )
        if result.stdout:
            log.info(f"[CONSOLE DIAG] Recent console messages from dmesg:\n{result.stdout}")
    except Exception as e:
        log.warning(f"[CONSOLE DIAG] Exception reading dmesg: {e}")
    
    log.info("[CONSOLE DIAG] Console routing dump complete")


def verify_early_output(node: Node, log: Logger, timeout: int = 5) -> bool:
    """
    Verify that the guest can output to the console by writing a test message.
    
    Returns True if we can successfully write and the system responds.
    """
    log.info("[CONSOLE DIAG] Verifying console output capability...")
    
    try:
        # Try to write something that should appear in console
        test_marker = "LISA_CONSOLE_TEST_MARKER_12345"
        result = node.execute(
            f'echo "{test_marker}" | tee /dev/kmsg',
            shell=True,
            sudo=True,
            timeout=timeout
        )
        
        if result.exit_code == 0:
            log.info(f"[CONSOLE DIAG] ✓ Successfully wrote test marker to /dev/kmsg")
            log.info(f"[CONSOLE DIAG] Check console logs for: {test_marker}")
            return True
        else:
            log.warning(
                f"[CONSOLE DIAG] Failed to write to /dev/kmsg: {result.stderr}"
            )
            return False
            
    except Exception as e:
        log.warning(f"[CONSOLE DIAG] Exception during console output test: {e}")
        return False
