Develop LISA using VS Code Dev Containers
==========================================

For developers who want to contribute to LISA or develop test cases, you can use VS Code Dev Containers 
to work inside a Docker container with all dependencies pre-configured. This approach works on both 
Linux and Windows.

Prerequisites
-------------

1. Install `Visual Studio Code <https://code.visualstudio.com/>`__
2. Install the `Dev Containers extension <https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers>`__
3. Ensure Docker is installed and running:
   
   - On Linux: See :doc:`docker_linux`
   - On Windows: See :doc:`docker_windows`

Using the Dev Container
------------------------

1. Clone the LISA repository:

   .. code:: bash

      git clone https://github.com/microsoft/lisa.git
      cd lisa

2. Open the repository in VS Code:

   .. code:: bash

      code .

3. When VS Code opens, you should see a prompt asking if you want to "Reopen in Container". Click **Reopen in Container**.

   Alternatively, you can manually open the container:
   
   - Press ``F1`` or ``Ctrl+Shift+P`` to open the command palette
   - Type "Dev Containers: Reopen in Container" and select it

4. VS Code will build the Docker container and reopen the workspace inside it. This may take a few minutes 
   the first time as it downloads the base image and installs all dependencies.

5. Once inside the container, you have a full development environment with:

   - Python 3 with all LISA dependencies installed
   - Python extensions (Python language support and Pylance for IntelliSense)
   - Your workspace mounted at ``/app/lisa`` from your host machine
   - All changes are persisted to your local filesystem
   - Your source code is synced between the container and host machine, so you can use Git directly on your host system.

Rebuilding the Container
-------------------------

If you make changes to the ``.devcontainer/devcontainer.json`` file, the Dockerfile, or Python dependencies 
(``pyproject.toml``), you'll need to rebuild the container:

1. Press ``F1`` or ``Ctrl+Shift+P`` to open the command palette
2. Type "Dev Containers: Rebuild Container" and select it
3. VS Code will rebuild the container with your changes and reopen the workspace

Alternatively, use "Dev Containers: Rebuild and Reopen in Container" to rebuild and reopen in one step.

Debugging Support
-----------------

The dev container fully supports VS Code's debugging capabilities. You can set breakpoints, step through code, 
and use all standard debugging features just as you would in a local development environment.

Benefits
--------

Dev Containers provide a consistent development environment across all platforms without requiring local 
installation of dependencies.
