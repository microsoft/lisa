"""
Nox configuration file
See https://nox.thea.codes/en/stable/config.html
"""

import platform
import sys
from pathlib import Path

import nox
import toml

CURRENT_PYTHON = sys.executable or f"{sys.version_info.major}.{sys.version_info.minor}"
ON_WINDOWS = platform.system() == "Windows"

CONFIG = toml.load("pyproject.toml")
DEPENDENCIES = CONFIG["project"]["dependencies"]
OPTIONAL_DEPENDENCIES = CONFIG["project"]["optional-dependencies"]
NOX_DEPENDENCIES = ("nox", "toml")


# Global options
nox.options.stop_on_first_error = False
nox.options.error_on_missing_interpreters = False

# Require support for tags
nox.needs_version = ">=2022.8.7"


# --- Testing ---


@nox.session(python=CURRENT_PYTHON, tags=["test", "all"])  # type: ignore
def test(session: nox.Session) -> None:
    """Run tests"""
    session.install(
        *DEPENDENCIES, *OPTIONAL_DEPENDENCIES["azure"], *OPTIONAL_DEPENDENCIES["test"]
    )
    session.run("python", "-m", "unittest", "discover")


@nox.session(python=CURRENT_PYTHON, tags=["test", "all"])  # type: ignore
def example(session: nox.Session) -> None:
    """Run example"""
    session.install("--editable", ".", "--config-settings", "editable_mode=compat")
    session.run("lisa", "--debug")


@nox.session(python=CURRENT_PYTHON, tags=["all"])  # type: ignore
def coverage(session: nox.Session) -> None:
    """Check test coverage"""
    session.install(
        *DEPENDENCIES,
        *OPTIONAL_DEPENDENCIES["azure"],
        *OPTIONAL_DEPENDENCIES["test"],
        "coverage",
    )

    session.run("coverage", "erase")
    session.run("coverage", "run", "-m", "lisa")
    session.run("coverage", "run", "--append", "-m", "unittest", "discover")
    session.run("coverage", "report")


# --- Formatting ---


@nox.session(python=CURRENT_PYTHON, tags=["format", "all"])  # type: ignore
def black(session: nox.Session) -> None:
    """Run black"""
    session.install(*OPTIONAL_DEPENDENCIES["black"])
    session.run("black", ".")


@nox.session(python=CURRENT_PYTHON, tags=["format", "all"])  # type: ignore
def isort(session: nox.Session) -> None:
    """Run isort"""
    session.install(*OPTIONAL_DEPENDENCIES["isort"])
    session.run("isort", ".")


# --- Linting ---


@nox.session(python=CURRENT_PYTHON, tags=["lint", "all"])  # type: ignore
def flake8(session: nox.Session) -> None:
    """Run flake8"""
    session.install(
        *OPTIONAL_DEPENDENCIES["black"],
        *OPTIONAL_DEPENDENCIES["flake8"],
        *OPTIONAL_DEPENDENCIES["isort"],
    )
    session.run("flake8")


@nox.session(python=CURRENT_PYTHON, tags=["lint", "all"])  # type: ignore
def pylint(session: nox.Session) -> None:
    """Run pylint"""
    session.install(
        *DEPENDENCIES,
        *NOX_DEPENDENCIES,
        *OPTIONAL_DEPENDENCIES["aws"],
        *OPTIONAL_DEPENDENCIES["azure"],
        *OPTIONAL_DEPENDENCIES["baremetal"],
        *OPTIONAL_DEPENDENCIES["libvirt"],
        *OPTIONAL_DEPENDENCIES["ai"],
        *OPTIONAL_DEPENDENCIES["pylint"],
        *OPTIONAL_DEPENDENCIES["typing"],
    )
    session.run(
        "pylint",
        "lisa",
        "microsoft",
        "examples",
        "selftests",
        "docs/tools",
        "docs",
        "noxfile.py",
    )


# --- Typing ---


@nox.session(python=CURRENT_PYTHON, tags=["typing", "all"])  # type: ignore
def mypy(session: nox.Session) -> None:
    """Run mypy"""
    session.install(
        *DEPENDENCIES,
        *OPTIONAL_DEPENDENCIES["azure"],
        *OPTIONAL_DEPENDENCIES["ai"],
        *OPTIONAL_DEPENDENCIES["mypy"],
        *OPTIONAL_DEPENDENCIES["typing"],
        *NOX_DEPENDENCIES,
    )

    session.run("mypy", "-p", "lisa")
    session.run("mypy", "docs", "microsoft")
    session.run("mypy", "noxfile.py")


# --- Utility ---


@nox.session(python=CURRENT_PYTHON, tags=["all"])  # type: ignore
def docs(session: nox.Session) -> None:
    """Build docs"""
    session.install(
        *DEPENDENCIES,
        *OPTIONAL_DEPENDENCIES["docs"],
        *OPTIONAL_DEPENDENCIES["azure"],
        *OPTIONAL_DEPENDENCIES["aws"],
    )

    session.run("sphinx-build", "-Eab", "html", "docs", "docs/_build/html")


@nox.session(python=CURRENT_PYTHON)  # type: ignore
def dev(session: nox.Session) -> None:
    """
    Create virtual environment for development
    Positional arguments determine which extras to install, default azure,libvirt
    Example:
        nox -vs dev -- libvirt
    """

    # Determine which extra dependencies to install
    if session.posargs:
        for arg in session.posargs:
            if arg not in OPTIONAL_DEPENDENCIES:
                session.error(f"'{arg}' is not a valid extra dependency group")

        extras = ",".join(session.posargs)
    elif ON_WINDOWS:
        extras = "azure"
    else:
        extras = "azure,libvirt"

    # Determine paths
    venv_path = ".venv"

    if ON_WINDOWS:
        venv_python = str(Path(venv_path).resolve() / "Scripts" / "python.exe")
    else:
        venv_python = str(Path(venv_path).resolve() / "bin" / "python")

    # Install virtualenv, it's used to create the final virtual environment
    session.install("virtualenv")

    # Create virtual environment
    session.run(
        "virtualenv", "--python", str(session.python), "--prompt", "lisa", venv_path
    )

    # Make sure pip and setuptools are up-to-date
    session.run(
        venv_python,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "pip",
        "setuptools",
        external=True,
    )

    # Editable install of lisa and dependencies
    session.run(
        venv_python,
        "-m",
        "pip",
        "install",
        "--editable",
        f".[{extras}]",
        # Workaround for non-package directories (microsoft, examples)
        "--config-settings",
        "editable_mode=compat",
        external=True,
    )

    # Install dev tools
    session.run(
        venv_python,
        "-m",
        "pip",
        "install",
        *OPTIONAL_DEPENDENCIES["black"],
        *OPTIONAL_DEPENDENCIES["flake8"],
        *OPTIONAL_DEPENDENCIES["isort"],
        *OPTIONAL_DEPENDENCIES["mypy"],
        *OPTIONAL_DEPENDENCIES["pylint"],
        *OPTIONAL_DEPENDENCIES["typing"],
        *NOX_DEPENDENCIES,
        external=True,
    )

    # Instruct user how to activate environment
    print("\nVirtual environment installed\nTo activate:\n")
    if ON_WINDOWS:
        print(
            f"   {venv_path}\\Scripts\\activate.bat\n"
            "       OR\n"
            f"   {venv_path}\\Scripts\\activate.ps1\n"
        )

    else:
        print(f"    source {venv_path}/bin/activate\n")
