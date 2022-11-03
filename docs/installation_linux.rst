Install LISA on Linux
=====================

Minimum System Requirements
---------------------------

1. Your favorite Linux distribution supporting Python 3.8 - 3.10
2. Dual core processor
3. 4 GB system memory

We will guide you through the installation of LISA on Linux.
The following commands assume Ubuntu is being used.


Install Python on Linux
-----------------------

LISA has been tested to work with `Python 3.8 - 3.10 64-bit <https://www.python.org/>`__.
Python 3.10 is recommended. Support for 3.11+ is under development.
If you find that LISA is not compatible with a supported version,
`please file an issue <https://github.com/microsoft/lisa/issues/new>`__.

To check which version of Python is used on your system, run the following:

.. code:: bash

   python3 --version

If you need to install a different Python package, there are likely packaged versions for
your distro.

Here is an example to install Python 3.10 on Ubuntu 20.04

.. code:: bash

   sudo apt update
   sudo apt install software-properties-common -y
   sudo add-apt-repository ppa:deadsnakes/ppa -y
   sudo apt install python3.10 python3.10-dev -y


Install system dependencies
---------------------------

Run the command below to install the dependencies on Ubuntu:

.. code:: bash

   sudo apt install git gcc libgirepository1.0-dev libcairo2-dev qemu-utils libvirt-dev python3-pip python3-venv -y

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

   echo $PATH | grep --color=always "$HOME/\.local/bin\|$

Ideally, this section is at the beginning of your ``$PATH``. If not, you can add the following to
the bottom of your ``~/.profile`` or ``~.bash_profile`` files.

.. code:: bash

   export PATH="$HOME/.local/bin:$PATH


Clone code
----------

.. code:: sh

   git clone https://github.com/microsoft/lisa.git
   cd lisa


Directly install LISA (Option 1)
--------------------------------

This will install LISA directly for the invoking user.
To install system-wide, preface the command with ``sudo``.

.. code:: bash

   python3 -m pip install .[azure, libvirt]



Install LISA in a virtual environment (Option 2)
------------------------------------------------

If you wish to keep LISA and it's dependencies separate, you can install it
into a virtual environment. This `guide`_ can be used if you wish to do this manually.
Or, to use a development virtual environment, follow the instructions in :ref:`DevVirtEnv`.

.. _guide: https://sublime-and-sphinx-guide.readthedocs.io/en/latest/references.html



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

If there’s any problem during the installation, please refer to :doc:`FAQ and
troubleshooting <troubleshooting>`.
