"""Proof-of-concept to schedule a comprehensive test plan."""
from __future__ import annotations

import time
import typing

from filelock import FileLock  # type: ignore

import pytest

if typing.TYPE_CHECKING:
    from typing import List

    from _pytest.config import Config
    from _pytest.fixtures import SubRequest
    from _pytest.tmpdir import TempPathFactory

    from pytest import Item, Session


def pytest_collection_modifyitems(
    session: Session, config: Config, items: List[Item]
) -> None:
    """For each item keep only instances using the feature."""
    keep: List[Item] = []
    for item in items:
        marker = item.get_closest_marker("feature")
        if marker is None:
            keep.append(item)
            continue
        feature = marker.args[0]
        if item.name.endswith(f"[{feature}]"):
            keep.append(item)
    items[:] = keep


@pytest.fixture(scope="session", autouse=True, params=["xdp", "gpu", "rdma"])
def feature(
    request: SubRequest, tmp_path_factory: TempPathFactory, worker_id: str
) -> str:
    """Pretend that this sets up the environment."""
    assert request.param
    if worker_id == "master":
        return str(request.param)
    # Get the shared temp directory.
    tmp_dir = tmp_path_factory.getbasetemp().parent
    fn = tmp_dir / request.param
    data: str = ""
    with FileLock(str(fn) + ".lock"):
        print(f"Worker {worker_id} using feature {request.param}")
        if fn.is_file():
            data = fn.read_text()
        else:
            # Pretend to do some expensive setup and cache it.
            time.sleep(3)
            data = request.param
            fn.write_text(data)
    return data
