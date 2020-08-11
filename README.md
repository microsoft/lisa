# Linux Integration Services Automation 3.0 (LISAv3)

[![CI Workflow for LISAv3](https://github.com/LIS/LISAv2/workflows/CI%20Workflow%20for%20LISAv3/badge.svg?branch=main)](https://github.com/LIS/LISAv2/actions?query=workflow%3A%22CI+Workflow+for+LISAv3%22+event%3Apush+branch%3Amain)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![GitHub license](https://img.shields.io/github/license/LIS/LISAv2)](https://github.com/LIS/LISAv2/blob/main/LICENSE-2.0.txt)

LISAv3 is a fresh new toolkit, and at its earliest stage. We are redeveloping
LISA in Python and to support both Windows and Linux.

## Getting Started

### Install Poetry

Install your system’s Python package (either from your Linux distribution’s
package repositories, or directly from [Python](https://www.python.org/) for
Windows). It used for bootstrapping [Poetry](https://python-poetry.org/docs/),
then install Poetry:

On Linux (or WSL):

```bash
curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py | python3
PATH=$PATH:$HOME/.poetry/bin
```

On Windows (in PowerShell):

```powershell
(Invoke-WebRequest -Uri https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py -UseBasicParsing).Content | python
# the path can be added to system, so it applies to every terminal.
$env:PATH += ";$env:USERPROFILE\.poetry\bin"
```

Then use Poetry to install our Python package dependencies:

```bash
poetry install
```

Now run LISAv3 using Poetry’s environment:

```bash
poetry run python lisa/main.py
```

You can also use `poetry shell` to drop into new shell where the first `python`
in `PATH` is the virtualenv’s Python.

To obtain the path of the Poetry virtual environment setup for LISA (where the
isolated Python installation and packages are located), run:

```bash
poetry env list --full-path
```

This command is the same for Windows and Linux, and it should show something like:

```cmd
/home/<username>/.cache/pypoetry/virtualenvs/lisa-s7Q404Ij-py3.8 (Activated)
C:\Users\<username>\AppData\Local\pypoetry\Cache\virtualenvs\lisa-WNmvsOCZ-py3.8 (Activated)
```

“Activated” means you have successfully used Poetry to create the isolated
virtual environment for our Python distribution and packages.

### Editor Setup

This is subject to change as we intend to make as much of it automatic as possible.

#### Visual Studio Code

First, click the Python version in the bottom left, then enter the path emitted
by the command above. This will point Code to the Poetry virtual environment.

Make sure below settings are in root level of `.vscode/settings.json`

```json
{
    "python.analysis.typeCheckingMode": "strict",
    "python.formatting.provider": "black",
    "python.linting.enabled": true,
    "python.linting.flake8Enabled": true,
    "python.linting.mypyEnabled": true,
    "python.linting.pylintEnabled": false,
    "python.linting.pylintUseMinimalCheckers": false,
    "editor.formatOnSave": true,
    "python.analysis.diagnosticMode": "workspace",
    "python.linting.mypyArgs": [
        "--strict",
        "--namespace-packages",
        "--show-column-numbers",
    ],
    "python.sortImports.path": "isort",
    "python.analysis.useLibraryCodeForTypes": false,
    "python.analysis.autoImportCompletions": false,
}
```

#### Emacs

Use the [pyvenv](https://github.com/jorgenschaefer/pyvenv) package:

```emacs-lisp
(use-package pyvenv
  :ensure t
  :hook (python-mode . pyvenv-tracking-mode))
```

Then run `M-x add-dir-local-variable RET python-mode RET pyvenv-activate RET
<path/to/virtualenv>` where the value is the path given by the command above.
This will create a `.dir-locals.el` file which looks like this:

```emacs-lisp
;;; Directory Local Variables
;;; For more information see (info "(emacs) Directory Variables")

((python-mode . ((pyvenv-activate . "~/.cache/pypoetry/virtualenvs/lisa-s7Q404Ij-py3.8"))))
```
