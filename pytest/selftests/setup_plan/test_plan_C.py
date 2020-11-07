import functools

import conftest
from target import Target

LISA = functools.partial(
    conftest.LISA, platform="Azure", category="Functional", area="self-test", priority=1
)


@LISA(features=["xdp"])
def test_xdp_c(target: Target) -> None:
    pass


@LISA(features=["gpu"])
def test_gpu_c(target: Target) -> None:
    pass


@LISA(features=["rdma"])
def test_rdma_c(target: Target) -> None:
    pass
