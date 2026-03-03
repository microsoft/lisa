Use LISA docker image on Windows
=================================

This guide will walk you through using the LISA Docker image on a Windows system.

Quick Start with quick-container.ps1 (Recommended)
----------------------------------------------------

The ``quick-container.ps1`` script handles everything automatically — including
installing Docker CE if it is not already installed. No need to install Docker
Desktop or any other tools beforehand.

1. **Download the script** (run PowerShell as Administrator):

.. code:: powershell

   Invoke-WebRequest -Uri "https://raw.githubusercontent.com/microsoft/lisa/main/installers/quick-container.ps1" -OutFile "quick-container.ps1"

2. **Install Docker CE and launch an interactive container**:

.. code:: powershell

   .\quick-container.ps1 -InstallDocker -Interactive

3. **Run LISA with an Azure subscription**:

.. code:: powershell

   $token = az account get-access-token --query accessToken -o tsv
   .\quick-container.ps1 -InstallDocker -Runbook lisa/microsoft/runbook/azure.yml `
       -SubscriptionId YOUR_SUBSCRIPTION_ID -Token $token

.. note::

   The ``-InstallDocker`` flag is only needed the first time. On subsequent
   runs, you can omit it — the script will detect that Docker is already
   installed.

Manual Docker Setup
--------------------

If you prefer to install Docker yourself, you can use Docker Desktop or Docker
CE, then run containers directly.

Install Docker Desktop on Windows
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

You can download Docker Desktop from the `Docker website <https://www.docker.com/products/docker-desktop>`__.

Start Docker service
^^^^^^^^^^^^^^^^^^^^^

After installing Docker, open the Docker Desktop application to start the Docker service. Or use the following command to  launch and start the Docker service.

.. code:: powershell

    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"

Launch LISA container
^^^^^^^^^^^^^^^^^^^^^^

Use below command to launch the LISA container.

.. code:: powershell

   docker run --rm -i mcr.microsoft.com/lisa/runtime:latest lisa -r ./examples/runbook/hello_world.yml

Mount local files into the container
--------------------------------------

To override files inside the container (e.g., for testing a code fix), use the
``-v`` flag to mount a local **directory** into the container.

.. important::

   Windows containers only support mounting **directories**, not individual
   files. Mount the parent directory instead.

.. code:: powershell

   # Mount local lisa\util directory to override container files
   docker run --rm -i `
       -v C:\code\lisa\lisa\util:C:\app\lisa\lisa\util `
       mcr.microsoft.com/lisa/runtime:latest `
       lisa -r ./examples/runbook/hello_world.yml

If using ``quick-container.ps1``, pass the mount via ``-ExtraArgs``:

.. code:: powershell

   .\quick-container.ps1 -Runbook lisa/microsoft/runbook/azure.yml `
       -SubscriptionId xxx -Token $token `
       -ExtraArgs "-v C:\code\lisa\lisa\util:C:\app\lisa\lisa\util"
