# Linux Integration Services Automation 3.0 (LISAv3)

[![CI Workflow for LISAv3](https://github.com/LIS/LISAv2/workflows/CI%20Workflow%20for%20LISAv3/badge.svg?branch=main)](https://github.com/LIS/LISAv2/actions?query=workflow%3A%22CI+Workflow+for+LISAv3%22+event%3Apush+branch%3Amain)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![GitHub license](https://img.shields.io/github/license/LIS/LISAv2)](https://github.com/LIS/LISAv2/blob/main/LICENSE-2.0.txt)

LISA is a Linux test automation framework with built-in test cases to verify the quality of
Linux distributions on multiple platforms (such as Azure, On-prem HyperV, and Linux bare metal).

This version (v3) is a brand new implementation in Python 3, supports running on Windows and Linux distros.

## Getting Started

### Install Python 3

Install [Python 3.8](https://www.python.org/) from Linux distribution’s package
repositories, or [python.org](https://www.python.org/). We also need `gcc` and
the `libpython` headers for the `usjon` package.

On Ubuntu 18.04 and 20.04:

```bash
sudo apt install git python3.8 libpython3.8-dev python3-distutils python3-apt gcc
```

NOTE: If you are using WSL, installing Poetry on both Windows and Linux may
cause both platforms’ versions of Poetry to be on your path, as Windows binaries
are mapped into WSL’s `PATH`. This means that the Linux `poetry` binary _must_
appear in your `PATH` before the Windows version, or this error will appear:

> `/usr/bin/env: ‘python\r’: No such file or directory`

### Install Poetry

On Linux (or WSL):

```bash
curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py | python3 - --preview --version 1.1.3
source $HOME/.poetry/env
```

On Windows (in PowerShell):

```powershell
(Invoke-WebRequest -Uri https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py -UseBasicParsing).Content | python - --preview --version 1.1.3
# the path can be added to system, so it applies to every terminal.
$env:PATH += ";$env:USERPROFILE\.poetry\bin"
```

If you already have Poetry installed, you can update it like:

```bash
poetry self update 1.1.3
```

### Install Python packages

Then use Poetry to install LISAv3's Python package dependencies:

```bash
git clone -b main https://github.com/LIS/LISAv2.git
cd LISAv2
poetry install
```

To obtain the path of the Poetry virtual environment setup for LISA (where the
isolated Python installation and packages are located), run:

```bash
poetry env list --full-path
```

### Run LISAv3

Run LISAv3 using Poetry’s environment:

```bash
poetry run python lisa/main.py
```

### Make

We now also have a GNU Makefile that automates some tasks. Try:
```bash
# Install Python packages
make setup

# Run LISAv3
make run

# Run unit tests
make test

# Run syntactic, semantic, formatting and type checkers
make check

# Generate coverage report (slow, reruns LISAv3 and tests)
make coverage

# Print current Python virtualenv
make venv
```

### Editor Setup

Install and enable [ShellCheck](https://github.com/koalaman/shellcheck) to find
bash errors locally.

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
    "editor.formatOnSave": true,
    "python.linting.mypyArgs": [
        "--strict",
        "--namespace-packages",
        "--show-column-numbers",
    ],
    "python.sortImports.path": "isort",
    "python.analysis.useLibraryCodeForTypes": false,
    "python.analysis.autoImportCompletions": false,
    "files.eol": "\n",
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
