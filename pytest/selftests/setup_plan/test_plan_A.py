import pytest


@pytest.mark.feature("xdp")
def test_xdp_a() -> None:
    pass


@pytest.mark.feature("gpu")
def test_gpu_a() -> None:
    pass


@pytest.mark.feature("rdma")
def test_rdma_a() -> None:
    pass
