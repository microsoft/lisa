all: setup test run

# Install Python packages
setup:
	cd pytest && poetry install --no-ansi --remove-untracked

# Run Pytest
run: setup
	cd pytest && poetry run pytest

# Run local tests
test: setup
	cd pytest && poetry run pytest --keep-vms --playbook=playbook.yaml --setup-show selftests/

# Run semantic analysis
check: setup
	cd pytest && poetry run pytest --check

# Clear cache and show when each fixture would be setup and torn down.
clean:
	cd pytest && poetry run pytest --cache-clear --setup-plan

# Demonstrate test selection via YAML playbook.
yaml:
	cd pytest && poetry run pytest --collect-only --playbook=criteria.yaml

# Run the smoke test demo.
smoke:
	cd pytest && poetry run pytest --demo -n 4 --playbook=smoke.yaml

# Print current Python virtualenv
venv:
	cd pytest && poetry env list --no-ansi --full-path
