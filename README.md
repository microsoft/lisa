# Linux Integration Services Automation 3.0 (LISAv3)

[![CI Workflow for LISAv3](https://github.com/LIS/LISAv2/workflows/CI%20Workflow%20for%20LISAv3/badge.svg?branch=main)](https://github.com/LIS/LISAv2/actions?query=workflow%3A%22CI+Workflow+for+LISAv3%22+event%3Apush+branch%3Amain)
[![Code Style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![GitHub License](https://img.shields.io/github/license/LIS/LISAv2)](https://github.com/LIS/LISAv2/blob/main/LICENSE.md)

LISA is a Linux test automation framework with built-in test cases to verify the
quality of Linux distributions on multiple platforms (such as Azure, Hyper-V,
and bare metal).

## Getting Started:

### Install Python 3:

Install Python 3.7 or newer from your Linux distribution’s package repositories,
or [python.org](https://www.python.org/).

### Install Poetry:

[Poetry](https://python-poetry.org/docs/) is our preferred tool for Python
dependency management and packaging. We’ll use it to automatically setup a
‘virtualenv’ and install everything we need.

#### On Linux (or WSL):

```bash
curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py | python -
source $HOME/.poetry/env
```

If you are using WSL, installing Poetry on both Windows and Linux may cause both
platforms’ versions of Poetry to be on your path, as Windows binaries are mapped
into WSL’s `PATH`. This means that the Linux `poetry` binary _must_ appear in
your `PATH` before the Windows version, or this error will appear:

```
`/usr/bin/env: ‘python\r’: No such file or directory`
```

Adjust your `PATH` appropriately to fix it.

#### On Windows (in PowerShell):

```powershell
(Invoke-WebRequest -Uri https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py -UseBasicParsing).Content | python -
$env:PATH += ";$env:USERPROFILE\.poetry\bin"
```

### Clone LISA and `cd` into the Git repo:

```bash
git clone -b main https://github.com/LIS/LISAv2.git lisa
cd lisa
```

### Install Python dependencies:

```bash
# Install the Python packages
poetry install

# Enter the virtual environment
poetry shell
```

### Use LISA:

```bash
# Run some self-tests
lisa --playbook=playbooks/test.yml selftests/

# Run a demo which deployes Azure resources
lisa --playbooks/smoke.yaml
```

#### Enable Azure:

To run the demo you’ll need the [Azure CLI][] tool installed and configured:

```bash
# Install Azure CLI, make sure `az` is in your `PATH`
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

# Login and set subscription
az login
az account set -s <your subscription ID>
```

See the [design document](DESIGN.md) for details.

## Contributing

The path to the virtualenv used by Poetry can found with this command:

```bash
poetry env list --full-path
```

Use it to configure your editor.

### Editor Setup

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

((nil . ((pyvenv-activate . "~/.cache/pypoetry/virtualenvs/<venv name>"))))
```

### Contributor License Agreement

This project welcomes contributions and suggestions. Most contributions require
you to agree to a Contributor License Agreement (CLA) declaring that you have
the right to, and actually do, grant us the rights to use your contribution. For
details, visit https://cla.opensource.microsoft.com.

When you submit a pull request, a CLA bot will automatically determine whether
you need to provide a CLA and decorate the PR appropriately (e.g., status check,
comment). Simply follow the instructions provided by the bot. You will only need
to do this once across all repos using our CLA.

This project has adopted the [Microsoft Open Source Code of
Conduct](https://opensource.microsoft.com/codeofconduct/). For more information
see the [Code of Conduct
FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or contact
[opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional
questions or comments.

## Legal Notices

Microsoft and any contributors grant you a license to the Microsoft
documentation and other content in this repository under the [Creative Commons
Attribution 4.0 International Public
License](https://creativecommons.org/licenses/by/4.0/legalcode), see the
[LICENSE-DOCS](LICENSE-DOCS.md) file, and grant you a license to any code in the
repository under the [MIT License](https://opensource.org/licenses/MIT), see the
[LICENSE](LICENSE.md) file.

Microsoft, Windows, Microsoft Azure and/or other Microsoft products and services
referenced in the documentation may be either trademarks or registered
trademarks of Microsoft in the United States and/or other countries. The
licenses for this project do not grant you rights to use any Microsoft names,
logos, or trademarks. Microsoft's general trademark guidelines can be found at
http://go.microsoft.com/fwlink/?LinkID=254653.

Privacy information can be found at https://privacy.microsoft.com/en-us/

Microsoft and any contributors reserve all other rights, whether under their
respective copyrights, patents, or trademarks, whether by implication, estoppel
or otherwise.
