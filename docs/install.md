# Install LISA

- [Prerequisites](#prerequisites)
- [Install Python](#install-python)
- [Install dependencies](#install-dependencies)
- [Clone code](#clone-code)
- [Install Poetry and Python dependencies](#install-poetry-and-python-dependencies)
  - [Install Poetry in Linux](#install-poetry-in-linux)
  - [Install Poetry in Windows](#install-poetry-in-windows)
- [FAQ and Troubleshooting](#faq-and-troubleshooting)
  - [How to use LISA in WSL](#how-to-use-lisa-in-wsl)
  - [Cannot find package after run `poetry install`](#cannot-find-package-after-run-poetry-install)
  - [Poetry related questions](#poetry-related-questions)
  - [Other issues](#other-issues)

LISA supports to run on both Windows and Linux. Follow below steps to install LISA from source code.

## Prerequisites

LISA needs to be installed on a computer, which

* Can access the tested platform, like Azure, Hyper-V, or else. It recommends to have good bandwidth and low network latency.
* At least 2 CPU cores and 4GB memory.

## Install Python

LISA is developed in Python, and tested with Python 3.8 (64 bit). The latest version of Python 3.8 is recommended, but feel free to file an issue, if LISA is not compatible with higher Python version.

Install latest [Python 3.8 64 bits](https://www.python.org/). If there are Python installed already, it needs to make sure effective Python's version is above 3.8 and 64 bits.

## Install dependencies

Some Python packages need to be built from source, so it needs build tools installed.

In Linux, it needs `git` and `gcc`. Below is depended packages on Ubuntu.

```bash
sudo apt install git gcc
```

In Windows, you need to install [git](https://git-scm.com/downloads) and [Visual C++ redistributable package](https://aka.ms/vs/16/release/vc_redist.x64.exe)

## Clone code

Open a terminal window, and enter the folder, which to download lisa code.

```sh
git clone https://github.com/microsoft/lisa.git
cd lisa
```

## Install Poetry and Python dependencies

Poetry is used to manage Python dependencies of LISA. Execute corresponding script to install Poetry.

Note, it's important to enter LISA's folder to run below command, since  Poetry manages dependencies by working folders.

### Install Poetry in Linux

```bash
curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py | python3 -
source $HOME/.poetry/env
poetry install
```

### Install Poetry in Windows

Open a PowerShell command prompt and execute

```powershell
(Invoke-WebRequest -Uri https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py -UseBasicParsing).Content | python -
# the path can be added to system, so it applies to every terminal.
$env:PATH += ";$env:USERPROFILE\.poetry\bin"
poetry install
```

## FAQ and Troubleshooting

### How to use LISA in WSL

If you are using WSL, installing Poetry on both Windows and WSL may cause both platforms' versions of Poetry to be on your path, as Windows binaries are mapped into `PATH` of WSL. This means that the WSL `poetry` binary _must_ appear in your `PATH` before the Windows version, or this error will appear:

> `/usr/bin/env: ‘python\r’: No such file or directory`

### Cannot find package after run `poetry install`

Poetry is case sensitive. When in windows, make sure the cases of path is consistent every time.

### Poetry related questions

Poetry is very useful to manage dependencies of Python. It's a virtual environment, not a complete environment like Conda. So make sure the right version of Python is effective. Know more about Poetry on [installation](https://python-poetry.org/docs/#installation) or [commands](https://python-poetry.org/docs/cli/).

### Other issues

Please check [known issues](https://github.com/microsoft/lisa/issues), or [file an issue](https://github.com/microsoft/lisa/issues/new) if it doesn't exists.
