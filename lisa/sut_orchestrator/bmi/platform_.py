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
from typing import Any, Dict, List, Optional, Type, cast

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
        # The BMI fleet size is driven entirely by ``nodes_requirement``,
        # mirroring how ``AzurePlatform._prepare_environment`` works: a test
        # asking for N nodes triggers a deploy of exactly N BMIs. There is
        # no static ``bmi_count`` fallback.
        assert self._bmi_runbook is not None
        if not environment.runbook.nodes_requirement:
            return True

        required = len(environment.runbook.nodes_requirement)
        assert self._deployer is not None
        self._deployer.bmi_count = required
        log.info(
            f"BMI fleet sized to {required} node(s) from environment " f"requirement."
        )

        # Reload requirement so feature settings deserialize to typed
        # objects, then match each requirement against the real BMI SKU
        # capability fetched from Azure ``resourceSkus``. Without populating
        # concrete capability values here, LISA's matcher sees
        # ``capability is None`` for any test that has a real requirement
        # (memory, Sriov, gpu, ...) and skips the test before deploy.
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
        """Build a capability NodeSpace for the BMI fleet.

        BMI runs on Azure-managed bare-metal VMs, so the same
        ``Microsoft.Compute/resourceSkus`` API exposes the real per-SKU
        limits (vCPU, memory, GPU, NIC, data-disk count, etc.). We query
        that for ``bmi_vm_size`` and translate the raw capability dict
        into a generic ``schema.NodeSpace``. If the lookup fails we raise
        – there is no static fallback.
        """
        assert self._bmi_runbook is not None
        assert self._deployer is not None

        raw_caps = self._deployer.get_vm_size_capabilities(
            self._bmi_runbook.bmi_vm_size, self._bmi_runbook.location
        )
        if not raw_caps:
            raise LisaException(
                f"BMI capability for '{self._bmi_runbook.bmi_vm_size}' in "
                f"'{self._bmi_runbook.location}' could not be resolved from "
                f"Azure resourceSkus; cannot proceed without real SKU "
                f"capability values."
            )
        self._log.info(
            f"BMI capability resolved from Azure resourceSkus for "
            f"'{self._bmi_runbook.bmi_vm_size}' in "
            f"'{self._bmi_runbook.location}': {raw_caps}"
        )
        return self._capability_from_raw(raw_caps)

    def _capability_from_raw(self, raw_caps: Dict[str, str]) -> schema.NodeSpace:
        """Translate an Azure resourceSku capabilities dict into a NodeSpace.

        Mirrors the numeric/limit portion of
        ``AzurePlatform._resource_sku_to_capability`` without dragging in
        Azure-only feature settings (BMI exposes its own ``supported_features``
        list). ``raw_caps`` is the flattened ``{name: value}`` mapping for
        the SKU's ``capabilities`` array.
        """
        assert self._bmi_runbook is not None
        cap = schema.NodeSpace(
            node_count=1,
            core_count=0,
            memory_mb=0,
            gpu_count=0,
        )

        # vCPU: prefer vCPUsAvailable, fall back to vCPUs.
        vcpus_available = int(raw_caps.get("vCPUsAvailable", "0") or "0")
        if vcpus_available:
            cap.core_count = vcpus_available
        else:
            cap.core_count = int(raw_caps.get("vCPUs", "0") or "0")

        memory_value = raw_caps.get("MemoryGB", None)
        if memory_value:
            cap.memory_mb = int(float(memory_value) * 1024)

        gpus = raw_caps.get("GPUs", None)
        if gpus:
            cap.gpu_count = int(gpus)

        cap.disk = schema.DiskOptionSettings()
        max_disk_count = raw_caps.get("MaxDataDiskCount", None)
        if max_disk_count:
            cap.disk.max_data_disk_count = int(max_disk_count)
            cap.disk.data_disk_count = search_space.IntRange(max=int(max_disk_count))

        cap.network_interface = schema.NetworkInterfaceOptionSettings()
        max_nic_count = raw_caps.get("MaxNetworkInterfaces", None)
        if max_nic_count:
            sku_nic_count = int(max_nic_count) or 1
            cap.network_interface.nic_count = search_space.IntRange(
                min=1, max=sku_nic_count
            )
            cap.network_interface.max_nic_count = sku_nic_count

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
            info = self._deployer.deploy(
                environment=environment
            )  # idempotent: ARM incremental mode
        else:
            info = self._deployer.deploy(environment=environment)

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
            # Stash jumphost + internal-IP info so the generic Reboot tool
            # can probe BMI:22 directly via the jumphost when DNAT/NAT-port
            # reconnects fail.
            node._bmi_diag = {  # type: ignore[attr-defined]
                "internal_ip": ctx.internal_ip,
                "jumphost_address": ctx.public_address,
                "jumphost_port": 22,
                "jumphost_username": self._bmi_runbook.jumphost_username,
                "jumphost_password": self._bmi_runbook.jumphost_password,
                "jumphost_private_key_file": (
                    self._deployer.jumphost_private_key_file if self._deployer else ""
                ),
                # Self-heal NSG rule when the agent's SNAT egress IP rotates
                # mid-run (silent NSG drop fingerprint = TCP timeout to both
                # public NAT port and jumphost:22). The deployer throttles.
                "nsg_refresh": (
                    lambda rg=info.resource_group: (
                        self._deployer.refresh_nsg_for_agent_ip(rg)
                    )
                ),
            }
            # Wire the same NSG self-heal into the SSH shell's connect
            # failure path. This covers spawn() retries from any tool
            # (sysctl, ntttcp restore_system, etc.), not just Reboot.
            try:
                shell = getattr(node, "_shell", None)
                if shell is not None:
                    shell._pre_connect_failure_hook = node._bmi_diag[
                        "nsg_refresh"
                    ]  # type: ignore[attr-defined]
            except Exception:
                pass
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
