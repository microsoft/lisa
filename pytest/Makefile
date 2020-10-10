all: setup run

# Install Python packages
setup:
	@poetry install --no-ansi --remove-untracked

# Run Pytest
run:
	@poetry run python -X dev -m pytest --flake8 --mypy -rA

# Print current Python virtualenv
venv:
	@poetry env list --no-ansi --full-path
