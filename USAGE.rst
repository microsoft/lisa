How to Use Pytest and LISA
==========================

LISA is supported on almost any Linux or Windows installation provided
Python 3.7 (released in 2018) or newer is available and SSH can be
used to connect to the remote targets under test. The local SSH
configuration is respected so ``ProxyJump`` can be used.

Install Python 3.7+
-------------------

Install Python 3.7 or newer from your Linux distribution’s package
repositories, or `python.org <https://www.python.org/>`_.

On Ubuntu 20.04 and up, just run ``apt install python-is-python3``.

Below that Ubuntu version, the ``python3`` package is out-of-date, so
use something like a `PPA`_ or `pyenv`_.

.. _PPA: https://launchpad.net/~deadsnakes/+archive/ubuntu/ppa
.. _pyenv: https://github.com/pyenv/pyenv

Install Poetry
--------------

`Poetry <https://python-poetry.org/docs/>`_ is our preferred tool for
Python dependency management and packaging. We’ll use it to
automatically setup a virtual environment and install everything.

On Linux (or WSL)
~~~~~~~~~~~~~~~~~

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
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: powershell

   (Invoke-WebRequest -Uri https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py -UseBasicParsing).Content | python -
   $env:PATH += ";$env:USERPROFILE\.poetry\bin"

Clone LISA and ``cd`` into the Git repo
---------------------------------------

.. code:: bash

   git clone -b andschwa/pytest https://github.com/microsoft/lisa.git
   cd lisa

Install Python dependencies
---------------------------

Now we’ll use ``poetry`` to install all the necessary packages. Note
that we have a number of developer dependencies specified to make your
life easier when :doc:`contributing <CONTRIBUTING>`, but you can
exclude these (and their potential additional requirements) with the
flag ``--no-dev``. Once installed, we use ``poetry shell`` to enter a
sub-shell with the Python virtual environment setup.

.. code:: bash

   # Install the Python packages
   poetry install

   # Enter the virtual environment
   poetry shell

Use LISA
--------

Under the covers ``lisa`` is just ``pytest``! Run ``lisa --help`` for
all available options, and refer to the Pytest `usage`_ documentation.
LISA is generally run with a :py:mod:`playbook` which is a `YAML file
<https://learnxinyminutes.com/docs/yaml/>`_ specifying a list of
remote targets, their parameters, and optionally a set of test
selection criteria. The ``demo.yaml`` looks like:

.. _usage: https://docs.pytest.org/en/stable/usage.html

.. code:: yaml

   platforms:
     AzureCLI:
       sku: Standard_DS2_v2

   targets:
     - name: Debian
       platform: AzureCLI
       image: credativ:Debian:9:9.0.201706190

     - name: Ubuntu
       platform: AzureCLI
       image: Canonical:UbuntuServer:18.04-LTS:latest

   criteria:
       - module: test_smoke_b

The ``platforms`` key is used to set default parameters for
targets using that platform; in this case, the SKU is set to
``Standard_DS2_v2``.

The ``targets`` key defines a number of targets on which the selected
tests will run. Here we’re asking for two targets using the same
:py:class:`~target.azure.AzureCLI` platform, both will use the same
default for the SKU, but different images. The ``name`` is just a
user-provided friendly name that is appended to the parameterized
tests and will show up in test results.

The ``criteria`` key can be used to select a tests instead of using
Pytest’s CLI test selection interface. In this case we’re selecting
all tests from the module (Python file) named ``test_smoke_b``, one of
the examples of an Azure VM smoke test, and it looks like this:

