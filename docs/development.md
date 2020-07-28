# Setup development environment

## Python

### Python version

LISAv3 supports `Python 64bit 3.8.3`, and prefer to use latest stable version.

### Development packages

LISAv3 use `flake, isor, black, mypy` packages to enforce basic code guideline. Below command is an example to install them.

```bash
python -m pip install flake8 isort black mypy --upgrade
```

## IDE settings

### Visual Studio Code

Make sure below settings are in root level of `.vscode/settings.json`

```json
{
    "python.linting.pylintEnabled": false,
    "python.linting.flake8Enabled": true,
    "python.linting.enabled": true,
    "python.formatting.provider": "black",
    "python.linting.mypyEnabled": true
}
```
