# This Makefile simply automates all our tasks. Its use is optional.

all: setup run test check

# Install Python packages
setup:
	@poetry install --no-ansi --remove-untracked

# Run LISAv3
run:
	@poetry run python -X dev lisa/main.py --debug

# Run unit tests
test:
	@poetry run python -X dev -m unittest discover -v lisa

# Generate coverage report (slow, reruns LISAv3 and tests)
coverage:
	@poetry run coverage erase
	@poetry run coverage run lisa/main.py 2>/dev/null
	@poetry run coverage run --append -m unittest discover lisa 2>/dev/null
	@poetry run coverage report --skip-empty --include=lisa*,examples*,testsuites* --omit=lisa/tests/* --precision 2

# Run syntactic, semantic, formatting and type checkers
check: flake8 mypy

# This also runs Black and isort via plugins
flake8:
	@poetry run flake8

# This runs the static type checking
mypy:
	@poetry run mypy --strict --namespace-packages .

# Print current Python virtualenv
venv:
	@poetry env list --no-ansi --full-path
