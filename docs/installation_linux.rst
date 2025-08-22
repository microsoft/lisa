Install LISA on Linux
=====================

Minimum System Requirements
---------------------------

1. Your favorite Linux distribution supporting Python 3.8 or above
2. Dual core processor
3. 4 GB system memory

We will guide you through the installation of LISA on Linux.
The following commands assume Ubuntu or Azure Linux is being used.


Install Python on Linux
-----------------------

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
---------------------------

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
----------

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
----------

.. code:: sh

   git clone https://github.com/microsoft/lisa.git
   cd lisa


Development Environment
-----------------------

For making any code changes and running test cases in LISA, you will need to setup a development environment. Instructions for setting up the development environment are present here: :ref:`DevEnv`.

Runtime Environment
-------------------

This installation method is used to run LISA if no change in source code is desired, for example, when setting up automation with LISA in pipelines. Direct installation requires pip 22.2.2 or higher. If the version of pip provided by your installation is older than this, a newer version should be installed.

.. code:: bash

   python3 -m pip install --upgrade pip

The example below will install LISA directly for the invoking user.
To install system-wide, preface the command with ``sudo``.

.. code:: bash

   python3 -m pip install --editable .[azure,libvirt] --config-settings editable_mode=compat


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