.. code:: python

   from __future__ import annotations  # For type checking.

   import typing

   if typing.TYPE_CHECKING:
       from target import AzureCLI
       from _pytest.logging import LogCaptureFixture
       from pathlib import Path

   import logging
   import socket
   import time

   from invoke.runners import CommandTimedOut, UnexpectedExit  # type: ignore
   from paramiko import SSHException  # type: ignore

   from lisa import LISA


   @LISA(platform="Azure", category="Functional", area="deploy", priority=0)
   def test_smoke(target: AzureCLI, caplog: LogCaptureFixture, tmp_path: Path) -> None:
       """Check that an Azure Linux VM can be deployed and is responsive.

       This example uses exactly one function for the entire test, which
       means we have to catch failures that don't fail the test, and
       instead emit warnings. It works, and it's closer to how LISAv2
       would have implemented it, but it's less Pythonic. For a more
       "modern" example, see `test_smoke_a.py`.

       1. Deploy the VM (via `target` fixture).
       2. Ping the VM.
       3. Connect to the VM via SSH.
       4. Attempt to reboot via SSH, otherwise use the platform.
       5. Fetch the serial console logs AKA boot diagnostics.

       SSH failures DO NOT fail this test.

       """
       # Capture INFO and above logs for this test.
       caplog.set_level(logging.INFO)

       logging.info("Pinging before reboot...")
       ping1 = target.ping()

       ssh_errors = (TimeoutError, CommandTimedOut, SSHException, socket.error)

       try:
           logging.info("SSHing before reboot...")
           target.conn.open()
       except ssh_errors as e:
           logging.warning(f"SSH before reboot failed: '{e}'")

       reboot_exit = 0
       try:
           logging.info("Rebooting...")
           # If this succeeds, we should expect the exit code to be -1
           reboot_exit = target.conn.sudo("reboot", timeout=5).exited
       except ssh_errors as e:
           logging.warning(f"SSH failed, using platform to reboot: '{e}'")
           target.platform_restart()
       except UnexpectedExit:
           # TODO: How do we differentiate reboot working and the SSH
           # connection disconnecting for other reasons?
           if reboot_exit != -1:
               logging.warning("While SSH worked, 'reboot' command failed")

       # TODO: We should check something more concrete here instead of
       # sleeping an arbitrary amount of time.
       logging.info("Sleeping for 10 seconds after reboot...")
       time.sleep(10)

       logging.info("Pinging after reboot...")
       ping2 = target.ping()

       try:
           logging.info("SSHing after reboot...")
           target.conn.open()
       except ssh_errors as e:
           logging.warning(f"SSH after reboot failed: '{e}'")

       logging.info("Retrieving boot diagnostics...")
       path = tmp_path / "diagnostics.txt"
       try:
           # NOTE: It’s actually more interesting to emit the downloaded
           # boot diagnostics to `stdout` as they’re then captured in the
           # HTML report, but this is to demo using `tmp_path`.
           diagnostics = target.get_boot_diagnostics(hide=True)
           path.write_text(diagnostics.stdout)
       except UnexpectedExit:
           logging.warning("Retrieving boot diagnostics failed.")
       else:
           logging.info(f"See '{path}' for boot diagnostics.")

       # NOTE: The test criteria is to fail only if ping fails.
       assert ping1.ok, f"Pinging {target.host} before reboot failed"
       assert ping2.ok, f"Pinging {target.host} after reboot failed"


Enable Azure
~~~~~~~~~~~~

Before running this demo, we will need to set up the `Azure CLI
<https://aka.ms/azureclidocs>`_ because this platform uses it. Install
it if you do not already have, then ensure it is logged in with your
choice of authentication, and set a default subscription, which will
be used to deploy the resources.

.. code:: bash

   # Install Azure CLI, make sure `az` is in your `PATH`
   curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

   # Login and set subscription
   az login
   az account set -s <your subscription ID>

Run the Demo
~~~~~~~~~~~~

Now we can run the demo!

.. code:: bash

   # Run a demo which deploys Azure resources
   lisa --playbook=playbooks/demo.yaml --keep-targets --html=demo.html

This will sequentially deploy the two requested targets and run the
smoke test against them, printing the stdout, stderr, and logging of
all tests after they complete (see below for how to change this
behavior). The ``--keep-targets`` flag comes from the :py:mod:`target`
plugin and instructs it to cache the deployed targets between test
runs. Delete them by running ``lisa --delete-targets``. The
``--html=demo.html`` flag will cause an easy-to-read HTML report to be
written to ``demo.html``.

It should look very similar to this slightly redacted example:

