Development setup
=================

This document describes the existing developer tooling we have in place (and
what to expect of it).

-  `Environment Setup <#environment-setup>`__

   -  `Visual Studio Code <#visual-studio-code>`__
   -  `Emacs <#emacs>`__
   -  `Other setups <#other-setups>`__

-  `Code checks <#code-checks>`__
-  `Local Documentation <#local-documentation>`__
-  `Extended reading <#extended-reading>`__

Environment Setup
-----------------

Follow the :ref:`quick_start:installation` steps to
prepare the source code. Then follow the steps below to set up the corresponding
development environment.

Visual Studio Code
~~~~~~~~~~~~~~~~~~

1. Click on the Python version at the bottom left of the editor’s window
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
         "python.formatting.provider": "black",
         "python.linting.enabled": true,
         "python.linting.flake8Enabled": true,
         "python.linting.mypyEnabled": true,
         "python.linting.pylintEnabled": false,
         "editor.formatOnSave": true,
         "python.linting.mypyArgs": [
            "--config-file",
            "pyproject.toml"
         ],
         "python.sortImports.path": "isort",
         "editor.codeActionsOnSave": {
            "source.organizeImports": true
         },
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
            "reportUnusedFunction": "none"
         },
         "python.analysis.stubPath": "./typings",
         "python.languageServer": "Pylance"
      }

3. Install extensions.

   -  Install
      `Pylance <https://marketplace.visualstudio.com/items?itemName=ms-python.vscode-pylance>`__
      to get best code intelligence experience.
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

   ((python-mode . ((pyvenv-activate . "~/.cache/pypoetry/virtualenvs/lisa-s7Q404Ij-py3.8"))))

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

Local Documentation
-------------------

It's recommended to build the documentation locally using ``Sphinx`` for preview.

To do so, in ``./lisa/docs``, run 

.. code:: bash

   poetry run make html

You can find all generated documents in ``./lisa/docs/_build/html`` folder. Open
them with a browser to view.

.. note::
   If there are already generated documents in ``./lisa/docs/_build/html``, run
   ``poetry run make clean`` to ensure the documentation is clean and not
   affected by the previous build.

Extended reading
----------------

-  `Python Design Patterns <https://python-patterns.guide/>`__. A
   fantastic collection of material for using Python’s design patterns.
-  `The Hitchhiker’s Guide to
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
