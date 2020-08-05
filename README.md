# Linux Integration Services Automation 3.0 (LISAv3)

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
curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py | python
PATH=$PATH:$HOME/.poetry/bin
```

On Windows (in PowerShell):

```powershell
(Invoke-WebRequest -Uri https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py -UseBasicParsing).Content | python
$env:PATH += ";$env:USERPROFILE\.poetry\bin"
```

Then use Poetry to install our Python package dependencies:

```
poetry install
```

Now run LISAv3 using Poetry’s environment:

```
poetry run lisa/main.py
```

### Editor Setup

This is subject to change as we intend to make as much of it automatic as possible.

#### Visual Studio Code

Make sure below settings are in root level of `.vscode/settings.json`

```json
{
    "python.linting.pylintEnabled": false,
    "python.linting.flake8Enabled": true,
    "python.linting.enabled": true,
    "python.formatting.provider": "black",
    "python.linting.mypyEnabled": true,
    "python.linting.flake8Args": [
        "--max-line-length",
        "88"
    ]
}
```
