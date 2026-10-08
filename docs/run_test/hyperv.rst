Run tests on a Hyper-V host
============================

The ``microsoft/runbook/hyperv/host_vhd.yml`` runbook creates a Linux guest VM
from an existing VHD or VHDX on a Windows Hyper-V host and runs LISA tests
against that guest. The default test case is ``smoke_test``.

Prerequisites
-------------

The Hyper-V host must have the Hyper-V role and management PowerShell module
installed. The account running LISA must be able to connect to the host through
OpenSSH and must have permission to create, start, stop, and delete Hyper-V VMs.
The account should be a member of ``Hyper-V Administrators`` or ``Administrators``.

The guest VHD or VHDX must already exist on the Hyper-V host, be bootable, and
have SSH enabled. The guest credentials passed to LISA must be valid. Use an
external Hyper-V virtual switch when the LISA controller is separate from the
Hyper-V host so that it can reach the guest IP address.

On the Hyper-V host, verify the required components and VHD before running:

.. code:: powershell

   Get-WindowsFeature Hyper-V, Hyper-V-PowerShell
   Get-Service sshd
   Get-VMSwitch
   Test-Path "C:\images\guest.vhdx"
   Get-VHD "C:\images\guest.vhdx"

To enable the OpenSSH server when permitted by the host policy:

.. code:: powershell

   Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
   Set-Service sshd -StartupType Automatic
   Start-Service sshd
   Enable-NetFirewallRule -Name OpenSSH-Server-In-TCP

Run the VHD runbook
--------------------

Run the command from the LISA repository. ``guest_vhd_path`` is a path on the
Hyper-V host, not a path on the LISA controller.

.. code:: powershell

   python -m lisa `
     -r .\microsoft\runbook\hyperv\host_vhd.yml `
     -v "hyperv_host_address:<HYPERV_HOST_IP_OR_FQDN>" `
     -v "hyperv_host_username:<HYPERV_HOST_USERNAME>" `
     -v "hyperv_host_password:<HYPERV_HOST_PASSWORD>" `
     -v "guest_vhd_path:C:\images\guest.vhdx" `
     -v "guest_username:<GUEST_USERNAME>" `
     -v "guest_password:<GUEST_PASSWORD>" `
     -v "hyperv_generation:2" `
     -v "vm_cpus:4" `
     -v "vm_memory_mb:8192" `
     -v "switch_name:<EXTERNAL_SWITCH_NAME>" `
     -v "test_case_name:smoke_test"

Do not place passwords in a checked-in runbook. Use an environment variable,
secret store, or an interactive command prompt when running locally.

Runbook variables
-----------------

``hyperv_host_address``
  Address or FQDN of the Windows Hyper-V host.

``hyperv_host_username`` and ``hyperv_host_password``
  OpenSSH credentials for the Hyper-V host.

``guest_vhd_path``
  Existing ``.vhd`` or ``.vhdx`` path on the Hyper-V host.

``guest_username`` and ``guest_password``
  Credentials LISA uses to connect to the deployed Linux guest.

``hyperv_generation``
  Use ``1`` for BIOS/MBR images and ``2`` for UEFI/GPT images. ARM64 guests
  generally require Generation 2.

``vm_cpus`` and ``vm_memory_mb``
  CPU count and startup memory for the guest VM.

``switch_name``
  Optional Hyper-V virtual switch. If omitted, LISA uses the host default switch.

``osdisk_size_in_gb``
  Defaults to ``0``, which does not resize the VHD. Set a value larger than the
  current VHD size only when the guest root partition supports online expansion.

``keep_environment``
  Defaults to ``no``. Set to ``always`` for debugging to retain the created VM.

Troubleshooting
---------------

If the Hyper-V host cannot be reached, validate SSH from the LISA controller:

.. code:: powershell

   ssh -l "<HYPERV_HOST_USERNAME>" <HYPERV_HOST_IP_OR_FQDN>

If LISA cannot connect to the guest after it starts, verify that the selected
virtual switch provides a route from the LISA controller to the guest. An
internal/default switch may require NAT port forwarding and is usually less
suitable for a controller on another computer.

If a VHD resize is required, verify its root device uses a partition naming
scheme supported by the guest OS. Keep ``osdisk_size_in_gb:0`` for pre-sized
Gen1 images with nonstandard root device names.