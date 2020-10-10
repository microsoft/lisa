from pathlib import Path

from fabric import Config, Connection  # type: ignore

import pytest

LINUX_SCRIPTS = Path("../Testscripts/Linux")


# TODO: Make the hostname a parameter.
@pytest.fixture
def node() -> Connection:
    config = Config(overrides={"run": {"in_stream": False}})
    with Connection("centos", config=config) as connection:
        yield connection


def test_lis_version(node: Connection) -> None:
    # TODO: Include “utils.sh” automatically? Or something...
    for f in ["utils.sh", "LIS-VERSION-CHECK.sh"]:
        node.put(LINUX_SCRIPTS / f)
        node.run(f"chmod +x {f}")
    node.sudo("yum install -y bc")
    # TODO: Fix this PATH issue.
    node.run(
        "PATH=$PATH:/usr/local/sbin:/usr/sbin ./LIS-VERSION-CHECK.sh",
    )
    node.get("state.txt")
    with open("state.txt") as f:
        assert f.readline().strip() == "TestCompleted"
