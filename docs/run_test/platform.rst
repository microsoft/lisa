Run tests on different platforms
================================

-  `Run on Azure <#run-on-azure>`__
-  `Run on Azure without
   deployment <#run-on-azure-without-deployment>`__
-  `Run on Ready computers <#run-on-ready-computers>`__

Run on Azure
------------

Follow the same procedure in `Getting started with
Azure <quick_run.html>`__.

Run on Azure without deployment
-------------------------------

In addition to deploying a new Azure server and running tests, you can
skip the deployment phase and use existing resource group.

The advantage is that it can run all test cases of Azure. The shortage
is that the VM name is fixed, and it should be node-0, so each resource
group can put only one VM.

Run on Ready computers
----------------------

If you have prepared a Linux computer for testing, please run LISA with
``ready`` runbook:

1. Get the IP address of your computer for testing.

2. Get the SSH public/private key pair which can access this computer.

3. Run LISA with parameters below:

   .. code:: bash

      lisa -r ./microsoft/runbook/ready.yml -v public_address:<public address> -v "user_name:<user name>" -v "admin_private_key_file:<private key file>"

The advantage is it’s not related to any infra. The shortage is that,
some test cases won’t run in Ready platform, for example, test cases
cannot get serial log from a VM directly.

``ready`` runbook also supports tests which require multiple computers
(for example, networking testing); and, it supports password
authentication too. Learn more from `runbook
reference <runbook.html>`__.

For a comprehensive introduction to LISA supported test parameters and
runbook schema, please read `command-line
reference <command_line.html>`__ and `runbook
reference <runbook.html>`__.
