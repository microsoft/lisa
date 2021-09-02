# This Makefile simply automates all our tasks. Its use is optional.

all: setup run test check

# Install Python packages
setup:
	@poetry install --no-ansi --remove-untracked

# Run LISA
run:
	@poetry run python -X dev lisa/main.py --debug

# Run unit tests
test:
	@poetry run python -X dev -m unittest discover

# Generate coverage report (slow, reruns LISA and tests)
coverage:
	@poetry run coverage erase
	@poetry run coverage run lisa/main.py
	@poetry run coverage run --append -m unittest discover
	@poetry run coverage report --skip-empty --include=lisa*,examples*,microsoft/testsuites* --omit=lisa/tests/* --precision 2

# Run syntactic, semantic, formatting and type checkers
check: flake8 mypy

# This also runs Black and isort via plugins
flake8:
	@poetry run flake8

# This runs the static type checking
mypy:
	@poetry run mypy --strict --exclude '.venv/.*' --namespace-packages --implicit-reexport --config-file pyproject.toml -p docs -p lisa -p microsoft

# Print current Python virtualenv
venv:
	@poetry env list --no-ansi --full-path
