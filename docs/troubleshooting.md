# Troubleshooting

- [Installation](#installation)
  - [How to use LISA in WSL](#how-to-use-lisa-in-wsl)
  - [Cannot find package after run `poetry install`](#cannot-find-package-after-run-poetry-install)
  - [Poetry related questions](#poetry-related-questions)
  - [Other issues](#other-issues)

## Installation

### How to use LISA in WSL

If you are using WSL, installing Poetry on both Windows and WSL may cause both platforms' versions of Poetry to be on your path, as Windows binaries are mapped into `PATH` of WSL. This means that the WSL `poetry` binary _must_ appear in your `PATH` before the Windows version, or this error will appear:

> `/usr/bin/env: ‘python\r’: No such file or directory`

### Cannot find package after run `poetry install`

Poetry is case sensitive. When in windows, make sure the case of path is consistent every time.

### Poetry related questions

Poetry is very useful to manage dependencies of Python. It's a virtual environment, not a complete interpreter like Conda. So make sure the right version of Python interpreter is installed and effective. Learn more about Poetry from [installation](https://python-poetry.org/docs/#installation) or [commands](https://python-poetry.org/docs/cli/).

### Other issues

Please check [known issues](https://github.com/microsoft/lisa/issues) or [file a new issue](https://github.com/microsoft/lisa/issues/new) if it doesn't exist.
