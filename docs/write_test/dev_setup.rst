Development setup
=================

This document describes the existing developer tooling we have in place (and
what to expect of it).

.. contents::
   :local:
   :depth: 2


Environment Setup
-----------------

Follow the :ref:`quick_start:installation` steps to
prepare the source code. Then follow the steps below to set up the corresponding
development environment.

.. _DevEnv:

Creating a LISA development virtual environment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Nox is used to manage virtual environments for LISA.
See `Using Nox`_ for more information.

Nox can be installed with `pip`.

.. code:: bash

   pip3 install nox toml


The following creates a virtual environment in ``.venv`` with an editable install
of LISA. An editable install allows code changes in the repo to immediately affect
the virtual environment. This is useful for iterative development.

From the root of the LISA repo, run the following to create or update virtual environment.

.. code:: bash

   nox -vs dev

By default, the extra dependencies for Azure will be installed.
On Linux, the extra dependencies for libvirt will also be installed.
This behavior can be overridden by passing dependency groups as additional arguments.

For example, the following will only install extra dependencies for Azure.

.. code:: bash

   nox -vs dev -- azure

Information on what extra dependency groups are supported can be found in
:ref:`extras:LISA's extras`.


VSCode should automatically detect and activate the virtual environment on startup
and you can manually activate it in a shell with the following commands.


Activate virtual environment (Bash)

.. code:: bash

   source .venv/bin/activate

Activate virtual environment (Powershell)

.. code:: powershell

   .venv\Scripts\activate.ps1

Activate virtual environment (cmd)

.. code:: batch

   .venv\Scripts\activate.bat


When the virtual environment is active, your command prompt will be prefixed with `(lisa)`.

If you wish to deactivate the virtual environment, use the ``deactivate`` command.

.. code:: bash

   deactivate


Visual Studio Code
~~~~~~~~~~~~~~~~~~

1. Click on the Python version at the bottom left of the editor's window
   and select the Python interpreter which Poetry just created. If you do not
   find it, check :doc:`FAQ and troubleshooting <../troubleshooting>` for extra
   instructions. This step is important because it ensures that the current
   workspace uses the correct Poetry virtual environment which provides all
   dependencies required.

2. You can copy the settings below into ``.vscode/settings.json``.

   .. code:: json

      {
         "markdown.extension.toc.levels": "2..6",
         "python.analysis.typeCheckingMode": "strict",
         "python.linting.pylintEnabled": false,
         "python.analysis.useLibraryCodeForTypes": false,
         "python.analysis.autoImportCompletions": false,
         "files.eol": "\n",
         "terminal.integrated.env.windows": {
            "mypypath": "${workspaceFolder}\\typings"
         },
         "python.analysis.diagnosticSeverityOverrides": {
            "reportUntypedClassDecorator": "none",
            "reportUnknownMemberType": "none",
            "reportGeneralTypeIssues": "none",
            "reportUnknownVariableType": "none",
            "reportUnknownArgumentType": "none",
            "reportUnknownParameterType": "none",
            "reportUnboundVariable": "none",
            "reportPrivateUsage": "none",
            "reportImportCycles": "none",
            "reportUnnecessaryIsInstance": "none",
            "reportPrivateImportUsage": "none",
            "reportUnusedImport": "none",
            "reportUnusedFunction": "none",
            "reportOptionalMemberAccess": "none",
            "reportArgumentType": "none",
            "reportAttributeAccessIssue": "none",
            "reportAssignmentType": "none",
            "reportOptionalSubscript": "none",
            "reportRedeclaration": "none",
            "reportIncompatibleVariableOverride": "none",
            "reportUnnecessaryCast": "none",
            "reportUnnecessaryComparison": "none",
            "reportCallIssue": "none",
            "reportOperatorIssue": "none",
            "reportMissingImports": "none",
            "reportUnusedVariable": "none",
            "reportMissingParameterType": "none",
            "reportReturnType": "none",
            "reportMissingTypeStubs": "none"
         },
         "python.analysis.stubPath": "./typings",
         "python.languageServer": "Pylance",
         "flake8.importStrategy": "fromEnvironment",
         "mypy-type-checker.importStrategy": "fromEnvironment",
         "mypy-type-checker.args": [
            "--config-file",
            "pyproject.toml"
         ],
         "black-formatter.importStrategy": "fromEnvironment",
         "[python]": {
            "editor.defaultFormatter": "ms-python.black-formatter",
            "editor.formatOnSave": true,
            "editor.codeActionsOnSave": {
                  "source.organizeImports": true
            },
         },
         "isort.importStrategy": "fromEnvironment",
         "isort.args": [
            "--settings-path",
            "pyproject.toml"
         ]
      }

