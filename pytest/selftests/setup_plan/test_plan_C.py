import pytest


@pytest.mark.feature("xdp")
def test_xdp_c() -> None:
    pass


@pytest.mark.feature("gpu")
def test_gpu_c() -> None:
    pass


@pytest.mark.feature("rdma")
def test_rdma_c() -> None:
    pass
