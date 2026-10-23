Troubleshooting
===============

.. contents::
   :local:
   :depth: 2


Installation
------------

Error: (For Windows installation) Cannot open Scripts folder
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The Shell interface tries to locate the Scripts folder inside python.exe.

Error line: Cannot open <Your local AppData dir>\\Microsoft\\WindowsApps\
\PythonSoftwareFoundation.Python.3.10_qbz5n2kfra8p0\\python.exe\\Scripts'

Reason: This can happen when you install the Python version via Microsoft
store or use a user installation.
Fix: uninstall the Microsoft Store version and install the standalone
version from https://www.python.org/downloads/windows/


Using VSCode
------------

VSCode Python extension no longer supports “python.pythonPath” in “setting.json”
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Refer to
`DeprecatePythonPath <https://github.com/microsoft/vscode-python/wiki/AB-Experiments>`__
for more information.

.. admonition:: TL;DR

   "We removed the “python.pythonPath” setting from your settings.json
   file as the setting is no longer used by the Python extension. You
   can get the path of your selected interpreter in the Python output
   channel."

An alternative way is to simply select the virtual environment ``.venv`` as
the default interpreter in the workspace.

Azure guest sudo passwords
-------------------------

SSH key authentication does not imply passwordless sudo. When a Linux guest
requires a sudo password and none was supplied, LISA uses the VMAccessForLinux
extension to reset the test user's password.

Extension initialization reads the Azure Linux Agent configuration without sudo
first, so an already-enabled agent can reset the password before privileged guest
commands are available. If the configuration is not readable, LISA retries with
sudo and reports any read failure. Changing a disabled ``Extensions.Enabled``
setting still requires sudo privileges.

Other issues
------------

Please check `known issues <https://github.com/microsoft/lisa/issues>`__
or `file a new issue <https://github.com/microsoft/lisa/issues/new>`__
if it doesn't exist.