::

   $ lisa --playbook=playbooks/demo.yaml --keep-targets --html=demo.html
   =========================== test session starts ==========================
   collected 40 items / 38 deselected / 2 selected

   testsuites/test_smoke_b.py F.                                       [100%]

   ================================ FAILURES ================================
   _______________________ test_smoke[Target=Debian] ________________________
   testsuites/test_smoke_b.py:93: in test_smoke
       assert ping2.ok, f"Pinging {target.host} after reboot failed"
   E   AssertionError: Pinging 40.123.27.161 after reboot failed
   E   assert False
   E    +  where False = <Result cmd='ping -c 1 40.123.27.161' exited=1>.ok
   ------------------------- Captured stdout setup --------------------------
   az vm create -g pytest-d6056453-a28c-4fec-8225-7c7aab02c84a-rg -n pytest-d6056453-a28c-4fec-8225-7c7aab02c84a-0 --image credativ:Debian:9:9.0.201706190 --size Standard_DS2_v2 --boot-diagnostics-storage pytestbootdiag --generate-ssh-keys
   {
     "fqdns": "",
     "id": "/subscriptions/<...>/resourceGroups/pytest-d6056453-a28c-4fec-8225-7c7aab02c84a-rg/providers/Microsoft.Compute/virtualMachines/pytest-d6056453-a28c-4fec-8225-7c7aab02c84a-0",
     "location": "eastus2",
     "macAddress": "00-0D-3A-DE-07-17",
     "powerState": "VM running",
     "privateIpAddress": "10.0.0.4",
     "publicIpAddress": "<...>",
     "resourceGroup": "pytest-d6056453-a28c-4fec-8225-7c7aab02c84a-rg",
     "zones": ""
   }
   -------------------------- Captured stdout call --------------------------
   ping -c 1 40.123.27.161
   PING 40.123.27.161 (40.123.27.161) 56(84) bytes of data.

   --- 40.123.27.161 ping statistics ---
   1 packets transmitted, 0 received, 100% packet loss, time 0ms
   ...
   ping -c 1 40.123.27.161
   PING 40.123.27.161 (40.123.27.161) 56(84) bytes of data.
   64 bytes from 40.123.27.161: icmp_seq=1 ttl=43 time=85.6 ms

   --- 40.123.27.161 ping statistics ---
   1 packets transmitted, 1 received, 0% packet loss, time 0ms
   rtt min/avg/max/mdev = 85.562/85.562/85.562/0.000 ms
   ping -c 1 40.123.27.161
   PING 40.123.27.161 (40.123.27.161) 56(84) bytes of data.

   --- 40.123.27.161 ping statistics ---
   1 packets transmitted, 0 received, 100% packet loss, time 0ms
   ...
   ping -c 1 40.123.27.161
   PING 40.123.27.161 (40.123.27.161) 56(84) bytes of data.

   --- 40.123.27.161 ping statistics ---
   1 packets transmitted, 0 received, 100% packet loss, time 0ms

   --------------------------- Captured log call ----------------------------
   2021-01-20 17:14:56 INFO Pinging before reboot...
   2021-01-20 17:15:51 INFO SSHing before reboot...
   2021-01-20 17:15:52 INFO Connected (version 2.0, client OpenSSH_7.4p1)
   2021-01-20 17:15:53 INFO Authentication (publickey) successful!
   2021-01-20 17:15:53 INFO Rebooting...
   2021-01-20 17:15:53 WARNING While SSH worked, 'reboot' command failed
   2021-01-20 17:15:53 INFO Sleeping for 10 seconds after reboot...
   2021-01-20 17:16:03 INFO Pinging after reboot...
   2021-01-20 17:17:08 INFO SSHing after reboot...
   2021-01-20 17:19:16 ERROR Secsh channel 1 open FAILED: Connection timed out: Connect failed
   2021-01-20 17:19:16 WARNING SSH after reboot failed: 'ChannelException(2, 'Connect failed')'
   2021-01-20 17:19:16 INFO Retrieving boot diagnostics...
   2021-01-20 17:19:20 INFO See '/tmp/pytest-of-andschwa/pytest-181/test_smoke_Target_Debian_0/diagnostics.txt' for boot diagnostics.
   ================================= PASSES =================================
   _______________________ test_smoke[Target=Ubuntu] ________________________
   ------------------------- Captured stdout setup --------------------------
   az vm create -g pytest-8f173841-d702-432e-bd32-f09a984bd3ab-rg -n pytest-8f173841-d702-432e-bd32-f09a984bd3ab-0 --image Canonical:UbuntuServer:18.04-LTS:latest --size Standard_DS2_v2 --boot-diagnostics-storage pytestbootdiag --generate-ssh-keys
   {
     "fqdns": "",
     "id": "/subscriptions/<..>/resourceGroups/pytest-8f173841-d702-432e-bd32-f09a984bd3ab-rg/providers/Microsoft.Compute/virtualMachines/pytest-8f173841-d702-432e-bd32-f09a984bd3ab-0",
     "location": "eastus2",
     "macAddress": "00-0D-3A-7C-85-59",
     "powerState": "VM running",
     "privateIpAddress": "10.0.0.4",
     "publicIpAddress": "<...>",
     "resourceGroup": "pytest-8f173841-d702-432e-bd32-f09a984bd3ab-rg",
     "zones": ""
   }
   -------------------------- Captured stdout call --------------------------
   ping -c 1 137.116.51.62
   PING 137.116.51.62 (137.116.51.62) 56(84) bytes of data.

   --- 137.116.51.62 ping statistics ---
   1 packets transmitted, 0 received, 100% packet loss, time 0ms
   ...
   ping -c 1 137.116.51.62
   PING 137.116.51.62 (137.116.51.62) 56(84) bytes of data.
   64 bytes from 137.116.51.62: icmp_seq=1 ttl=42 time=84.0 ms

   --- 137.116.51.62 ping statistics ---
   1 packets transmitted, 1 received, 0% packet loss, time 0ms
   rtt min/avg/max/mdev = 84.004/84.004/84.004/0.000 ms
   --------------------------- Captured log call ----------------------------
   2021-01-20 17:20:26 INFO Pinging before reboot...
   2021-01-20 17:21:21 INFO SSHing before reboot...
   2021-01-20 17:21:21 INFO Connected (version 2.0, client OpenSSH_7.6p1)
   2021-01-20 17:21:22 INFO Authentication (publickey) successful!
   2021-01-20 17:21:22 INFO Rebooting...
   2021-01-20 17:21:24 WARNING While SSH worked, 'reboot' command failed
   2021-01-20 17:21:24 INFO Sleeping for 10 seconds after reboot...
   2021-01-20 17:21:34 INFO Pinging after reboot...
   2021-01-20 17:21:45 INFO SSHing after reboot...
   2021-01-20 17:21:46 INFO Connected (version 2.0, client OpenSSH_7.6p1)
   2021-01-20 17:21:46 INFO Authentication (publickey) successful!
   2021-01-20 17:21:46 INFO Retrieving boot diagnostics...
   2021-01-20 17:21:50 INFO See '/tmp/pytest-of-andschwa/pytest-181/test_smoke_Target_Ubuntu_0/diagnostics.txt' for boot diagnostics.
   ----- generated html file: file:///home/andschwa/src/lisa/demo.html ------
   ======================== short test summary info =========================
   PASSED testsuites/test_smoke_b.py::test_smoke[Target=Ubuntu]
   FAILED testsuites/test_smoke_b.py::test_smoke[Target=Debian] - AssertionError: Pinging 40.123.27.161 after reboot failed
   ========= 1 failed, 1 passed, 38 deselected in 541.93s (0:09:01) =========

