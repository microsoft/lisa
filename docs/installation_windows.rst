Install LISA on Windows
=======================

We will guide you through the installation of LISA on Windows.

.. note::

   On Windows, after you finished an installation, or make an
   environment variable change, you might need to restart your shell before moving
   to next step to make sure your changes take effect.

.. note::
   Please run your command prompt or shell with elevated privilege
   (such as ``'Run as Administrator'`` on Windows) when you see access denied
   message when installing tools.


Install Python on Windows
-------------------------

LISA has been tested to work with `Python 3.8 64-bit <https://www.python.org/>`__ and above.
The latest version of Python 3 is recommended. If you find that LISA is not compatible
with higher version Python, `please file an issue <https://github.com/microsoft/lisa/issues/new>`__.

The full installer allows greater customization and doesn't have the security restriction
of the Microsoft Store packages, so may be preferred in some situations.

Navigate to `Python releases for Windows <https://www.python.org/downloads/windows/>`__.
Download and install *Windows installer (64-bit)* for Python 3.12 64-bit or above.

More information on the full installer, including installation without a GUI,
can be found `here <https://docs.python.org/3/using/windows.html#the-full-installer>`_.

.. warning::

   Please make sure the ``Python`` directory and its ``Scripts``
   directory are added to your ``PATH`` environment variable. To check,
   type in console

.. code:: powershell

   echo $env:path

and if you see such two paths in the output, you are good. Otherwise
please manually add these two paths.

.. code:: powershell

   ...;C:\Users\username\AppData\Local\Programs\Python\Python39;C:\Users\username\AppData\Local\Programs\Python\Python39\Scripts;...

If this is your first time installing Python, simply check “add Python
to PATH” option in installation.


Install system dependencies on Windows
--------------------------------------

In Windows, you need to install `git <https://git-scm.com/downloads>`__,
and `Visual C++ redistributive package <https://aka.ms/vs/16/release/vc_redist.x64.exe>`__


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

The example below will install LISA directly for the invoking user. No need to run as Administrator.

.. code:: bash

    python3 -m pip install --editable .[azure] --config-settings editable_mode=compat



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
