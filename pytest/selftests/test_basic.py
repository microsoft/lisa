"""These tests are meant to run in a CI environment."""
from conftest import LISA
from target import Target


@LISA
def test_basic(target: Target) -> None:
    """Basic test which creates a Node connection to 'localhost'."""
    target.local("echo Hello World")
