Install LISA on Linux
=====================

This guide provides two ways to install LISA on Linux:

- **Option A: Quick Installation Script** — automated, recommended for most users
- **Option B: Manual Installation** — step-by-step commands if you prefer full control

.. contents:: Table of Contents
   :local:
   :depth: 2

.. tip::

   For the fastest way to get started without local installation, see :doc:`docker_linux` for Docker-based usage.


Minimum System Requirements
---------------------------

1. Your favorite Linux distribution supporting Python 3.8 or above
2. Dual core processor
3. 4 GB system memory


Option A: Quick Installation Script (Recommended)
-------------------------------------------------

For a quick and automated installation, you can use the provided installation script:

.. code:: bash

   curl -sSL https://raw.githubusercontent.com/microsoft/lisa/main/quick-install.sh | bash

This script will:

- Detect your Linux distribution and version
- Install Python 3.12 (or use existing Python 3.8+)
- Install system dependencies based on your distribution
- Clone the LISA repository
- Install LISA with Azure and libvirt extensions

**For Ubuntu 24.04+:** The script automatically creates a virtual environment to comply with PEP 668.

**Customization options:**

.. code:: bash

   # Custom installation path (use sudo for system paths like /opt)
   sudo bash quick-install.sh --install-path /opt/lisa

   # Specific Python version
   bash quick-install.sh --python-version 3.12

   # Specific git branch
   bash quick-install.sh --branch develop

   # Skip Python installation
   bash quick-install.sh --skip-python

For help:

.. code:: bash

   bash quick-install.sh --help

If you prefer manual installation or need to customize your setup, continue with Option B below.


Option B: Manual Installation
-----------------------------

The following commands assume Ubuntu or Azure Linux is being used.

<<<<<<< HEAD
.. tip::

   For the fastest way to get started without local installation, see :doc:`docker_linux` for Docker-based usage.


=======
>>>>>>> 52ac9e751 (Refine doc for installing lisa)
Install Python on Linux
~~~~~~~~~~~~~~~~~~~~~~~

LISA has been tested to work with `Python >=3.8 64-bit <https://www.python.org/>`__.
Python 3.12 is recommended.
If you find that LISA is not compatible with a supported version,
`please file an issue <https://github.com/microsoft/lisa/issues/new>`__.

To check which version of Python is used on your system, run the following:

.. code:: bash

   python3 --version

If you need to install a different Python package, there are likely packaged versions for
your distro.

Here is an example to install Python 3.12 on Ubuntu 22.04

.. code:: bash

   sudo apt update
   sudo apt install python3.12 python3.12-dev -y

For Azure Linux, Python installation is included in the system dependencies section below and does not need to be installed separately.


Install system dependencies
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Run the command below to install the dependencies on Ubuntu:

.. code:: bash

   sudo apt install git gcc libgirepository1.0-dev libcairo2-dev qemu-utils libvirt-dev python3-pip python3-venv -y

Run the command below to install the dependencies on Azure Linux:

.. code:: bash

   sudo tdnf install -y git gcc gobject-introspection-devel cairo-gobject cairo-devel pkg-config libvirt-devel python3-devel python3-pip python3-virtualenv build-essential cairo-gobject-devel curl wget tar azure-cli ca-certificates

Run the command below to install the dependencies on Fedora 41 & above:

.. code:: bash

   sudo dnf install -y git gcc gobject-introspection-devel cairo-devel qemu-img libvirt-devel python3-pip python3-virtualenv -y

If you're using a different distribution or python version, adjust the command as needed


Check PATH
~~~~~~~~~~

When installing Python packages via ``pip``, they will be installed as a local user unless invoked
as root. Some Python packages contain entry point scripts which act as user-facing commands
for the Python package. When installed as a user, these scripts are placed in ``$HOME/.local/bin``.

To ensure you're able to run these commands, make sure ``$HOME/.local/bin`` is at the beginning
of your ``$PATH``. The following command will highlight this section of the ``$PATH`` variable
if it exists.