3. Install extensions.

   -  Install
      `Python <https://marketplace.visualstudio.com/items?itemName=ms-python.python>`__,
      `Pylance <https://marketplace.visualstudio.com/items?itemName=ms-python.vscode-pylance>`__
      to get best code intelligence experience.
   -  Install Python extensions to get consistent error as CI pipelines, `flake8 <https://marketplace.visualstudio.com/items?itemName=ms-python.flake8>`__, `mypy <https://marketplace.visualstudio.com/items?itemName=ms-python.mypy-type-checker>`__, `black <https://marketplace.visualstudio.com/items?itemName=ms-python.black-formatter>`__, `isort <https://marketplace.visualstudio.com/items?itemName=ms-python.isort>`__.

   -  Install
      `Rewrap <https://marketplace.visualstudio.com/items?itemName=stkb.rewrap>`__
      to automatically wrap.
   -  If there is need to update the documentation, it is recommended to
      install `Markdown All in
      One <https://marketplace.visualstudio.com/items?itemName=yzhang.markdown-all-in-one>`__.
      It helps to maintain the table of contents in the documentation.
   -  Install
      `reStructuredText
      <https://marketplace.visualstudio.com/items?itemName=lextudio.restructuredtext>`__
      to get a syntax checker for reStructuredText. To preview the document, see
      :ref:`write_test/dev_setup:local documentation`.

Emacs
~~~~~

Use the `pyvenv <https://github.com/jorgenschaefer/pyvenv>`__ package:

.. code:: emacs-lisp

   (use-package pyvenv
     :ensure t
     :hook (python-mode . pyvenv-tracking-mode))

Then run
``M-x add-dir-local-variable RET python-mode RET pyvenv-activate RET <path/to/virtualenv>``
where the value is the path given by the command above. This will create
a ``.dir-locals.el`` file as follows:

.. code:: emacs-lisp

   ;;; Directory Local Variables
   ;;; For more information see (info "(emacs) Directory Variables")

   ((python-mode . ((pyvenv-activate . ".venv"))))

Other setups
~~~~~~~~~~~~

-  Install and enable
   `ShellCheck <https://github.com/koalaman/shellcheck>`__ to find bash
   errors locally.

Code checks
-----------

If the development environment is set up correctly, the following tools
will automatically check the code. If there is any problem with the
development environment settings, please feel free to submit an issue to
us or create a pull request for repair. You can also run the check
manually.

-  `Black <https://github.com/psf/black>`__, the opinionated code
   formatter resolves all disputes about how to format our Python files.
   This will become clearer after following `PEP
   8 <https://www.python.org/dev/peps/pep-0008/>`__ (official Python
   style guide).
-  `Flake8 <https://flake8.pycqa.org/en/latest/>`__ (and integrations),
   the semantic analyzer, used to coordinate most other tools.
-  `isort <https://timothycrosley.github.io/isort/>`__, the ``import``
   sorter, it will automatically divide the import into the expected
   alphabetical order.
-  `mypy <http://mypy-lang.org/>`__, the static type checker, which
   allows us to find potential errors by annotating and checking types.
-  `rope <https://github.com/python-rope/rope>`__, provides completion
   and renaming support for pyls.

Using Nox
---------

Nox is test automation utility that allows running tests and utilities in
virtual environments. This allows isolation and consistency for these actions.

Sessions
~~~~~~~~

Nox tasks are called sessions. A number of Nox sessions have been configured
for LISA. They can be displayed by running ``nox --list``.

