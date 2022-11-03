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

Install from Microsoft Store (recommended)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

It is recommended to install Python from the Microsoft Store. Packages are regularly
published by the Python Software Foundation and will set up paths as needed.

To install from the Microsoft Store, search for Python in the store interface or,
if no other Python version is installed, running `python3` from the command line
will bring up the latest version.
More details can be found `here<https://docs.python.org/3/using/windows.html#windows-store>`.

Install using full installer (alternative)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The full installer allows greater customization and doesn't have the security restriction
of the Microsoft Store packages, so may be preferred in some situations.

Navigate to `Python releases for Windows <https://www.python.org/downloads/windows/>`__.
Download and install *Windows installer (64-bit)* for Python 3.8 - 3.10 64-bit.

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


Directly install LISA (Option 1)
--------------------------------

This will install LISA directly for the invoking user.
To install system-wide, run from and Administrator console.

.. code:: bash

   pip3 install .[azure]



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
