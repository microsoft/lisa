"""These tests are meant to run in a CI environment."""
from node_plugin import Node


def test_basic(node: Node) -> None:
    """Basic test which creates a Node connection to 'localhost'."""
    node.local("echo Hello World")
