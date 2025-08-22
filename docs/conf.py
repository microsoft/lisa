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

import sys
from pathlib import Path
from typing import List

# to import lisa package
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "docs"))

from tools import update_file, update_finetune_data, update_summary  # noqa: E402

# -- Project information -----------------------------------------------------

project = "Linux Integration Services Automation (LISA)"
copyright = "Microsoft Corporation"  # pylint: disable=redefined-builtin
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
autosectionlabel_maxdepth = 2

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
html_static_path: List[str] = []

html_theme_options = {
    "collapse_navigation": False,
    "navigation_depth": 2,
    "logo_only": True,
    "display_version": False,
}

# -- Test auto-generation pipelines ------------------------------------------

base_path = Path(__file__).parent

update_summary()
update_file()
update_finetune_data()
