Install LISA on Linux
=====================

Minimum System Requirement
-----------------------
1. Your favourite Linux distro supporting Python 3.8+
2. Dual core processor
3. 4 GB system memory

We will guide you through the installation of LISA on Linux. The following commands assume Ubuntu 18.04 as the underlying Linux distro.

Install Python on Linux
-----------------------

LISA has been tested to work with `Python 3.8 64-bit
<https://www.python.org/>`__. The latest version of Python 3 is
recommended. If you find that LISA is not compatible with higher version
Python, `please file an
issue <https://github.com/microsoft/lisa/issues/new>`__.

Run following commands to install Python 3.8:

.. code:: bash

   sudo apt update
   sudo apt install software-properties-common -y
   sudo add-apt-repository ppa:deadsnakes/ppa -y
   sudo apt install python3.8 python3.8-dev -y

Install dependencies on Linux
-----------------------------

Run the command below to install the dependencies:

.. code:: bash

   sudo apt install git gcc libgirepository1.0-dev libcairo2-dev qemu-utils libvirt-dev python3-pip python3-venv -y

Clone code
----------

.. code:: sh

   git clone https://github.com/microsoft/lisa.git
   cd lisa

Install Poetry on Linux
-----------------------

Poetry is used to manage Python dependencies of LISA.

.. warning::
   
   Please enter the root folder of LISA source code to run
   following commands to install poetry, since Poetry manages dependencies
   by the working folder.

.. code:: bash

   curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/install-poetry.py | python3 -

After running this, you should see
``Add export PATH="/home/YOURUSERNAME/.local/bin:$PATH" to your shell configuration file``
message on the console. Follow the message and add the necessary exports to ``$HOME/.profile`` file. Then do

.. code:: bash

   source $HOME/.profile
   make setup

Verify installation
-------------------

``lisa.sh`` is provided in Linux to wrap ``Poetry`` for you to run LISA
test.

In Linux, you could create an alias for this simple script. For example,
add below line to add to ``.bashrc``:

.. code:: bash

   alias lisa="./lisa.sh"

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
