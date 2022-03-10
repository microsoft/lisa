Run tests in Local VM
=====================

In this document you will find instruction to run tests locally. We will use
a VM to ensure that the tests do not affect any local distro settings. Follow
the steps below to configure your local computer and run LISA tests. The steps
can be followed on host machines running either windows or Linux.

#. Create a virtual machine following the below instructions:
   
   a. For Linux, start QEMU KVM in a ``Private Virtual Bridge`` network configuration.
   You can follow the instructions given `here
   <https://www.linux-kvm.org/page/Networking>`__
   
   b. For windows, start a VM using Hyper-V. You can follow the instructions given `here
   <https://docs.microsoft.com/en-us/virtualization/hyper-v-on-windows/quick-start/quick-create-virtual-machine>`__

#. Get IP address of the virtual machine

   Connect to VM and obtain the IP address of the guest VM. Run a simple ping test from host to
   ensure that the guest VM is accessible from the host.

   .. code:: bash

      ping "<guest ip address>"

#. Get/setup the SSH key pair which can access guest VM.

#. Use ready platform to run tests

   .. code:: bash

      lisa -r ./microsoft/runbook/ready.yml -v "public_address:<guest ip address>" -v "user_name:<user name>" -v "admin_private_key_file:<private key file>"