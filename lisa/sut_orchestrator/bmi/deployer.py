# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
"""
BMI environment deployer.

Deploys a bare-metal-instance environment to Azure using a Bicep template
(``bmi.bicep``) — the source of truth — compiled to an ARM JSON artifact
(``autogen_bmi_template.json``) that is committed alongside the source and
loaded at runtime via the Azure Python SDK. We never shell out to ``az`` or
to ``bicep`` at runtime. After the template completes, the deployer:

  * fetches the jumphost public IP and the BMI private IPs via the SDK;
  * SSHes into the jumphost (paramiko) to configure iptables SNAT/DNAT rules
    that map ``jumphost_public_ip:nat_port`` to ``bmi_internal_ip:22``;
  * persists the iptables rules so they survive reboots.

The class exposes :meth:`deploy` and :meth:`delete`. The platform glue code
wraps these to plug into LISA's Platform lifecycle.
"""

from __future__ import annotations

import base64
import json
import socket
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from azure.core.credentials import TokenCredential
from azure.core.exceptions import ResourceNotFoundError
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.resource import ResourceManagementClient
from msrestazure.azure_cloud import AZURE_PUBLIC_CLOUD

from lisa.environment import Environment
from lisa.sut_orchestrator.azure.credential import build_compute_credential
from lisa.util import LisaException, plugin_manager
from lisa.util.logger import Logger

from .schema import BmiDeploymentInfo, BmiNodeContext, BmiPlatformSchema

_TEMPLATE_FILE = Path(__file__).parent / "autogen_bmi_template.json"