Settings
--------

Our opinionated `usage`_ settings are in ``pytest.ini``. Adjust them
(or override them on the CLI) as you see fit! They include:

``--no-header``

   For more succinct display, we suppress the default Pytest header
   with the platform, root directory, plugins, and timeout
   information.

``--tb=short``

   Since we’re generally testing commands on remote systems, we don’t
   care about the full Python trace when a test fails, so we set the
   `traceback printing
   <https://docs.pytest.org/en/stable/usage.html#modifying-python-traceback-printing>`_
   to be short.

``-rA``

   We want the status (and captured logs) of *all* tests printed in
   the final summary, but Pytest defaults to failed and errored tests
   with ``fE``, hence our use of ``A``.

``timeout = 1200``

   Since we run our tests on remote machines which may hang, we use
   `pytest-timeout <https://pypi.org/project/pytest-timeout/>`_ to
   cancel any tests that exceed 20 minutes. Note that the
   :py:class:`target` class also has a “timeout” configuration for
   individual commands using `Invoke <https://www.pyinvoke.org/>`_.

Suggestions
~~~~~~~~~~~

Test developers may wish to run with the flags:

``--capture=tee-sys``

   This will `capture
   <https://docs.pytest.org/en/stable/capture.html>`_ all writes to
   ``sys.stdout`` and ``sys.stderr``, but also pass them to ``sys``
   such that they’re printed *live* (useful when writing tests, but
   annoying when running tests).

``log_cli=true``

   Pytest can emit captured `logs
   <https://docs.pytest.org/en/stable/logging.html>`_ live too. Add
   this to ``pytest.ini`` (and adjust the level and format as
   desired).

``--tb=auto``

   To show the full traceback instead of just a line.

``--html=path/to/report.html``

   We include `pytest-html
   <https://pytest-html.readthedocs.io/en/latest/>`_ as a dependency
   so users can generate HTML reports with all captured stdout,
   stderr, traceback, and logs.
