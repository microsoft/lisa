Use LISA docker image on Linux
===============================

This guide will walk you through using the LISA Docker image on a Linux system.

Install docker on Linux
-----------------------

The first steps are to install Docker on your system.

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

   docker run --rm -i mcr.microsoft.com/lisa/runtime:latest lisa -r ./examples/runbook/hello_world.yml
