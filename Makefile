format: 
	@nox -vRt format

isort:
	@nox -vRs isort

black:
	@nox -vRs black

flake8:
	@nox -vRs flake8

mypy:
	@nox -vRs mypy

check: isort black flake8 mypy

install: 
	@nox -vs dev -- azure
	
all:
	@nox -vRt all