import pytest


@pytest.fixture(scope="session", params=["xdp", "gpu", "rdma"])
def feature(request) -> str:
    yield request.param
