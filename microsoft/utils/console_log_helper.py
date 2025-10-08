# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""
Helper utilities for configuring guest kernel console logging.

This module provides functions to ensure guest VMs produce verbose console output
that can be captured by serial console loggers. Common issues include:
- Low kernel log levels (default may only show critical messages)
- "quiet" kernel boot parameter suppressing boot logs
- Missing console= kernel parameter directing output to serial device
"""

from typing import Optional

from lisa import Logger, Node
from lisa.operating_system import Posix
from lisa.util import LisaException


def _read_file(node: Node, path: str) -> str:
    """
    Read a file from the node, returning empty string on failure.

    Args:
        node: The target node
        path: Path to the file to read

    Returns:
        File contents or empty string if read fails
    """
    result = node.execute(f"cat {path}", sudo=True, shell=True)
    return result.stdout if result.exit_code == 0 else ""


def _parse_active_consoles(text: str) -> dict[str, str]:
    """
    Parse /proc/consoles to extract active console devices and their flags.

    /proc/consoles format (one device per line):
        ttyS0    -W- (EC p a)    4:64
        hvc0     -W- (EC p  )   229:0

    Returns:
        Dict mapping device name to flags string (e.g., {"hvc0": "-W-"})
    """
    active = {}
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        dev = parts[0]
        flags = parts[1] if len(parts) > 1 else ""
        active[dev] = flags
    return active


def _guess_console_device(node: Node) -> Optional[str]:
    """
    Guess the expected console device by checking /proc/consoles.

    Returns the first write-enabled console device found.

    Args:
        node: The target node

    Returns:
        Device name (e.g., "hvc0", "ttyS0") or None if nothing found
    """
    # Check /proc/consoles to see what's actually active and write-enabled
    active_text = _read_file(node, "/proc/consoles")
    active = _parse_active_consoles(active_text)

    # Return the first write-enabled console (checking in priority order)
    for dev in ("hvc0", "ttyS0", "ttyS1"):
        flags = active.get(dev, "")
        if "W" in flags:  # Write-enabled
            return dev

    return None


def _assert_kernel_console_wired(
    node: Node, log: Logger, expected_console: Optional[str] = None
) -> None:
    """
    Verify that the kernel is configured to send output to the serial console.

    This checks:
    1. /proc/cmdline has console= parameter
    2. The expected console device is listed in cmdline
    3. /proc/consoles shows the device is active and write-enabled

    Fails fast with LisaException if console is not properly wired.

    Args:
        node: The target node to check
        log: Logger instance
        expected_console: Expected console device (e.g., "hvc0", "ttyS0")
                         If None, will auto-detect based on /dev presence

    Raises:
        LisaException: If kernel console is not properly configured
    """
    cmdline = _read_file(node, "/proc/cmdline").strip()

    # Extract all console= parameters from cmdline
    # Example: console=hvc0,115200 console=tty0 -> ["hvc0", "tty0"]
    consoles = [p.split("=", 1)[1] for p in cmdline.split() if p.startswith("console=")]
    consoles = [c.split(",")[0] for c in consoles]  # Strip speed like ,115200
    consoles_set = set(consoles)

    active_text = _read_file(node, "/proc/consoles")
    active = _parse_active_consoles(active_text)

    # Determine expected console (explicit or auto-detect)
    guess = expected_console or _guess_console_device(node)

    log.debug(f"Kernel cmdline: {cmdline}")
    log.debug(f"/proc/consoles:\n{active_text}")

    # Fail fast if no console= parameter at all
    if not consoles_set:
        raise LisaException(
            "Kernel cmdline has no 'console=' parameter. "
            "Serial console logs will be empty. "
            "Add e.g. 'console=hvc0,115200' (virtio-console/Cloud Hypervisor) "
            "or 'console=ttyS0,115200' (UART/QEMU)."
        )

    # Fail fast if expected console is not in cmdline
    if guess and guess not in consoles_set:
        raise LisaException(
            f"Kernel cmdline consoles {sorted(consoles_set)} do not include "
            f"expected '{guess}'. "
            f"Serial console logs will be empty. "
            f"Fix kernel cmdline to include 'console={guess},115200'."
        )

    # NEW: Verify the console is actually active and write-enabled
    if guess:
        flags = active.get(guess, "")
        if not flags:
            raise LisaException(
                f"Expected console '{guess}' not present in /proc/consoles. "
                "Driver may be missing or device not initialized. "
                f"Active consoles: {list(active.keys())}"
            )
        if "W" not in flags:
            raise LisaException(
                f"Console '{guess}' present but not write-enabled (flags='{flags}'). "
                "Kernel output will not be captured."
            )

    # Build dict of active consoles that are in cmdline for logging
    active_cmdline_consoles = {k: v for k, v in active.items() if k in consoles_set}

    log.info(
        f"✓ Kernel console wired correctly: "
        f"cmdline={sorted(consoles_set)}, "
        f"active={active_cmdline_consoles}, "
        f"expected={guess or 'auto'}"
    )


def configure_console_logging(
    node: Node,
    log: Logger,
    loglevel: int = 8,
    persistent: bool = False,
    expected_console: Optional[str] = None,
) -> None:
    """
    Configure kernel console logging to ensure verbose output is captured.

    This function:
    1. Verifies kernel is wired to serial console (fails fast if not)
    2. Sets kernel printk log level for verbose output

    CRITICAL: The kernel MUST have console=<device> in boot parameters.
    This function will raise LisaException if not properly configured.

    Args:
        node: The target node to configure
        log: Logger instance for detailed logging
        loglevel: Kernel log level (0-8, default 8 for maximum verbosity)
                  0 = emergency only, 8 = debug and higher
        persistent: If True, also configure GRUB to persist across reboots
        expected_console: Expected console device (e.g., "hvc0" for Cloud Hypervisor,
                         "ttyS0" for QEMU). If None, will auto-detect.

    Raises:
        LisaException: If kernel console is not properly configured

    Common log levels:
        0 (KERN_EMERG)   : System is unusable
        1 (KERN_ALERT)   : Action must be taken immediately
        2 (KERN_CRIT)    : Critical conditions
        3 (KERN_ERR)     : Error conditions
        4 (KERN_WARNING) : Warning conditions
        5 (KERN_NOTICE)  : Normal but significant
        6 (KERN_INFO)    : Informational
        7 (KERN_DEBUG)   : Debug-level messages
        8                : All messages including verbose debug

    Example:
        # Before running stress tests, enable verbose console logging
        # This will fail fast if console= is not in kernel cmdline
        configure_console_logging(node, log, loglevel=8, expected_console="hvc0")

        # Run test that may cause crashes/panics
        stress_test.run()

        # Console logs will now contain detailed kernel output
    """
    if not isinstance(node.os, Posix):
        log.debug(
            f"Skipping console logging configuration for non-Posix OS: {node.os.name}"
        )
        return

    log.info(f"Configuring console logging with loglevel={loglevel}")

    # FAIL FAST: Verify kernel console is properly wired
    # This will raise LisaException if console= is missing or wrong
    _assert_kernel_console_wired(node, log, expected_console)

    # Set current kernel printk log level (immediate effect, not persistent)
    # Format: console_loglevel default_message_loglevel minimum_console_loglevel
    #         default_console_loglevel
    # Setting all to the same level ensures everything goes to console
    printk_value = f"{loglevel} {loglevel} 1 {loglevel}"
    result = node.execute(
        f'echo "{printk_value}" | sudo tee /proc/sys/kernel/printk',
        sudo=True,
        shell=True,
    )

    if result.exit_code == 0:
        log.info(
            f"Successfully set kernel printk level to {loglevel}. "
            f"Console will now show verbose kernel messages."
        )
    else:
        log.warning(
            f"Failed to set kernel printk level: {result.stderr}. "
            f"Console logs may be incomplete."
        )

    if persistent:
        _configure_grub_console_logging(node, log, loglevel)


def _configure_grub_console_logging(
    node: Node,
    log: Logger,
    loglevel: int = 8,
) -> None:
    """
    Configure GRUB to enable verbose console logging on every boot.

    This modifies /etc/default/grub to:
    - Remove 'quiet' parameter (suppresses boot messages)
    - Add 'loglevel=X' parameter (sets kernel log verbosity)
    - Ensure console output goes to serial device

    Args:
        node: The target node to configure
        log: Logger instance for detailed logging
        loglevel: Kernel log level to set in GRUB cmdline
    """
    if not isinstance(node.os, Posix):
        return

    log.info("Configuring GRUB for persistent verbose console logging")

    grub_file = "/etc/default/grub"

    # Check if GRUB config exists
    result = node.execute(f"test -f {grub_file}", sudo=True)
    if result.exit_code != 0:
        log.warning(
            f"GRUB config file {grub_file} not found. "
            f"Skipping persistent console logging configuration."
        )
        return

    # Read current GRUB configuration
    result = node.execute(f"sudo cat {grub_file}", sudo=True)
    if result.exit_code != 0:
        log.warning(f"Failed to read {grub_file}: {result.stderr}")
        return

    # Modify GRUB_CMDLINE_LINUX_DEFAULT to remove 'quiet' and add loglevel
    log.info("Backing up GRUB configuration")
    node.execute(f"sudo cp {grub_file} {grub_file}.backup", sudo=True)

    # Remove 'quiet' and add loglevel using sed
    commands = [
        # Remove 'quiet' parameter
        f"sudo sed -i 's/quiet//g' {grub_file}",
        # Remove existing loglevel parameter if present
        f"sudo sed -i 's/loglevel=[0-9]//g' {grub_file}",
        # Add new loglevel parameter to GRUB_CMDLINE_LINUX_DEFAULT
        f"sudo sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT=\"/GRUB_CMDLINE_LINUX_DEFAULT=\"loglevel={loglevel} /' {grub_file}",  # noqa: E501
    ]

    for cmd in commands:
        result = node.execute(cmd, sudo=True, shell=True)
        if result.exit_code != 0:
            log.warning(f"Failed to modify GRUB config: {result.stderr}")
            # Try to restore backup
            node.execute(f"sudo cp {grub_file}.backup {grub_file}", sudo=True)
            return

    # Update GRUB
    log.info("Updating GRUB configuration")
    update_grub_cmd = _get_update_grub_command(node, log)
    if update_grub_cmd:
        result = node.execute(update_grub_cmd, sudo=True)
        if result.exit_code == 0:
            log.info(
                "Successfully updated GRUB. Verbose console logging will "
                "persist across reboots."
            )
            log.info(
                "Note: Changes will take effect on next reboot. "
                "For immediate effect, use configure_console_logging() "
                "without persistent=True."
            )
        else:
            log.warning(f"Failed to update GRUB: {result.stderr}")
            # Restore backup
            node.execute(f"sudo cp {grub_file}.backup {grub_file}", sudo=True)
    else:
        log.warning("Could not determine GRUB update command for this distribution")


def _get_update_grub_command(node: Node, log: Logger) -> Optional[str]:
    """
    Determine the correct GRUB update command for the distribution.

    Different distributions use different commands:
    - Debian/Ubuntu: update-grub or update-grub2
    - RHEL/CentOS: grub2-mkconfig -o /boot/grub2/grub.cfg
    - SUSE: grub2-mkconfig -o /boot/grub2/grub.cfg

    Returns:
        The appropriate update command, or None if cannot be determined
    """
    # Try common commands in order of preference
    commands = [
        "update-grub",
        "update-grub2",
        "grub2-mkconfig -o /boot/grub2/grub.cfg",
        "grub-mkconfig -o /boot/grub/grub.cfg",
    ]

    for cmd in commands:
        # Check if command exists
        check_cmd = cmd.split()[0]  # Get just the command name
        result = node.execute(f"which {check_cmd}", sudo=True)
        if result.exit_code == 0:
            log.debug(f"Using GRUB update command: {cmd}")
            return cmd

    return None


def verify_console_logging_config(node: Node, log: Logger) -> bool:
    """
    Verify that console logging is properly configured.

    Checks:
    - Current kernel printk log level
    - GRUB configuration for persistent settings

    Args:
        node: The target node to check
        log: Logger instance for detailed logging

    Returns:
        True if console logging is configured for verbose output, False otherwise
    """
    if not isinstance(node.os, Posix):
        log.debug(f"Cannot verify console logging for non-Posix OS: {node.os.name}")
        return False

    # Check current printk level
    result = node.execute("cat /proc/sys/kernel/printk", sudo=True)
    if result.exit_code == 0:
        levels = result.stdout.split()
        if len(levels) >= 1:
            current_level = int(levels[0])
            log.info(f"Current kernel console loglevel: {current_level}")
            if current_level >= 7:
                log.info("Console logging is configured for verbose output")
                return True
            else:
                log.warning(
                    f"Console loglevel ({current_level}) is low. "
                    f"Consider increasing to 7 or 8 for verbose output."
                )
                return False

    log.warning(f"Failed to read kernel printk level: {result.stderr}")
    return False
