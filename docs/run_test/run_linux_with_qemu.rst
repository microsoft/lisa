Running Tests with Linux and Qemu
=================================

In this document you will find instruction to run tests using Qemu on Linux. 
Qemu is virtualization software to create VM's locally on Linux. We use Qemu
to ensure that the tests do not affect any local distro settings. Follow the
steps below to configure your local computer and run LISA test against
Qemu VM.

#. Create Qemu qcow2 image

   Make sure either `Azure CLI
   <https://docs.microsoft.com/en-us/cli/azure/install-azure-cli>`__ or `Azure
   PowerShell
   <https://docs.microsoft.com/en-us/powershell/azure/install-az-ps>`__ has been
   installed on your local computer. Then log in to your Azure subscription to
   authenticate your current session. LISA also supports other Azure
   authentications, for more information, please refer to :doc: `runbook
   reference <runbook>`.

   Here, let’s choose ``Azure CLI`` for the setup. You should see a page
   pop up and all your Azure subscriptions shown in console after
   running the following command.

   .. code:: bash

      az login

# Run LISA