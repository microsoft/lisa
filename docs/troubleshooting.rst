Troubleshooting
===============

-  `Installation <#installation>`__

   -  `How to use LISA in WSL <#how-to-use-lisa-in-wsl>`__
   -  `Many missing packages <#many-missing-packages>`__
   -  `Error: Poetry could not find a pyproject.toml
      file <#error-poetry-could-not-find-a-pyproject-toml-file>`__
   -  `Error: Poetry \"The virtual environment seems to be broken\" 
      <#error-poetry-the-virtual-environment-seems-to-be-broken>`__

-  `Using VSCode <#using-vscode>`__

   -  `Cannot find Python Interpreter by
      Poetry <#cannot-find-python-interpreter-by-poetry>`__
   -  `VSCode Python extension no longer supports “python.pythonPath” in
      “setting.json” <#vscode-python-extension-no-longer-supports-python-pythonpath-in-setting-json>`__

-  `Other issues <#other-issues>`__

   -  `Poetry related questions <#poetry-related-questions>`__

Installation
------------

How to use LISA in WSL
~~~~~~~~~~~~~~~~~~~~~~

If you are using WSL, installing Poetry on both Windows and WSL may
cause both platforms’ versions of Poetry to be on your path, as Windows
binaries are mapped into ``PATH`` of WSL. This means that the WSL
``poetry`` binary *must* appear in your ``PATH`` before the Windows
version, otherwise this error will appear:

``/usr/bin/env: ‘python\r’: No such file or directory``

Many missing packages
~~~~~~~~~~~~~~~~~~~~~

Poetry is case sensitive, which means it differentiates directories like
``C:\abc`` and ``C:\ABC`` in Windows, although Windows in fact does not allow
this (as a case insensitive system). When reading the path, please make sure
there’s no case mismatch in the path. Then run ``poetry install`` again at the
root folder (where your LISA source code is) to make sure all packages are
correctly installed.

Error: Poetry could not find a pyproject.toml file
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Poetry provides different packages according to the folder, and depends
on the ``pyproject.toml`` file in the current folder. Make sure to run
``poetry`` in the root folder of LISA.

Error: Poetry "The virtual environment seems to be broken"
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Ensure that ``python3 --version`` returns python3.8 before trying to install poetry. If the command points to an older version of python3, you must uninstall then reinstall poetry after ensuring that virtualenv is installed with pip3 using python3.8. 


Using VSCode
------------

Cannot find Python Interpreter by Poetry
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In the root folder of LISA, run the command below. It will return the
path of the virtual environment that Poetry set up. Use that path to
find the Python interpreter accordingly (in most cases open the path and
look for ``\Scripts\python.exe``).

.. code:: powershell

   poetry env info -p

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

An alternative way is to simply select the Poetry Python interpreter as
the default interpreter in the workspace, as in `Cannot find Python
Interpreter by Poetry <#cannot-find-python-interpreter-by-poetry>`__

Other issues
------------

Please check `known issues <https://github.com/microsoft/lisa/issues>`__
or `file a new issue <https://github.com/microsoft/lisa/issues/new>`__
if it doesn’t exist.

Poetry related questions
~~~~~~~~~~~~~~~~~~~~~~~~

Poetry is very useful to manage dependencies of Python. It’s a virtual
environment, not a complete interpreter like Conda. So make sure the
right and effective version of Python interpreter is installed. You can
learn more about Poetry in the official documentation like
`installation <https://python-poetry.org/docs/#installation>`__ or
`commands <https://python-poetry.org/docs/cli/>`__.