class BmiDeployer:
    """High-level orchestrator for a BMI environment deployment."""

    def __init__(self, runbook: BmiPlatformSchema, log: Logger) -> None:
        self._runbook = runbook
        self._log = log
        # Cached SDK clients.
        self._credential: Optional[TokenCredential] = None
        self._resource_client: Optional[ResourceManagementClient] = None
        self._network_client: Optional[NetworkManagementClient] = None
        self._compute_client: Optional[ComputeManagementClient] = None
        # Set by deploy() so _deploy_template can pass it through pluggy hooks.
        self._environment: Optional[Environment] = None
        # Throttle agent-IP NSG refresh: at most one Azure update per minute.
        self._last_nsg_refresh_ts: float = 0.0
        self._nsg_refresh_min_interval_s: float = 60.0
        # BMI fleet size, set by BmiPlatform from ``nodes_requirement``
        # before deploy() runs. No static fallback in the runbook schema.
        self.bmi_count: int = 0
        # Jumphost SSH credentials generated/discovered at deploy time.
        # Not user-facing runbook fields.
        self.jumphost_public_key_data: str = ""
        self.jumphost_private_key_file: str = ""

    # ─── public API ─────────────────────────────────────────────────────

    def deploy(self, environment: Optional[Environment] = None) -> BmiDeploymentInfo:
        """Create the full BMI environment and return its connection info."""
        self._environment = environment
        self._validate_runbook()
        rg_name = self._resolve_rg_name()
        location = self._runbook.location

        self._log.info(
            f"BMI deploy: rg='{rg_name}' location='{location}' "
            f"bmi_count={self.bmi_count}"
        )

        # 1. Ensure resource group exists.
        self._ensure_resource_group(rg_name, location)

        try:
            if self._runbook.reuse_existing:
                # Discover existing resources without re-submitting ARM.
                self._log.info(
                    f"reuse_existing=true; discovering resources in '{rg_name}'"
                )
                name_prefix, jumphost_public_ip_name = self._discover_existing(rg_name)
                jumphost_public_ip = self._get_public_ip(
                    rg_name, jumphost_public_ip_name
                )
                node_contexts = self._collect_bmi_node_contexts(
                    rg_name=rg_name,
                    name_prefix=name_prefix,
                    jumphost_public_ip=jumphost_public_ip,
                )
                # NAT already configured on prior deploy; skip re-setup.
            else:
                # 2. Run the ARM template deployment (the full BMI environment).
                outputs = self._deploy_template(rg_name)

                # 3. Discover IPs from the deployed resources.
                name_prefix = str(outputs["bmiNamePrefix"]).rstrip("_")
                jumphost_public_ip = self._get_public_ip(
                    rg_name, outputs["jumphostPublicIpName"]
                )
                node_contexts = self._collect_bmi_node_contexts(
                    rg_name=rg_name,
                    name_prefix=name_prefix,
                    jumphost_public_ip=jumphost_public_ip,
                )

                # 4. Configure NAT (DNAT + SNAT) on the jumphost via SSH and persist.
                self._configure_jumphost_nat(
                    jumphost_public_ip=jumphost_public_ip,
                    node_contexts=node_contexts,
                )
        except Exception:
            # Best-effort cleanup so a failed deploy does not leak quota.
            if self._runbook.delete_on_cleanup:
                self._log.info(f"deploy failed; deleting resource group '{rg_name}'")
                try:
                    self._rm_client.resource_groups.begin_delete(rg_name)
                except Exception as cleanup_err:
                    self._log.info(
                        f"failed to start cleanup of '{rg_name}': {cleanup_err}"
                    )
            raise

        info = BmiDeploymentInfo(
            resource_group=rg_name,
            location=location,
            jumphost_public_ip=jumphost_public_ip,
            nodes=node_contexts,
        )
        self._log.info(
            f"BMI deploy complete: jumphost={jumphost_public_ip}, "
            f"nodes={[(n.public_address, n.public_port) for n in node_contexts]}"
        )
        return info

    def delete(self, rg_name: str) -> None:
        """Tear down the resource group containing the BMI environment."""
        if not self._runbook.delete_on_cleanup:
            self._log.info(
                f"delete_on_cleanup=false; leaving resource group '{rg_name}' intact"
            )
            return
        self._log.info(f"BMI cleanup: deleting resource group '{rg_name}'")
        try:
            poller = self._rm_client.resource_groups.begin_delete(rg_name)
            poller.wait(timeout=self._runbook.deployment_timeout)
        except ResourceNotFoundError:
            self._log.info(f"resource group '{rg_name}' is already gone")

    def refresh_nsg_for_agent_ip(self, rg_name: str) -> None:
        """Re-resolve the LISA agent's external IP and update the NSG.

        Throttled to ``_nsg_refresh_min_interval_s`` to avoid hammering ARM
        when the reboot tool retries connection probes back-to-back. Fans
        out to all registered ``bmi_refresh_nsg_for_agent_ip`` hook
        implementations (e.g. ``extensions.bmi_nsg_enablement``).
        """
        now = time.time()
        if now - self._last_nsg_refresh_ts < self._nsg_refresh_min_interval_s:
            return
        self._last_nsg_refresh_ts = now
        nsg_name = f"{rg_name}_nsg"
        nat_start = int(self._runbook.nat_port_start)
        bmi_count = int(self.bmi_count)
        nat_range = f"{nat_start}-{nat_start + bmi_count - 1}"
        dest_ports = ["22", nat_range]
        self._log.info(
            f"BMI NSG refresh: triggering for rg='{rg_name}' nsg='{nsg_name}'"
        )
        try:
            plugin_manager.hook.bmi_refresh_nsg_for_agent_ip(
                net_client=self._net_client,
                rg_name=rg_name,
                nsg_name=nsg_name,
                dest_ports=dest_ports,
            )
        except Exception as e:  # noqa: BLE001
            self._log.warning(f"BMI NSG refresh hook error (ignored): {e}")

    # ─── runbook validation ────────────────────────────────────────────

    def _validate_runbook(self) -> None:
        missing: List[str] = []
        if not self._runbook.subscription_id:
            missing.append("subscription_id")
        if not self._runbook.location:
            missing.append("location")
        if not self._runbook.bmi_image_sig:
            missing.append("bmi_image_sig")
        if self.bmi_count <= 0:
            missing.append("bmi_count (no nodes_requirement set on environment)")
        if missing:
            raise LisaException(
                "BMI platform runbook missing required field(s): " + ", ".join(missing)
            )
        if not self._runbook.bmi_password and not self._runbook.bmi_private_key_file:
            raise LisaException(
                "BMI platform runbook must set either 'bmi_password' or "
                "'bmi_private_key_file' for SSH access to BMI nodes"
            )
        if not _TEMPLATE_FILE.is_file():
            raise LisaException(f"BMI ARM template not found at {_TEMPLATE_FILE}")

    def _resolve_rg_name(self) -> str:
        if self._runbook.resource_group_name:
            return self._runbook.resource_group_name
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        return f"lisa_bmi_{stamp}"

    # ─── Azure SDK helpers ─────────────────────────────────────────────

    @property
    def _cred(self) -> TokenCredential:
        if self._credential is None:
            # Reuse AzurePlatform's auth resolution (typed credential
            # subobject → SP env-var shortcut → ARM token → Default).
            self._credential = build_compute_credential(
                credential_schema=self._runbook.credential,
                service_principal_tenant_id=(self._runbook.service_principal_tenant_id),
                service_principal_client_id=(self._runbook.service_principal_client_id),
                service_principal_key=self._runbook.service_principal_key,
                azure_arm_access_token=self._runbook.azure_arm_access_token,
                cloud=AZURE_PUBLIC_CLOUD,
                logger=self._log,
            )
        return self._credential

    @property
    def _rm_client(self) -> ResourceManagementClient:
        if self._resource_client is None:
            self._resource_client = ResourceManagementClient(
                credential=self._cred,
                subscription_id=self._runbook.subscription_id,
            )
        return self._resource_client

    @property
    def _net_client(self) -> NetworkManagementClient:
        if self._network_client is None:
            self._network_client = NetworkManagementClient(
                credential=self._cred,
                subscription_id=self._runbook.subscription_id,
            )
        return self._network_client

    @property
    def _cmp_client(self) -> ComputeManagementClient:
        if self._compute_client is None:
            self._compute_client = ComputeManagementClient(
                credential=self._cred,
                subscription_id=self._runbook.subscription_id,
            )
        return self._compute_client

    def get_vm_size_capabilities(
        self, vm_size: str, location: str
    ) -> Optional[Dict[str, str]]:
        """Return the raw capabilities dict for ``vm_size`` at ``location``.

        Queries Azure ``Microsoft.Compute/resourceSkus`` and returns the SKU's
        ``capabilities`` list flattened into a ``{name: value}`` mapping (the
        same shape consumed by ``AzurePlatform._resource_sku_to_capability``).
        Returns ``None`` when the SKU is not found or the lookup fails — the
        caller is expected to fall back to a generic capability.
        """
        try:
            paged = self._cmp_client.resource_skus.list(
                filter=f"location eq '{location}'"
            )
            for sku in paged:
                if (
                    sku.resource_type == "virtualMachines"
                    and sku.name
                    and sku.name.lower() == vm_size.lower()
                ):
                    raw: Dict[str, str] = {}
                    if sku.capabilities:
                        for cap in sku.capabilities:
                            raw[cap.name] = cap.value
                    return raw
        except Exception as e:
            self._log.debug(
                f"BMI capability lookup failed for " f"'{vm_size}' in '{location}': {e}"
            )
            return None
        self._log.debug(f"BMI VM size '{vm_size}' not found in location '{location}'")
        return None

    def _ensure_resource_group(self, name: str, location: str) -> None:
        self._rm_client.resource_groups.create_or_update(name, {"location": location})

    def _deploy_template(self, rg_name: str) -> Dict[str, Any]:
        with _TEMPLATE_FILE.open("r", encoding="utf-8") as f:
            template_body = json.load(f)
        parameters = self._build_template_parameters(rg_name)

        # Let extensions mutate the template before submission (e.g. inject
        # additional NSG rules for trusted Microsoft service tags + agent IP).
        plugin_manager.hook.bmi_update_arm_template(
            template=template_body,
            parameters=parameters,
            environment=self._environment,
        )

        # Persist the rendered template + parameters for debugging.
        log_dir = Path.cwd()
        try:
            (log_dir / f"bmi_template_{rg_name}.json").write_text(
                json.dumps(template_body, indent=2), encoding="utf-8"
            )
            redacted = {
                k: ({"value": "***"} if "password" in k.lower() else v)
                for k, v in parameters.items()
            }
            (log_dir / f"bmi_parameters_{rg_name}.json").write_text(
                json.dumps(redacted, indent=2), encoding="utf-8"
            )
        except OSError as e:
            # Non-fatal: failure to write debug artifacts must not block deploy.
            self._log.debug(f"unable to write template debug files: {e}")

        # Submit the deployment via direct REST PUT at apiVersion 2024-11-01.
        # The azure-mgmt-resource SDK pins the deployments operation to its
        # bundled apiVersion (currently 2021-04-01); on that older apiVersion
        # the BareMetal Instance RP's create path hits an Azure Policy modify
        # effect (AzSecPack/Defender) that injects an 'identity' property the
        # BMI RP rejects with "Property 'identity' is not supported on a
        # BareMetal Instance". 'az vm create' avoids this by using
        # apiVersion 2024-11-01 for the outer deployment.
        return self._submit_deployment_rest(
            rg_name=rg_name,
            template_body=template_body,
            parameters=parameters,
        )

    def _submit_deployment_rest(
        self,
        rg_name: str,
        template_body: Dict[str, Any],
        parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        import requests

        subscription = self._runbook.subscription_id
        deployment_name = f"bmi_deploy_{datetime.utcnow():%Y%m%d_%H%M%S}"
        scope = "https://management.azure.com/.default"

        def _auth_headers() -> Dict[str, str]:
            tok = self._cred.get_token(scope).token
            return {
                "Authorization": f"Bearer {tok}",
                "Content-Type": "application/json",
            }

        url = (
            f"https://management.azure.com/subscriptions/{subscription}"
            f"/resourcegroups/{rg_name}/providers/Microsoft.Resources"
            f"/deployments/{deployment_name}?api-version=2024-11-01"
        )
        body = {
            "properties": {
                "template": template_body,
                "parameters": parameters,
                "mode": "Incremental",
            }
        }
        self._log.info(f"submitting ARM deployment '{deployment_name}'")
        response = requests.put(
            url, headers=_auth_headers(), data=json.dumps(body), timeout=300
        )
        if response.status_code not in (200, 201):
            raise LisaException(
                f"deployment '{deployment_name}' PUT failed: "
                f"{response.status_code} {response.text}"
            )

        # Poll deployment until terminal. Refresh token each iteration so we
        # do not silently start getting 401s after the initial token expires.
        deadline = time.time() + float(self._runbook.deployment_timeout)
        last_state = ""
        while True:
            try:
                poll = requests.get(url, headers=_auth_headers(), timeout=60)
            except requests.RequestException as e:
                self._log.debug(f"deployment poll request failed: {e}")
                if time.time() > deadline:
                    raise LisaException(
                        f"timed out waiting for deployment '{deployment_name}'"
                    )
                time.sleep(15)
                continue
            if poll.status_code == 200:
                props = poll.json().get("properties", {})
                state = props.get("provisioningState", "")
                if state != last_state:
                    self._log.info(f"deployment '{deployment_name}' state: {state}")
                    last_state = state
                if state == "Succeeded":
                    outputs: Dict[str, Any] = {}
                    for k, v in (props.get("outputs") or {}).items():
                        outputs[k] = v.get("value") if isinstance(v, dict) else v
                    if not outputs:
                        raise LisaException(
                            f"ARM deployment '{deployment_name}' returned " "no outputs"
                        )
                    return outputs
                if state in ("Failed", "Canceled"):
                    raise LisaException(
                        f"deployment '{deployment_name}' failed: "
                        f"{json.dumps(props.get('error') or props)}"
                    )
            else:
                self._log.debug(
                    f"deployment poll returned {poll.status_code}: "
                    f"{poll.text[:500]}"
                )
            if time.time() > deadline:
                raise LisaException(
                    f"timed out waiting for deployment '{deployment_name}'"
                )
            time.sleep(15)

    def _ensure_jumphost_auth(self, rg_name: str) -> None:
        """Make sure the jumphost has a usable credential.

        Resolution order:
          1. ``jumphost_private_key_file`` set in the runbook -> derive the
             OpenSSH public key from it and use that. ``<file>.pub`` is
             preferred when present, otherwise it's generated from the
             private key.
          2. A previously-injected key on the deployer instance -> reuse.
          3. ``jumphost_password`` set -> password auth, no key generated.
          4. Nothing supplied -> auto-generate a 2048-bit RSA keypair next
             to the artifacts dir (private key chmod 0600), stash both the
             path and the public key on the deployer so it flows into the
             ARM template and the post-deploy SSH session.
        """
        import paramiko

        from lisa.secret import add_secret

        # (1) BYO key from the runbook.
        runbook_key = self._runbook.jumphost_private_key_file
        if runbook_key and not self.jumphost_private_key_file:
            key_path = Path(runbook_key).expanduser()
            if not key_path.is_file():
                raise LisaException(
                    f"jumphost_private_key_file '{runbook_key}' does not exist"
                )
            pub_path = Path(str(key_path) + ".pub")
            if pub_path.is_file():
                pub_line = pub_path.read_text(encoding="utf-8").strip()
            else:
                rsa_key = paramiko.RSAKey.from_private_key_file(str(key_path))
                pub_line = f"{rsa_key.get_name()} {rsa_key.get_base64()} lisa-bmi"
            self.jumphost_private_key_file = str(key_path)
            self.jumphost_public_key_data = pub_line
            self._log.info(f"using runbook-supplied jumphost key '{key_path}'")
            return

        # (2) Already populated by an earlier call / programmatic injection.
        if self.jumphost_public_key_data:
            return

        # (3) Password-only path; nothing to generate.
        if self._runbook.jumphost_password:
            return

        # (4) Auto-generate.
        key_dir = Path.cwd()
        key_path = key_dir / f"bmi_jumphost_{rg_name}_id_rsa"
        pub_path = Path(str(key_path) + ".pub")

        rsa_key = paramiko.RSAKey.generate(2048)
        rsa_key.write_private_key_file(str(key_path))
        try:
            import os

            os.chmod(str(key_path), 0o600)
        except OSError:
            # Windows / unsupported FS: best-effort.
            pass
        pub_line = f"{rsa_key.get_name()} {rsa_key.get_base64()} lisa-bmi"
        pub_path.write_text(pub_line + "\n", encoding="utf-8")

        self.jumphost_private_key_file = str(key_path)
        self.jumphost_public_key_data = pub_line
        add_secret(pub_line)
        self._log.info(
            f"generated jumphost SSH keypair at '{key_path}' (private) and "
            f"'{pub_path}' (public)"
        )

    def _build_template_parameters(self, rg_name: str) -> Dict[str, Any]:
        # Ensure jumphost SSH auth is configured before building params.
        self._ensure_jumphost_auth(rg_name)

        # ARM expects {"name": {"value": ...}} pairs.
        # ARM ``namePrefix`` is reused as the per-resource prefix. Reuse the
        # resource group name (already unique and matches the reference shell
        # script's naming convention).
        params: Dict[str, Any] = {
            "namePrefix": {"value": rg_name},
            "location": {"value": self._runbook.location},
            "bmiCount": {"value": self.bmi_count},
            "bmiHostSku": {"value": self._runbook.bmi_host_sku},
            "jumphostVmSize": {"value": self._runbook.jumphost_vm_size},
            "jumphostUsername": {"value": self._runbook.jumphost_username},
            "jumphostPassword": {"value": self._runbook.jumphost_password},
            "jumphostPublicKey": {"value": self.jumphost_public_key_data},
            "vnetAddressPrefix": {"value": self._runbook.vnet_address_prefix},
            "externalSubnetPrefix": {"value": self._runbook.external_subnet_prefix},
            "internalSubnetPrefix": {"value": self._runbook.internal_subnet_prefix},
            "natPortStart": {"value": self._runbook.nat_port_start},
            "bmiVmSize": {"value": self._runbook.bmi_vm_size},
            "bmiImageId": {"value": self._runbook.bmi_image_sig},
        }
        # Decompose the Canonical-style URN into the four image fields. The
        # URN is "publisher:offer:sku:version".
        urn_parts = self._runbook.jumphost_image.split(":")
        if len(urn_parts) == 4:
            params["jumphostImagePublisher"] = {"value": urn_parts[0]}
            params["jumphostImageOffer"] = {"value": urn_parts[1]}
            params["jumphostImageSku"] = {"value": urn_parts[2]}
            params["jumphostImageVersion"] = {"value": urn_parts[3]}
        return params

    # ─── resource discovery ────────────────────────────────────────────

    def _get_public_ip(self, rg_name: str, public_ip_name: str) -> str:
        pip = self._net_client.public_ip_addresses.get(rg_name, public_ip_name)
        if not pip.ip_address:
            raise LisaException(
                f"jumphost public IP '{public_ip_name}' has no address yet"
            )
        return str(pip.ip_address)

    def _discover_existing(self, rg_name: str) -> Tuple[str, str]:
        """For reuse_existing: find name_prefix and jumphost public IP name
        from resources already in the RG. NIC names follow the pattern
        '<prefix>_bmi_<N>_internal_nic'; public IP follows
        '<prefix>_jumphostPublicIP'."""
        # Find any BMI internal NIC to derive the name_prefix.
        # NIC name pattern: "<prefix>_<N>_internal_nic".
        import re

        name_prefix = ""
        for nic in self._net_client.network_interfaces.list(rg_name):
            if not nic.name:
                continue
            m = re.match(r"(.+_bmi)_\d+_internal_nic$", nic.name)
            if m:
                name_prefix = m.group(1)
                break
        if not name_prefix:
            raise LisaException(f"reuse_existing: no BMI NIC found in '{rg_name}'")

        # Find the jumphost public IP (only one resource of that type expected).
        public_ip_name = ""
        for pip in self._net_client.public_ip_addresses.list(rg_name):
            if pip.name:
                public_ip_name = pip.name
                break
        if not public_ip_name:
            raise LisaException(f"reuse_existing: no public IP found in '{rg_name}'")

        self._log.info(
            f"reuse_existing: discovered name_prefix='{name_prefix}', "
            f"public_ip='{public_ip_name}'"
        )
        return name_prefix, public_ip_name

    def _collect_bmi_node_contexts(
        self,
        rg_name: str,
        name_prefix: str,
        jumphost_public_ip: str,
    ) -> List[BmiNodeContext]:
        contexts: List[BmiNodeContext] = []
        for i in range(1, self.bmi_count + 1):
            nic_name = f"{name_prefix}_{i}_internal_nic"
            nic = self._net_client.network_interfaces.get(rg_name, nic_name)
            private_ip = ""
            if nic.ip_configurations:
                private_ip = nic.ip_configurations[0].private_ip_address or ""
            if not private_ip:
                raise LisaException(
                    f"could not resolve private IP for BMI NIC '{nic_name}'"
                )
            contexts.append(
                BmiNodeContext(
                    name=f"{name_prefix}_{i}",
                    internal_ip=private_ip,
                    public_address=jumphost_public_ip,
                    public_port=self._runbook.nat_port_start + (i - 1),
                    username=self._runbook.bmi_admin_username,
                    private_key_file=self._runbook.bmi_private_key_file or None,
                    password=self._runbook.bmi_password,
                )
            )
        return contexts

    # ─── post-deploy NAT setup ─────────────────────────────────────────

    def _configure_jumphost_nat(
        self,
        jumphost_public_ip: str,
        node_contexts: List[BmiNodeContext],
    ) -> None:
        # paramiko import is lazy because the rest of LISA may not need it,
        # and this keeps platform import lightweight.
        import paramiko

        self._wait_for_ssh(jumphost_public_ip, port=22, timeout=300)

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            connect_kwargs: Dict[str, Any] = dict(
                hostname=jumphost_public_ip,
                port=22,
                username=self._runbook.jumphost_username,
                timeout=60,
                allow_agent=False,
                look_for_keys=False,
            )
            if self.jumphost_private_key_file:
                connect_kwargs["key_filename"] = self.jumphost_private_key_file
            else:
                connect_kwargs["password"] = self._runbook.jumphost_password
            client.connect(**connect_kwargs)

            commands: List[str] = [
                # Enable IP forwarding (runtime and persistent).
                "echo 1 | sudo tee /proc/sys/net/ipv4/ip_forward",
                "sudo sysctl -w net.ipv4.ip_forward=1",
                # SNAT all egress out of the jumphost's external NIC. The
                # jumphost only has a single NIC, so use the first physical
                # interface (any non-loopback/docker/veth name).
                "EXT_IF=$(ip -o link show | awk -F': ' "
                "'$2 !~ /^(lo|docker|veth|cni|flannel)/ {print $2; exit}'); "
                'if [ -z "$EXT_IF" ]; then '
                '  echo "no external interface found" >&2; exit 1; '
                "fi; "
                'echo "EXT_IF=$EXT_IF"; '
                'sudo iptables -t nat -C POSTROUTING -o "$EXT_IF" '
                "-j MASQUERADE 2>/dev/null || "
                'sudo iptables -t nat -A POSTROUTING -o "$EXT_IF" '
                "-j MASQUERADE",
            ]
            # DNAT rule per BMI: public_port -> bmi_internal_ip:22.
            for ctx in node_contexts:
                commands.append(
                    f"sudo iptables -t nat -C PREROUTING -p tcp "
                    f"--dport {ctx.public_port} "
                    f"-j DNAT --to-destination {ctx.internal_ip}:22 "
                    f"2>/dev/null || "
                    f"sudo iptables -t nat -A PREROUTING -p tcp "
                    f"--dport {ctx.public_port} "
                    f"-j DNAT --to-destination {ctx.internal_ip}:22"
                )
            # Persist rules so they survive reboot.
            commands.extend(
                [
                    "sudo apt-get update -y",
                    "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "
                    "iptables-persistent",
                    "sudo netfilter-persistent save",
                ]
            )

            for cmd in commands:
                self._run_ssh(client, cmd)
            # Keep client open for the readiness wait so we can probe BMI
            # sshd from inside the VNet (bypasses NSG / fabric NAT path)
            # and run ARP-flush self-heal when only the external path is
            # stuck.
            self._wait_for_all_nat_ports(
                jumphost_public_ip, node_contexts, jumphost_client=client
            )
        finally:
            client.close()

    def _run_ssh(self, client: Any, command: str) -> None:
        # Encode the script in base64 so the remote login shell does not
        # expand $VAR / $(...) / $N before bash sees them. Without this the
        # outer sh -c expands e.g. awk's $2 and any "$EXT_IF" reference,
        # corrupting the script.
        encoded = base64.b64encode(command.encode("utf-8")).decode("ascii")
        full = f"echo {encoded} | base64 -d | bash"
        self._log.debug(f"jumphost$ {command}")
        _stdin, stdout, stderr = client.exec_command(full, timeout=600)
        rc = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        if out:
            self._log.debug(f"  stdout: {out}")
        if err:
            self._log.debug(f"  stderr: {err}")
        if rc != 0:
            raise LisaException(
                f"jumphost command failed (rc={rc}): {command}\n"
                f"stdout={out}\nstderr={err}"
            )

    def _wait_for_ssh(self, host: str, port: int, timeout: int) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with socket.create_connection((host, port), timeout=5):
                    return
            except (OSError, socket.timeout):
                time.sleep(5)
        raise LisaException(
            f"timed out after {timeout}s waiting for SSH on {host}:{port}"
        )

    def _wait_for_all_nat_ports(
        self,
        host: str,
        node_contexts: List[BmiNodeContext],
        jumphost_client: Any = None,
    ) -> None:
        # Two-stage readiness: probe the BMI sshd banner BOTH from inside
        # the jumphost (internal /24 path, bypasses NSG and the SDN edge)
        # and from this agent through the public NAT. Only mark ready when
        # both paths see the banner. If only the internal probe passes for
        # too long, the external delivery to BMI is wedged - flush the
        # jumphost ARP entry for the BMI to force re-resolution.
        deadline = time.monotonic() + self._runbook.ready_timeout
        pending = list(node_contexts)
        last_log = 0.0
        # per-node monotonic ts of first observed internal-only ready
        internal_only_since: Dict[str, float] = {}
        # per-node monotonic ts of last ARP flush attempt
        last_arp_flush: Dict[str, float] = {}
        while pending and time.monotonic() < deadline:
            still_pending: List[BmiNodeContext] = []
            for ctx in pending:
                internal_ok = self._probe_internal_ssh_banner(
                    jumphost_client, ctx.internal_ip
                )
                external_ok = self._probe_ssh_banner(host, ctx.public_port)
                if internal_ok and external_ok:
                    self._log.debug(
                        f"BMI {ctx.name} sshd ready on {host}:{ctx.public_port}"
                    )
                    internal_only_since.pop(ctx.name, None)
                    last_arp_flush.pop(ctx.name, None)
                    continue
                still_pending.append(ctx)
                now = time.monotonic()
                if internal_ok and not external_ok:
                    first = internal_only_since.setdefault(ctx.name, now)
                    stuck_for = now - first
                    last_flush = last_arp_flush.get(ctx.name, 0.0)
                    # After 60s of internal-ok / external-fail, refresh
                    # ARP. Re-fire every 120s while still wedged.
                    if stuck_for > 60 and (now - last_flush) > 120:
                        self._log.info(
                            f"BMI {ctx.name}: internal sshd ready but "
                            f"external NAT path stuck for {int(stuck_for)}s; "
                            f"flushing jumphost ARP for {ctx.internal_ip}"
                        )
                        self._flush_jumphost_arp(jumphost_client, ctx.internal_ip)
                        last_arp_flush[ctx.name] = now
                else:
                    internal_only_since.pop(ctx.name, None)
            if not still_pending:
                self._log.info("all BMI nodes have responsive sshd")
                return
            now = time.monotonic()
            if now - last_log > 60:
                remaining = int(deadline - now)
                stuck = sorted(internal_only_since.keys())
                extra = f" (internal-only: {stuck})" if stuck else ""
                self._log.info(
                    f"waiting for BMI sshd: {len(still_pending)} pending "
                    f"({[c.name for c in still_pending]}), "
                    f"{remaining}s left of ready_timeout{extra}"
                )
                last_log = now
            pending = still_pending
            time.sleep(15)
        if pending:
            stuck = sorted(internal_only_since.keys())
            extra = (
                f" (sshd up internally but external NAT path never opened: {stuck})"
                if stuck
                else ""
            )
            raise LisaException(
                "timed out waiting for BMI sshd banners on: "
                f"{[(c.name, c.public_port) for c in pending]}{extra}"
            )

    def _probe_internal_ssh_banner(
        self, jumphost_client: Any, internal_ip: str
    ) -> bool:
        # Run a banner read from the jumphost via /dev/tcp; bash exits 0
        # only when it both connects and sees data starting with 'SSH-'.
        if jumphost_client is None:
            return True
        cmd = (
            "timeout 10 bash -c 'exec 3<>/dev/tcp/" + internal_ip + "/22; "
            "head -c 4 <&3' 2>/dev/null"
        )
        try:
            _stdin, stdout, _stderr = jumphost_client.exec_command(cmd, timeout=20)
            data = stdout.read()
            rc = stdout.channel.recv_exit_status()
            return rc == 0 and data.startswith(b"SSH-")
        except Exception:
            return False

    def _flush_jumphost_arp(self, jumphost_client: Any, internal_ip: str) -> None:
        if jumphost_client is None:
            return
        # Drop the cached neighbor entry and prod a few SYNs so the kernel
        # re-ARPs immediately. Best-effort, swallow errors.
        cmd = (
            f"sudo -n ip neigh flush to {internal_ip} 2>/dev/null; "
            f"sudo -n ip -s neigh show {internal_ip} 2>/dev/null; "
            f"timeout 3 bash -c '</dev/tcp/{internal_ip}/22' "
            "2>/dev/null; true"
        )
        try:
            _stdin, stdout, _stderr = jumphost_client.exec_command(cmd, timeout=15)
            stdout.channel.recv_exit_status()
        except Exception:
            pass

    def _probe_ssh_banner(self, host: str, port: int) -> bool:
        # Open the socket and read up to 255 bytes. A live OpenSSH server
        # sends "SSH-2.0-...\r\n" within a few seconds of accept().
        try:
            with socket.create_connection((host, port), timeout=10) as sock:
                sock.settimeout(10)
                data = sock.recv(255)
                return data.startswith(b"SSH-")
        except (OSError, socket.timeout):
            return False
