"""Proof-of-concept to schedule a comprehensive test plan."""
from __future__ import annotations

import typing

import pytest

if typing.TYPE_CHECKING:
    from typing import List

    from _pytest.config import Config

    from pytest import Item, Session


def pytest_collection_modifyitems(
    session: Session, config: Config, items: List[Item]
) -> None:
    """For each item keep only instances using the feature."""
    keep: List[Item] = []
    for item in items:
        marker = item.get_closest_marker("feature")
        if marker is None:
            continue
        feature = marker.args[0]
        if item.name.endswith(f"[{feature}]"):
            keep.append(item)
    items[:] = keep


@pytest.fixture(scope="session", autouse=True, params=["xdp", "gpu", "rdma"])
def feature(request) -> str:
    yield request.param
