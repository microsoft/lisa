# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
"""
BMI (Bare-Metal Instance) LISA platform.

The platform deploys a jumphost + N BMI VMs in Azure via an ARM template
(see ``template.json``) and exposes each BMI as a LISA node reachable
through a per-node TCP port on the jumphost's public IP. Tests therefore
run from LISA's host as usual; SSH transparently traverses the jumphost
SNAT/DNAT.
"""

from __future__ import annotations

import copy
from typing import Any, List, Optional, Type, cast

from lisa import features, schema, search_space
from lisa.environment import Environment
from lisa.feature import Feature, reload_platform_features
from lisa.node import RemoteNode
from lisa.platform_ import Platform
from lisa.util import LisaException, NotMeetRequirementException
from lisa.util.logger import Logger

from .. import BMI
from .deployer import BmiDeployer
from .schema import BmiDeploymentInfo, BmiPlatformSchema, to_remote_node_schema


class BmiPlatform(Platform):
    """LISA platform for Azure bare-metal instances behind a jumphost."""

    def __init__(self, runbook: schema.Platform) -> None:
        super().__init__(runbook=runbook)
        self._bmi_runbook: Optional[BmiPlatformSchema] = None
        self._deployer: Optional[BmiDeployer] = None
        self._deployment_info: Optional[BmiDeploymentInfo] = None

    # ─── LISA Platform hooks ───────────────────────────────────────────

    @classmethod
    def type_name(cls) -> str:
        return BMI

    @classmethod
    def supported_features(cls) -> List[Type[Feature]]:
        # BMIs are real machines reached over SSH only; expose the same
        # generic Linux/Network features as the ``ready`` platform so most
        # non-Azure-specific tests can run unchanged.
        return [
            features.Disk,
            features.Gpu,
            features.Nvme,
            features.NetworkInterface,
            features.Infiniband,
            features.IsolatedResource,
            features.SecurityProfile,
        ]

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        runbook: BmiPlatformSchema = self.runbook.get_extended_runbook(
            BmiPlatformSchema
        )
        assert runbook, "platform runbook cannot be empty"
        self._bmi_runbook = runbook
        self._deployer = BmiDeployer(runbook=runbook, log=self._log)

    def _prepare_environment(self, environment: Environment, log: Logger) -> bool:
        # The BMI fleet size is driven by ``nodes_requirement`` when the
        # environment has one: a test asking for N nodes triggers a deploy
        # of exactly N BMIs. The runbook's ``bmi_count`` is used only as
        # the fallback when no requirement is given (e.g. environments
        # declared as ``nodes: []``). The Bicep template caps the count
        # at 16; we clamp to the same range.
        assert self._bmi_runbook is not None
        if not environment.runbook.nodes_requirement:
            return True

        required = len(environment.runbook.nodes_requirement)
        clamped = max(1, min(required, 16))
        if clamped != self._bmi_runbook.bmi_count:
            log.info(
                f"BMI fleet auto-sized to {clamped} node(s) from "
                f"environment requirement (runbook default was "
                f"{self._bmi_runbook.bmi_count})."
            )
            self._bmi_runbook.bmi_count = clamped
        if clamped < required:
            log.warn_or_raise(
                environment.warn_as_error,
                f"BMI platform supports at most 16 nodes; environment "
                f"requires {required}.",
            )
            return False

        # Reload requirement so feature settings deserialize to typed
        # objects, then match each requirement against a generous BMI
        # fleet capability. Without populating concrete capability values
        # here, LISA's matcher sees ``capability is None`` for any test
        # that has a real requirement (memory, Sriov, gpu, ...) and skips
        # the test before deploy is attempted.
        environment.runbook.reload_requirements()
        bmi_capability = self._build_bmi_capability()

        matched_caps: List[schema.NodeSpace] = []
        for req in environment.runbook.nodes_requirement:
            reload_platform_features(req, self.supported_features())
            try:
                matched = req.choose_value(bmi_capability)
            except NotMeetRequirementException as e:
                log.warn_or_raise(
                    environment.warn_as_error,
                    f"BMI capability doesn't satisfy requirement {req}: {e}",
                )
                return False
            matched_caps.append(matched)

        environment.runbook.nodes_requirement = matched_caps
        return True

    def _build_bmi_capability(self) -> schema.NodeSpace:
        """Build a generous capability NodeSpace for the BMI fleet.

        BMIs are large bare-metal machines (e.g. GB200 with high core,
        memory and GPU counts and Sriov-capable NICs). We advertise an
        accommodating capability so that perf/feature tests with explicit
        ``node_requirement`` constraints can be matched and dispatched.
        """
        assert self._bmi_runbook is not None
        cap = schema.NodeSpace()
        cap.node_count = self._bmi_runbook.bmi_count
        cap.core_count = search_space.IntRange(min=1, max=4096)
        # 8 TiB upper bound – well above any current BMI SKU.
        cap.memory_mb = search_space.IntRange(min=512, max=8 * 1024 * 1024)
        cap.gpu_count = search_space.IntRange(min=0, max=16)
        cap.disk = schema.DiskOptionSettings()
        # Default NetworkInterfaceOptionSettings advertises both Synthetic
        # and Sriov data paths.
        cap.network_interface = schema.NetworkInterfaceOptionSettings()
        return cap

    def _deploy_environment(self, environment: Environment, log: Logger) -> None:
        assert self._deployer is not None
        assert self._bmi_runbook is not None

        if self._bmi_runbook.reuse_existing:
            log.info(
                "reuse_existing=true; skipping ARM deployment. The platform "
                "expects the resource group, jumphost, and BMIs to already "
                "be in place."
            )
            # Reuse-existing path still needs to know the jumphost IP and
            # BMI IPs. Without re-deploying we ask the deployer to just
            # collect those.
            info = self._deployer.deploy()  # idempotent: ARM incremental mode
        else:
            info = self._deployer.deploy()

        self._deployment_info = info

        # Build the BMI capability once; each node will be tagged with a
        # per-node copy so LISA's matcher can re-validate the test
        # requirement against the deployed environment.
        bmi_capability = self._build_bmi_capability()

        # Materialize each BMI as a LISA node.
        for ctx in info.nodes:
            node_runbook = to_remote_node_schema(ctx)
            node = environment.create_node_from_exists(node_runbook=node_runbook)
            node.name = ctx.name
            # Advertise BMI hardware capabilities on the node so that
            # post-deploy requirement matching (Sriov, memory_mb, ...)
            # succeeds. Without this, node.capability stays as the empty
            # default Capability() and any test with a real requirement is
            # skipped with "capability is None".
            per_node_cap = copy.deepcopy(bmi_capability)
            per_node_cap.node_count = 1
            reload_platform_features(per_node_cap, self.supported_features())
            # node.capability is declared as Capability, which is a NodeSpace
            # subclass. The matcher only needs a NodeSpace at runtime.
            node.capability = cast(schema.Capability, per_node_cap)
            # create_node_from_exists() does not wire up the SSH connection
            # for RemoteNode; the standard environment loader does this in
            # _load_nodes_from_runbook. We must do it ourselves so that
            # node.connection_info / node.shell are usable.
            if isinstance(node, RemoteNode):
                node.set_connection_info_by_runbook()
            node.initialize()
            log.info(
                f"BMI node '{ctx.name}' exposed at "
                f"{ctx.public_address}:{ctx.public_port}"
            )

        if not environment.nodes:
            raise LisaException(
                "BMI deployment produced no nodes; deployment likely failed."
            )

    def _delete_environment(self, environment: Environment, log: Logger) -> None:
        assert self._deployer is not None
        if self._deployment_info and self._deployment_info.resource_group:
            self._deployer.delete(self._deployment_info.resource_group)
        else:
            log.debug(
                "no deployment info captured; nothing to delete for environment "
                f"'{environment.name}'"
            )