.. code:: console

   $  nox --list
   Nox configuration file
   See https://nox.thea.codes/en/stable/config.html

   Sessions defined in /srv/Development/lisa/noxfile.py:

   * test -> Run tests
   * example -> Run example
   * coverage -> Check test coverage
   * black -> Run black
   * isort -> Run isort
   * flake8 -> Run flake8
   * mypy -> Run mypy
   * docs -> Build docs
   * dev -> Create virtual environment for development

   sessions marked with * are selected, sessions marked with - are skipped.

An individual session can be run with ``nox -vs <session>``.

.. code:: console

   $ nox -vs flake8
   nox > Running session flake8
   nox > Creating virtual environment (virtualenv) using python3 in .nox/flake8
   ...
   nox > flake8
   nox > Session flake8 was successful.

Tags
~~~~

Another way to call Nox sessions is with tags. Tags can not currently be
listed on the command line, but the following have been define:

all
   Runs various checks and tests to do before pushing a commit

format
   Run formatting tools such as isort and black

linting
   Run linting tools such as flake8

test
   Run unit tests and test scenarios

typing
   Run typing tools such as mypy


To execute all sessions with a given tag, use the ``-t`` option.

.. code:: console

   $ nox -vt format
   nox > Running session black
   ...
   nox > Running session isort
   ...
   nox > Ran multiple sessions:
   nox > * black: success
   nox > * isort: success


To determine which sessions will be called for a tag without running them,
use the ``--list`` option.

.. code:: console

   $ nox -t format --list
   Nox configuration file
   See https://nox.thea.codes/en/stable/config.html

   Sessions defined in /srv/Development/lisa/noxfile.py:

   - test -> Run tests
   - example -> Run example
   - coverage -> Check test coverage
   * black -> Run black
   * isort -> Run isort
   - flake8 -> Run flake8
   - mypy -> Run mypy
   - docs -> Build docs
   - dev -> Create virtual environment for development

Running with a different Python interpreter
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The Nox sessions for LISA are configured to run with the same Python interpreter
used to run Nox. To use a different interpreter, use the `--force-python` option.
You can either specify a Python version or the path to an executable.

.. code:: console

   $ nox -vs test --force-python 3.12

.. code:: console

   $ nox -vs test --force-python /usr/bin/python3.12

Speeding up Nox
~~~~~~~~~~~~~~~

By default, Nox will recreate a virtual environment every time it runs.
This ensures there are no stale dependencies, but is not always necessary.
To reuse a virtual environment, use the ``-r`` option. To reuse the virtual
environment without reinstalling any dependencies, use the ``-R`` option.
This will have a greater impact for sessions with a large number of
dependencies.


.. code:: console

   $ time nox -vs flake8
   ...
   real    0m9.827s

   $ time nox -vrs flake8
   ...
   real    0m6.433s

   $ time nox -vRs flake8
   ...
   real    0m5.638s



Additional information
~~~~~~~~~~~~~~~~~~~~~~

More information on Nox can be found `here <https://nox.thea.codes>`_.

Local Documentation
-------------------

It's recommended to build the documentation locally using ``Sphinx`` for preview.

To do so, run

.. code:: bash

   nox -vs docs

You can find all generated documents in ``./lisa/docs/_build/html`` folder. Open
them with a browser to view.


Extended reading
----------------

-  `Python Design Patterns <https://python-patterns.guide/>`__. A
   fantastic collection of material for using Python's design patterns.
-  `The Hitchhiker's Guide to
   Python <https://docs.python-guide.org/>`__. This handcrafted guide
   exists to provide both novice and expert Python developers a best
   practice handbook for the installation, configuration, and usage of
   Python on a daily basis.
-  LISA performs static type checking to help finding bugs. Learn more
   from `mypy cheat
   sheet <https://mypy.readthedocs.io/en/latest/cheat_sheet_py3.html>`__
   and `typing lib <https://docs.python.org/3/library/typing.html>`__.
   You can also learn from LISA code.
-  `How to write best commit
   messages <https://tbaggery.com/2008/04/19/a-note-about-git-commit-messages.html>`__
   and `Git best
   practice <http://sethrobertson.github.io/GitBestPractices/#sausage>`__.
