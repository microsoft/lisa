# Install LISA

- [Install LISA](#install-lisa)
  - [Prerequisites](#prerequisites)
  - [Install Python](#install-python)
    - [Install Python in Linux](#install-python-in-linux)
    - [Install Python in Windows](#install-python-in-windows)
  - [Install dependencies](#install-dependencies)
    - [Install dependencies in Linux](#install-dependencies-in-linux)
    - [Install dependencies in Windows](#install-dependencies-in-windows)
  - [Clone code](#clone-code)
  - [Install Poetry](#install-poetry)
    - [Install Poetry in Linux](#install-poetry-in-linux)
    - [Install Poetry in Windows](#install-poetry-in-windows)
  - [FAQ and Troubleshooting](#faq-and-troubleshooting)

LISA can be used to run test against the local node, or a remote node; if it is used to run 
against a remote node, you don't need to configure anything on the remote node.

![deploy](img/deploy.svg)

LISA can be launched on a Windows or a Linux OS. Follow below steps to install LISA
on your OS.


## Prerequisites

LISA needs to be installed on a computer which has network access to the platform and the node to be tested. 

- It is recommended that this computer at least has 2 CPU cores and 4GB memory.

## Notes

:blue_book:	On Windows, after you finished an installation, or made an environment variable 
change, you might need to restart your shell before moving to next step, to make sure your 
changes take effect.

:blue_book:	Please run your command prompt or shell with elevated privilege (such as `'Run as 
Administrator'` on Windows) when you see access denied message when install tools.


## Install Python

LISA has been tested on [Python 3.8 64 bits](https://www.python.org/). The latest version of
Python 3 is recommended. If you found LISA is not compatible with higher version Python,
[please file an issue](https://github.com/microsoft/lisa/issues/new).

#### Install Python in Linux

Refer below example to install Python 3.8 in Ubuntu 20.04.

```bash
sudo apt update
sudo apt install software-properties-common -y
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt install python3.8 python3.8-dev -y
```

#### Install Python in Windows

Navigate to [Python releases for
Windows](https://www.python.org/downloads/windows/). Download and install
*Windows installer (64-bit)* from Python 3.8 64-bits or higher version.

:warning: Please make sure the `Python` directory and its `Scripts` directory are 
added to your `PATH` environment variable. For example:

```powershell
PS C:\github> echo $env:path
... ...;C:\Users\username\AppData\Local\Programs\Python\Python39;C:\Users\username\AppData\Local\Programs\Python\Python39\Scripts;... ...
```

If this is the first time you are installing Python, simply check "add Python to PATH" option in installation.

## Install dependencies

Please install `git` on your computer to clone LISA source code from this repo.

#### Install dependencies in Linux

In Linux, for example, on Ubuntu 20.04, please use below command to install the dependencies:

```bash
sudo apt install git gcc libgirepository1.0-dev libcairo2-dev virtualenv -y
```

#### Install dependencies in Windows

In Windows, you need to install [git](https://git-scm.com/downloads), 
`virtualenv`(by running ```pip install virtualenv```) and [Visual C++ 
redistributable package](https://aka.ms/vs/16/release/vc_redist.x64.exe)


## Clone code

```sh
git clone https://github.com/microsoft/lisa.git
cd lisa
```


## Install Poetry

Poetry is used to manage Python dependencies of LISA.

:warning: Please enter LISA source code root folder to run below 
command to install poetry, since Poetry manages dependencies by the working folder.

#### Install Poetry in Linux

```bash
curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/install-poetry.py | python3 -
source $HOME/.profile
poetry install
```

#### Install Poetry in Windows

Enter the `PowerShell` command prompt and then execute below commands:

```powershell
(Invoke-WebRequest -Uri https://raw.githubusercontent.com/python-poetry/poetry/master/install-poetry.py -UseBasicParsing).Content | python -

# Add poetry.exe's path to your `PATH` environment variable.
$env:PATH += ";$env:APPDATA\Python\Scripts"

poetry install
```


## FAQ and Troubleshooting

Refer to [FAQ and troubleshooting](troubleshooting.md).
