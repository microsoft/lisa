Use LISA docker image on Windows
=================================

This guide will walk you through using the LISA Docker image on a Windows system.

Install Docker Desktop on Windows
----------------------------------

The first steps are to install Docker on your system.

You can download Docker Desktop from the `Docker website <https://www.docker.com/products/docker-desktop>`__.

Start Docker service
--------------------

After installing Docker, open the Docker Desktop application to start the Docker service. Or use the following command to  launch and start the Docker service.

.. code:: powershell

    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"

Launch LISA container
-----------------------

Use below command to launch the LISA container.

.. code:: powershell

   docker run --rm -i mcr.microsoft.com/lisa/runtime:latest lisa -r ./examples/runbook/hello_world.yml
