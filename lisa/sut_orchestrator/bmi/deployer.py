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
from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.resource import ResourceManagementClient

from lisa.sut_orchestrator.azure.common import StaticAccessTokenCredential
from lisa.util import LisaException
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

    # ─── public API ─────────────────────────────────────────────────────

    def deploy(self) -> BmiDeploymentInfo:
        """Create the full BMI environment and return its connection info."""
        self._validate_runbook()
        rg_name = self._resolve_rg_name()
        location = self._runbook.location

        self._log.info(
            f"BMI deploy: rg='{rg_name}' location='{location}' "
            f"bmi_count={self._runbook.bmi_count}"
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

    # ─── runbook validation ────────────────────────────────────────────

    def _validate_runbook(self) -> None:
        missing: List[str] = []
        if not self._runbook.deployment_subscription_id:
            missing.append("deployment_subscription_id")
        if not self._runbook.bmi_image_sig:
            missing.append("bmi_image_sig")
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
            token = self._runbook.azure_arm_access_token
            if token:
                # Token-based auth, same pattern as the lisav3 pipeline
                # (lisa_connection → az get-access-token → env var).
                # Lets the BMI deploy work inside docker without a host
                # az login session.
                self._log.info(
                    "BMI auth: using azure_arm_access_token (token credential)"
                )
                self._credential = StaticAccessTokenCredential(token)
            else:
                self._log.info(
                    "BMI auth: using DefaultAzureCredential "
                    "(no azure_arm_access_token supplied)"
                )
                # CodeQL [SM05139] DefaultAzureCredential is intentional for dev use.
                self._credential = DefaultAzureCredential()
        return self._credential

    @property
    def _rm_client(self) -> ResourceManagementClient:
        if self._resource_client is None:
            self._resource_client = ResourceManagementClient(
                credential=self._cred,
                subscription_id=self._runbook.deployment_subscription_id,
            )
        return self._resource_client

    @property
    def _net_client(self) -> NetworkManagementClient:
        if self._network_client is None:
            self._network_client = NetworkManagementClient(
                credential=self._cred,
                subscription_id=self._runbook.deployment_subscription_id,
            )
        return self._network_client

    @property
    def _cmp_client(self) -> ComputeManagementClient:
        if self._compute_client is None:
            self._compute_client = ComputeManagementClient(
                credential=self._cred,
                subscription_id=self._runbook.deployment_subscription_id,
            )
        return self._compute_client

    def _ensure_resource_group(self, name: str, location: str) -> None:
        self._rm_client.resource_groups.create_or_update(name, {"location": location})

    def _deploy_template(self, rg_name: str) -> Dict[str, Any]:
        with _TEMPLATE_FILE.open("r", encoding="utf-8") as f:
            template_body = json.load(f)
        parameters = self._build_template_parameters(rg_name)

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

        subscription = self._runbook.deployment_subscription_id
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

        If ``jumphost_public_key_data`` is already set on the runbook (caller
        injected a key) we use it as-is. Otherwise, if no password is set,
        we auto-generate a 2048-bit RSA keypair, persist the private key
        next to the deployment artifacts (mode 0600), and inject the public
        key into the runbook so it flows into the ARM template and is also
        used for the post-deploy SSH session.
        """
        if self._runbook.jumphost_public_key_data:
            return
        if self._runbook.jumphost_password:
            # Password-only path; nothing to generate.
            return

        import paramiko

        from lisa.secret import add_secret

        key_dir = Path.cwd()
        key_path = key_dir / f"bmi_jumphost_{rg_name}_id_rsa"
        pub_path = Path(str(key_path) + ".pub")

        rsa_key = paramiko.RSAKey.generate(2048)
        # Write private key.
        rsa_key.write_private_key_file(str(key_path))
        try:
            import os

            os.chmod(str(key_path), 0o600)
        except OSError:
            # Windows / unsupported FS: best-effort.
            pass
        # Compose OpenSSH-format public key line.
        pub_line = f"{rsa_key.get_name()} {rsa_key.get_base64()} lisa-bmi"
        pub_path.write_text(pub_line + "\n", encoding="utf-8")

        self._runbook.jumphost_private_key_file = str(key_path)
        self._runbook.jumphost_public_key_data = pub_line
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
            "bmiCount": {"value": self._runbook.bmi_count},
            "bmiHostSku": {"value": self._runbook.bmi_host_sku},
            "jumphostVmSize": {"value": self._runbook.jumphost_vm_size},
            "jumphostUsername": {"value": self._runbook.jumphost_username},
            "jumphostPassword": {"value": self._runbook.jumphost_password},
            "jumphostPublicKey": {"value": self._runbook.jumphost_public_key_data},
            "vnetAddressPrefix": {"value": self._runbook.vnet_address_prefix},
            "externalSubnetPrefix": {"value": self._runbook.external_subnet_prefix},
            "internalSubnetPrefix": {"value": self._runbook.internal_subnet_prefix},
            "natPortStart": {"value": self._runbook.nat_port_start},
            "sourceAddressPrefixes": {
                "value": self._runbook.nsg_source_address_prefixes
            },
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
        for i in range(1, self._runbook.bmi_count + 1):
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
            if self._runbook.jumphost_private_key_file:
                connect_kwargs["key_filename"] = self._runbook.jumphost_private_key_file
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
        finally:
            client.close()

        self._wait_for_all_nat_ports(jumphost_public_ip, node_contexts)

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
        self, host: str, node_contexts: List[BmiNodeContext]
    ) -> None:
        deadline = time.monotonic() + self._runbook.ready_timeout
        pending = [ctx.public_port for ctx in node_contexts]
        while pending and time.monotonic() < deadline:
            still_pending: List[int] = []
            for port in pending:
                try:
                    with socket.create_connection((host, port), timeout=5):
                        self._log.debug(f"NAT port {port} reachable")
                except (OSError, socket.timeout):
                    still_pending.append(port)
            if not still_pending:
                self._log.info("all BMI NAT ports are reachable")
                return
            pending = still_pending
            time.sleep(10)
        if pending:
            raise LisaException(f"timed out waiting for NAT ports: {pending}")
