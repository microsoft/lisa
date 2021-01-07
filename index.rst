Linux Integration Services Automation
=====================================

|LISA/Pytest CI Workflow| |Code Style: black|

LISA is a Linux test automation framework with built-in test cases to
verify the quality of Linux distributions on multiple platforms (such
as Azure, Hyper-V, and bare metal). It is an opinionated collection of
custom `Pytest <https://docs.pytest.org/en/stable/>`__ plugins,
configurations, and tests. See the :doc:`technical specification
document <DESIGN>` for details.

.. toctree::
   :maxdepth: 3
   :hidden:

   Design <DESIGN>
   Contributing <CONTRIBUTING>
   Code of Conduct <CODE_OF_CONDUCT>

Getting Started
---------------

Install Python 3
~~~~~~~~~~~~~~~~

Install Python 3.7 or newer from your Linux distribution’s package
repositories, or `python.org <https://www.python.org/>`__.

Install Poetry
~~~~~~~~~~~~~~

`Poetry <https://python-poetry.org/docs/>`__ is our preferred tool for
Python dependency management and packaging. We’ll use it to
automatically setup a ‘virtualenv’ and install everything we need.

On Linux (or WSL)
^^^^^^^^^^^^^^^^^

.. code:: bash

   curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py | python -
   source $HOME/.poetry/env

If you are using WSL, installing Poetry on both Windows and Linux may
cause both platforms’ versions of Poetry to be on your path, as Windows
binaries are mapped into WSL’s ``PATH``. This means that the Linux
``poetry`` binary *must* appear in your ``PATH`` before the Windows
version, or this error will appear:

::

   `/usr/bin/env: ‘python\r’: No such file or directory`

Adjust your ``PATH`` appropriately to fix it.

On Windows (in PowerShell)
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code:: powershell

   (Invoke-WebRequest -Uri https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py -UseBasicParsing).Content | python -
   $env:PATH += ";$env:USERPROFILE\.poetry\bin"

Clone LISA and ``cd`` into the Git repo
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: bash

   git clone -b andschwa/pytest https://github.com/microsoft/lisa.git
   cd lisa

Install Python dependencies
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: bash

   # Install the Python packages
   poetry install

   # Enter the virtual environment
   poetry shell

Use LISA
~~~~~~~~

.. code:: bash

   # Run some self-tests
   lisa --playbook=playbooks/test.yml selftests/

   # Run a demo which deploys Azure resources
   lisa --playbook=playbooks/demo.yaml

Enable Azure
^^^^^^^^^^^^

To run the demo you’ll need the `Azure
CLI <https://docs.microsoft.com/en-us/cli/azure/>`__ tool installed and
configured:

.. code:: bash

   # Install Azure CLI, make sure `az` is in your `PATH`
   curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

   # Login and set subscription
   az login
   az account set -s <your subscription ID>

Contributing
------------

See the :doc:`contributing guidelines <CONTRIBUTING>` for developer
information!

Contributor License Agreement
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This project welcomes contributions and suggestions. Most contributions
require you to agree to a Contributor License Agreement (CLA) declaring
that you have the right to, and actually do, grant us the rights to use
your contribution. For details, visit
https://cla.opensource.microsoft.com.

When you submit a pull request, a CLA bot will automatically determine
whether you need to provide a CLA and decorate the PR appropriately
(e.g., status check, comment). Simply follow the instructions provided
by the bot. You will only need to do this once across all repos using
our CLA.

This project has adopted the `Microsoft Open Source Code of
Conduct <https://opensource.microsoft.com/codeofconduct/>`__. For more
information see the `Code of Conduct
FAQ <https://opensource.microsoft.com/codeofconduct/faq/>`__ or contact
opencode@microsoft.com with any additional questions or comments.

Legal Notices
-------------

Microsoft and any contributors grant you a license to the Microsoft
documentation and other content in this repository under the `Creative
Commons Attribution 4.0 International Public License
<https://creativecommons.org/licenses/by/4.0/legalcode>`__, see the
:doc:`LICENSE-DOCS <LICENSE-DOCS>` file, and grant you a license to
any code in the repository under the `MIT License
<https://opensource.org/licenses/MIT>`__, see the :doc:`LICENSE
<LICENSE>` file.

Microsoft, Windows, Microsoft Azure and/or other Microsoft products and
services referenced in the documentation may be either trademarks or
registered trademarks of Microsoft in the United States and/or other
countries. The licenses for this project do not grant you rights to use
any Microsoft names, logos, or trademarks. Microsoft’s general trademark
guidelines can be found at
https://go.microsoft.com/fwlink/?LinkID=254653.

Privacy information can be found at https://privacy.microsoft.com/en-us/

Microsoft and any contributors reserve all other rights, whether under
their respective copyrights, patents, or trademarks, whether by
implication, estoppel or otherwise.

.. |LISA/Pytest CI Workflow| image:: https://github.com/microsoft/lisa/workflows/LISA/Pytest%20CI%20Workflow/badge.svg?branch=andschwa%2Fpytest
   :target: https://github.com/microsoft/lisa/actions?query=workflow%3A%22LISA%2FPytest+CI+Workflow%22
.. |Code Style: black| image:: https://img.shields.io/badge/code%20style-black-000000.svg
   :target: https://github.com/psf/black
