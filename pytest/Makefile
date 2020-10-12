all: setup run

# Install Python packages
setup:
	@poetry install --no-ansi --remove-untracked

# Run Pytest
run:
	@poetry run python -X dev -X tracemalloc -m pytest --flake8 --mypy -rA --tb=short

# Print current Python virtualenv
venv:
	@poetry env list --no-ansi --full-path
