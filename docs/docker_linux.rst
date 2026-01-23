Use LISA docker image on Linux
===============================

This guide will walk you through using the LISA Docker image on a Linux system.

Install docker on Linux
-----------------------

The first steps are to install Docker on your system.

**Automatic Installation:**

Use the quick-container script to install Docker automatically:

.. code:: bash

   bash quick-container.sh --install-docker --interactive

**Manual Installation:**

On Ubuntu, you can install Docker with the following commands:

.. code:: bash

   sudo apt update
   sudo apt install docker.io -y

On Azure Linux, you can install Docker with the following commands:

.. code:: bash

   sudo tdnf update
   sudo tdnf install -y moby-engine moby-cli

Start Docker service
--------------------

After installing Docker, you can start the Docker service with the following command:

.. code:: bash

   sudo systemctl start docker

Managing Docker Permissions
---------------------------

Add the current user to the "docker" group to run Docker without sudo.

.. code:: bash

   sudo usermod -aG docker $USER

Apply the group change immediately wihout logging out and logging back in.

.. code:: bash

   newgrp docker

Launch LISA container
-----------------------

Use below command to launch the LISA container.

.. code:: bash

   docker run --rm -i mcr.microsoft.com/lisa/runtime:latest lisa -r lisa/examples/runbook/hello_world.yml


Quick Container Script
-----------------------

For easier container management, use the provided quick-container script. The script automatically:

- Uses local Docker images by default (faster startup)
- Mounts LISA logs to local directory ``./lisa-logs``
- Supports both external runbook files and container internal paths
- Handles Azure authentication with shortcuts

**Quick start with container internal runbook:**

.. code:: bash

   # Using container's built-in runbook
   bash quick-container.sh -r lisa/microsoft/runbook/azure.yml \
       -v subscription_id:xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

**With Azure token authentication (recommended):**

.. code:: bash

   export LISA_azure_arm_access_token=$(az account get-access-token --query accessToken -o tsv)
   bash quick-container.sh -r lisa/microsoft/runbook/azure.yml \
       --subscription-id xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx \
       --token "$LISA_azure_arm_access_token"

**With external runbook file:**

.. code:: bash

   bash quick-container.sh -r ./my-runbook.yml

**Save logs to custom directory:**

.. code:: bash

   bash quick-container.sh -r lisa/microsoft/runbook/azure.yml \
       --log-path ./my-test-logs

**Force pull latest image:**

.. code:: bash

   # By default uses local image (faster)
   # Use --pull to get latest version
   bash quick-container.sh --pull -r lisa/microsoft/runbook/azure.yml

**Install dependencies automatically:**

.. code:: bash

   # Install Docker and Azure CLI if not present
   bash quick-container.sh --install-docker --install-azcli

**Start an interactive shell:**

.. code:: bash

   bash quick-container.sh -i

**With multiple LISA variables:**

.. code:: bash

   bash quick-container.sh -r lisa/microsoft/runbook/azure.yml \
       -v subscription_id:xxx \
       -v location:westus2 \
       -v vm_size:Standard_DS2_v2

**Available options:**

- ``-r, --runbook PATH`` - Path to runbook file (external or container internal)
- ``-v, --variable KEY:VALUE`` - LISA variable (can be used multiple times)
- ``-l, --log-path PATH`` - Local directory to save LISA logs (default: ./lisa-logs)
- ``--subscription-id ID`` - Azure subscription ID shortcut
- ``--token TOKEN`` - Azure access token shortcut
- ``--pull`` - Force pull latest image (default: use local image)
- ``--install-docker`` - Install Docker if not present
- ``--install-azcli`` - Install Azure CLI if not present
- ``-i, --interactive`` - Start an interactive shell
- ``-m, --mount PATH`` - Mount a local directory at /workspace
- ``-n, --name NAME`` - Custom container name (default: lisa-runner)
- ``-k, --keep`` - Keep container after exit
- ``--image IMAGE`` - Use custom Docker image
- ``--extra-args ARGS`` - Pass extra arguments to docker run
- ``-h, --help`` - Show help message

**Log Files:**

By default, LISA logs are automatically saved to ``./lisa-logs/`` directory. After running tests:

.. code:: bash

   # View logs
   ls -la ./lisa-logs/log/
   
   # Check test results
   cat ./lisa-logs/log/lisa-*.log

For full documentation:

.. code:: bash

   bash quick-container.sh --help


Develop with Dev Containers
----------------------------

For developers who want to contribute to LISA or develop test cases, see :doc:`dev_containers` for instructions 
on using VS Code Dev Containers with all dependencies pre-configured.
