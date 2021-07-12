Install LISA on Windows
=======================

We will guide you through the installation of LISA on Windows.

.. note::

   On Windows, after you finished an installation, or made an
   environment variable change, you might need to restart your shell before moving
   to next step, to make sure your changes take effect.

.. note::
   Please run your command prompt or shell with elevated privilege
   (such as ``'Run as Administrator'`` on Windows) when you see access denied
   message when install tools.

Install Python on Windows
-------------------------

LISA has been tested on `Python 3.8 64
bits <https://www.python.org/>`__. The latest version of Python 3 is
recommended. If you found LISA is not compatible with higher version
Python, `please file an
issue <https://github.com/microsoft/lisa/issues/new>`__.

Navigate to `Python releases for
Windows <https://www.python.org/downloads/windows/>`__. Download and
install *Windows installer (64-bit)* for Python 3.8 64-bits or higher
version.

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

Install dependencies on Windows
-------------------------------

Please install ``git`` on your computer to clone LISA source code from
this repo and ``pip`` for later installation of Poetry.

In Windows, you need to install `git <https://git-scm.com/downloads>`__,
``virtualenv``\ (by running ``pip install virtualenv``) and `Visual C++
redistributable
package <https://aka.ms/vs/16/release/vc_redist.x64.exe>`__

Clone code
----------

.. code:: sh

   git clone https://github.com/microsoft/lisa.git
   cd lisa

Install Poetry on Windows
-------------------------

Poetry is used to manage Python dependencies of LISA.

Enter the ``PowerShell`` command prompt and then execute below commands:

.. code:: powershell

   (Invoke-WebRequest -Uri https://raw.githubusercontent.com/python-poetry/poetry/master/install-poetry.py -UseBasicParsing).Content | python -

   # Add poetry.exe's path to your `PATH` environment variable.
   $env:PATH += ";$env:APPDATA\Python\Scripts"

   poetry install

Verify installation
-------------------

``lisa.cmd`` is provided in Windows to wrap ``Poetry`` for you to run
LISA test.

With no argument specified, LISA will run some sample test cases with
the default runbook (``examples/runbook/hello_world.yml``) on your local
computer. In the root folder of LISA, you can run this command to verify
your local LISA environment setup. This test will not modify your
computer.

.. code:: bash

   .\lisa

FAQ and Troubleshooting
-----------------------

If there’s any problem during the installation, please refer to `FAQ and
troubleshooting <troubleshooting.html>`__.
