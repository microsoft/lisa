all: setup test run

# Install Python packages
setup:
	cd pytest && poetry install --no-ansi --remove-untracked

# Run Pytest
run:
	cd pytest && poetry run python -m pytest -rA --capture=tee-sys --tb=short

# Run local tests
test:
	cd pytest && poetry run python -m pytest --html=test.html -rA --capture=tee-sys --tb=short selftests/

# Run semantic analysis
check:
	cd pytest && poetry run python -X dev -X tracemalloc -m pytest --html=check.html --flake8 --mypy -m 'flake8 or mypy'

clean:
	cd pytest && poetry run python -m pytest --cache-clear --setup-plan

smoke:
	cd pytest && poetry run python -m pytest --quiet --html=smoke.html --self-contained-html --tb=line --show-capture=log -k smoke

# Print current Python virtualenv
venv:
	cd pytest && poetry env list --no-ansi --full-path