.. code:: bash

   echo $PATH | grep --color=always "$HOME/\.local/bin"

.. note::

   For some distributions, such as Ubuntu and Azure Linux, ``$HOME/\.local/bin`` will be
   added to the ``$PATH`` at login if it exists. In this case, log out and
   log back in after installing LISA if your path doesn't currently include it.

Ideally, this section is at the beginning of your ``$PATH``. If not, you can add the following to
the bottom of your ``~/.profile`` or ``~.bash_profile`` files.

.. code:: bash

   export PATH="$HOME/.local/bin:$PATH"


Clone code
~~~~~~~~~~

.. code:: sh

   git clone https://github.com/microsoft/lisa.git
   cd lisa


<<<<<<< HEAD
Quick Installation Script
-------------------------

For a quick and automated installation, you can use the provided installation script:

.. code:: bash

   curl -sSL https://raw.githubusercontent.com/microsoft/lisa/main/quick-install.sh | bash

This script will:

- Detect your Linux distribution and version
- Install Python 3.12 (or use existing Python 3.8+)
- Install system dependencies based on your distribution
- Clone the LISA repository
- Install LISA with Azure and libvirt extensions

**For Ubuntu 24.04+:** The script automatically creates a virtual environment to comply with PEP 668.

**Customization options:**

.. code:: bash

   # Custom installation path (use sudo for system paths like /opt)
   sudo bash quick-install.sh --install-path /opt/lisa

   # Specific Python version
   bash quick-install.sh --python-version 3.12

   # Specific git branch
   bash quick-install.sh --branch develop

   # Skip Python installation
   bash quick-install.sh --skip-python

For help:

.. code:: bash

   bash quick-install.sh --help


Development Environment
-----------------------

For making any code changes and running test cases in LISA, you will need to setup a development environment. Instructions for setting up the development environment are present here: :ref:`DevEnv`.

Runtime Environment
-------------------

This installation method is used to run LISA if no change in source code is desired, for example, when setting up automation with LISA in pipelines. Direct installation requires pip 22.2.2 or higher. If the version of pip provided by your installation is older than this, a newer version should be installed.
=======
Install LISA
~~~~~~~~~~~~
>>>>>>> 52ac9e751 (Refine doc for installing lisa)

**For Ubuntu 24.04 and later:**

Due to PEP 668 externally-managed-environment restrictions, it's recommended to use a virtual environment:

.. code:: bash

   python3 -m venv venv
   source venv/bin/activate
   pip install --upgrade pip
   pip install --editable .[azure,libvirt] --config-settings editable_mode=compat

**For Ubuntu 22.04 and earlier, or other distributions:**

.. code:: bash

   python3 -m pip install --upgrade pip
   python3 -m pip install --editable .[azure,libvirt] --config-settings editable_mode=compat

To use LISA after installation in a virtual environment:

.. code:: bash

   # Option 1: Activate the environment
   source venv/bin/activate
   lisa

   # Option 2: Use the full path
   /path/to/lisa/venv/bin/lisa

   # Option 3: Create an alias (add to ~/.bashrc)
   alias lisa='/path/to/lisa/venv/bin/lisa'


Development Environment
-----------------------

For making any code changes and running test cases in LISA, you will need to setup a development environment. Instructions for setting up the development environment are present here: :ref:`DevEnv`.


Verify installation
-------------------

Ensure LISA is installed or a virtual environment is activated.

Run LISA with the ``lisa`` command

With no argument specified, LISA will run some sample test cases with
the default runbook (``examples/runbook/hello_world.yml``) on your local
computer. In the root folder of LISA, you can run this command to verify
your local LISA environment setup. This test will not modify your
computer.

.. code:: bash

   lisa

FAQ and Troubleshooting
-----------------------

If there's any problem during the installation, please refer to :doc:`FAQ and
troubleshooting <troubleshooting>`.
