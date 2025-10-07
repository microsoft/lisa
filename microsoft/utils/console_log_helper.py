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


def configure_console_logging(
    node: Node,
    log: Logger,
    loglevel: int = 8,
    persistent: bool = False,
) -> None:
    """
    Configure kernel console logging to ensure verbose output is captured.

    This function sets the kernel printk log level to ensure all kernel messages
    are sent to the console device and can be captured by serial console loggers.

    Args:
        node: The target node to configure
        log: Logger instance for detailed logging
        loglevel: Kernel log level (0-8, default 8 for maximum verbosity)
                  0 = emergency only, 8 = debug and higher
        persistent: If True, also configure GRUB to persist across reboots

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
        configure_console_logging(node, log, loglevel=8, persistent=False)

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
