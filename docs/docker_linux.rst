Use LISA docker image on Linux
===============================

This guide provides two ways to run LISA in Docker on Linux:

- **Option A: Quick Container Script** — automated, recommended for most users
- **Option B: Manual Setup** — step-by-step commands if you prefer full control

.. contents:: Table of Contents
   :local:
   :depth: 2

Option A: Quick Container Script (Recommended)
------------------------------------------------

The ``quick-container.sh`` script handles everything — installing Docker,
pulling images, mounting logs, and running LISA.

Step 1: Download the script
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: bash

   curl -fsSL https://raw.githubusercontent.com/microsoft/lisa/main/quick-container.sh -o quick-container.sh
   chmod +x quick-container.sh

If you have already cloned the LISA repository, the script is at the repository
root and you can skip this step.

Step 2: Install Docker (if needed)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: bash

   sudo bash quick-container.sh --install-docker --interactive

This detects your Linux distribution and installs Docker automatically.
You can also install Azure CLI at the same time:

.. code:: bash

   sudo bash quick-container.sh --install-docker --install-azcli

Step 3: Run LISA
~~~~~~~~~~~~~~~~~

**Quick start with built-in runbook:**

.. code:: bash

   sudo bash quick-container.sh -r lisa/microsoft/runbook/azure.yml \
       -v subscription_id:xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

**With Azure token authentication (recommended):**

.. code:: bash

   export LISA_azure_arm_access_token=$(az account get-access-token --query accessToken -o tsv)
   sudo bash quick-container.sh -r lisa/microsoft/runbook/azure.yml \
       --subscription-id xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx \
       --token "$LISA_azure_arm_access_token"

**With external runbook file:**

.. code:: bash

   sudo bash quick-container.sh -r ./my-runbook.yml

**Start an interactive shell:**

.. code:: bash

   sudo bash quick-container.sh -i

**With multiple LISA variables:**

.. code:: bash

   sudo bash quick-container.sh -r lisa/microsoft/runbook/azure.yml \
       -v subscription_id:xxx \
       -v location:westus2 \
       -v vm_size:Standard_DS2_v2

Script options reference
~~~~~~~~~~~~~~~~~~~~~~~~~

- ``-r, --runbook PATH`` — Path to runbook file (external or container internal)
- ``-v, --variable KEY:VALUE`` — LISA variable (can be used multiple times)
- ``-l, --log-path PATH`` — Local directory to save LISA logs (default: ``./lisa-logs``)
- ``--subscription-id ID`` — Azure subscription ID shortcut
- ``--token TOKEN`` — Azure access token shortcut
- ``--pull`` — Force pull latest image (default: use local image)
- ``--install-docker`` — Install Docker if not present
- ``--install-azcli`` — Install Azure CLI if not present
- ``-i, --interactive`` — Start an interactive shell
- ``-m, --mount PATH`` — Mount a local directory at /workspace
- ``-n, --name NAME`` — Custom container name (default: lisa-runner)
- ``-k, --keep`` — Keep container after exit
- ``--image IMAGE`` — Use custom Docker image
- ``--extra-args ARGS`` — Pass extra arguments to docker run
- ``-h, --help`` — Show help message

**Log files:**

By default, LISA logs are automatically saved to ``./lisa-logs/``. After running
tests:

.. code:: bash

   ls -la ./lisa-logs/log/
   cat ./lisa-logs/log/lisa-*.log

Save logs to a custom directory:

.. code:: bash

   sudo bash quick-container.sh -r lisa/microsoft/runbook/azure.yml \
       --log-path ./my-test-logs

Force pull the latest image:

.. code:: bash

   sudo bash quick-container.sh --pull -r lisa/microsoft/runbook/azure.yml

For full documentation:

.. code:: bash

   sudo bash quick-container.sh --help


Option B: Manual Setup
-----------------------

If you prefer to set up Docker and run LISA containers yourself, follow
the steps below.

Step 1: Install Docker
~~~~~~~~~~~~~~~~~~~~~~~~

On Ubuntu:

.. code:: bash

   sudo apt update
   sudo apt install docker.io -y

On Azure Linux:

.. code:: bash

   sudo tdnf update
   sudo tdnf install -y moby-engine moby-cli

Step 2: Start Docker service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: bash

   sudo systemctl start docker

Step 3: Configure Docker permissions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Add the current user to the "docker" group to run Docker without sudo:

.. code:: bash

   sudo usermod -aG docker $USER

Apply the group change immediately without logging out:

.. code:: bash

   newgrp docker

Step 4: Run LISA container
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: bash

   docker run --rm -i mcr.microsoft.com/lisa/runtime:latest \
       lisa -r lisa/examples/runbook/hello_world.yml


Develop with Dev Containers
----------------------------

For developers who want to contribute to LISA or develop test cases, see
:doc:`dev_containers` for instructions on using VS Code Dev Containers with all
dependencies pre-configured.
