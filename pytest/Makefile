all: setup test run

# Install Python packages
setup:
	@poetry install --no-ansi --remove-untracked

# Run Pytest
run:
	@poetry run python -m pytest -rA --capture=tee-sys --tb=short

# Run local tests
test:
	@poetry run python -m pytest -rA --capture=tee-sys --tb=short selftests/

# Run semantic analysis
check:
	@poetry run python -X dev -X tracemalloc -m pytest --flake8 --mypy -m 'flake8 or mypy'

smoke:
	@poetry run python -m pytest -rA --capture=tee-sys -k smoke

# Print current Python virtualenv
venv:
	@poetry env list --no-ansi --full-path
