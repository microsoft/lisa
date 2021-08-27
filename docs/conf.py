# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#
import subprocess
import sys
from pathlib import Path

import toml

root_dir = Path(__file__).parents[1]
pyproj = root_dir / "pyproject.toml"
requirement = root_dir / "docs" / "requirements.txt"

sys.path.insert(0, str(root_dir.resolve()))
sys.path.insert(0, str((root_dir / "docs" / "tools").resolve()))
sys.path.insert(0, str((root_dir / "lisa").resolve()))

data = toml.load(pyproj)
dependencies = data["tool"]["poetry"]["dependencies"]
sphinx_dependencies = data["tool"]["poetry"]["dev-dependencies"]

with open(requirement, "w") as req:
    for module, version in dependencies.items():
        if str(version)[0] != "^":
            version = version["version"]
        if str(module) in ["python", "pypiwin32", "PyGObject"]:
            continue
        req.write(str(module))
        req.write(">=")
        req.write(str(version)[1:])
        req.write("\n")

    for module, version in sphinx_dependencies.items():
        if str(module)[:6].lower() == "sphinx":
            req.write(str(module))
            req.write(">=")
            req.write(str(version)[1:])
            req.write("\n")

# -- Project information -----------------------------------------------------

project = "Linux Integration Services Automation (LISA)"
copyright = "2021, Microsoft"
author = "Microsoft"

release = ""

# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be extensions
# coming with Sphinx (named 'sphinx.ext.*') or your custom ones.
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
    "sphinxemoji.sphinxemoji",
    "sphinx.ext.autosectionlabel",
    "sphinx_copybutton",
]

autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "private-members": True,
}

autosectionlabel_prefix_document = True

# Add any paths that contain templates here, relative to this directory.
templates_path = ["_templates"]

source_suffix = [".rst"]

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files. This pattern also affects
# html_static_path and html_extra_path.
# exclude_patterns = []


# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for a
# list of builtin themes.
#
html_theme = "sphinx_rtd_theme"

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files, so
# a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ["_static"]

html_theme_options = {
    "collapse_navigation": False,
    "navigation_depth": 2,
    "logo_only": True,
    "display_version": False,
}

# -- Test auto-generation pipelines ------------------------------------------

base_path = Path(__file__).parent
test_summary_pipeline = base_path / "tools/test_summary_gen.py"
test_spec_pipeline = base_path / "tools/test_spec_gen.py"

subprocess.call(["python", test_summary_pipeline])
subprocess.call(["python", test_spec_pipeline])
