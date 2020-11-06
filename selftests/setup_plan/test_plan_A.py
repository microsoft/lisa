from conftest import LISA
from target import Target


@LISA(platform="Azure", features="xdp")
def test_xdp_a(target: Target) -> None:
    pass


@LISA(platform="Azure", features="gpu")
def test_gpu_a(target: Target) -> None:
    pass


@LISA(platform="Azure", features="rdma")
def test_rdma_a(target: Target) -> None:
    pass
