# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass, field
from typing import List, Optional

from dataclasses_json import dataclass_json
from marshmallow import validate

from lisa import schema
from lisa.secret import add_secret
from lisa.sut_orchestrator.azure.credential import AzureCredentialSchema
from lisa.util import constants, field_metadata


@dataclass_json()
@dataclass
class BmiPlatformSchema:
    """
    Runbook schema for the BMI (Bare-Metal Instance) platform.

    A BMI environment consists of:
      * A dedicated host group hosting one or more bare-metal VMs (BMIs).
      * A jumphost VM with a public IP that performs SNAT/DNAT (iptables) so
        LISA (running outside the VNet) can SSH into each BMI through a
        per-node TCP port on the jumphost.

    The platform deploys the environment with an ARM template and the Azure
    Python SDK, then exposes each BMI as a LISA node whose ``public_address``
    is the jumphost's public IP and whose ``public_port`` is the BMI's NAT
    port. Inside the VNet the node also has an ``address`` (BMI internal IP)
    on port 22.
    """

    # ── Azure context / authentication ─────────────────────────────────
    # Mirrors ``AzurePlatformSchema`` so the BMI platform supports the
    # full Azure auth surface: typed ``credential`` subobject (default,
    # secret, certificate, assertion, workloadidentity, token, azcli),
    # service-principal env-var shortcut, static ARM access token, or
    # fallback to ``DefaultAzureCredential``.
    #
    # Subscription used for deployment (RG, jumphost, BMI VMs). Required.
    subscription_id: str = field(
        default="",
        metadata=field_metadata(validate=validate.Regexp(constants.GUID_REGEXP)),
    )
    # Optional typed credential subobject — same factory used by
    # ``AzurePlatformSchema.credential``. When set, takes precedence over
    # the flat service-principal fields below.
    credential: Optional[AzureCredentialSchema] = field(default=None)
    # Service principal credentials. When all three are set the deployer
    # exports them as ``AZURE_TENANT_ID`` / ``AZURE_CLIENT_ID`` /
    # ``AZURE_CLIENT_SECRET`` env vars so ``DefaultAzureCredential``
    # picks them up — same pattern as ``AzurePlatform``.
    service_principal_tenant_id: str = field(
        default="",
        metadata=field_metadata(validate=validate.Regexp(constants.GUID_REGEXP)),
    )
    service_principal_client_id: str = field(
        default="",
        metadata=field_metadata(validate=validate.Regexp(constants.GUID_REGEXP)),
    )
    service_principal_key: str = ""
    # Optional Azure ARM access token (JWT). When set, the deployer uses
    # it directly via ``StaticAccessTokenCredential`` instead of
    # ``DefaultAzureCredential``. Pipelines wire this from
    # ``S_LISA_azure_arm_access_token`` so the BMI deploy works inside
    # docker without a host ``az login`` session — same pattern as the
    # lisav3 pipeline (``lisa_connection`` service connection → token).
    azure_arm_access_token: str = ""
    # Region for the resource group and all resources. Required.
    location: str = ""
    # Resource group name. If empty, a timestamped name is generated.
    resource_group_name: str = ""
    # If True, the platform skips deployment and assumes the RG already
    # exists with a jumphost + BMIs that match the runbook. Useful for
    # iterating tests against an already-deployed environment.
    reuse_existing: bool = False
    # If True, the resource group is deleted on environment teardown.
    delete_on_cleanup: bool = True

    # ── BMI node fleet ─────────────────────────────────────────────────
    # NOTE: BMI fleet size is derived from the test environment's
    # ``nodes_requirement`` at runtime (mirrors AzurePlatform). There is no
    # static ``bmi_count`` runbook field.
    # Bare-metal VM size (e.g. ND144isr_ETH_GB200_metal_v6).
    bmi_vm_size: str = "ND144isr_ETH_GB200_metal_v6"
    # Dedicated host SKU (e.g. GPCv6GB200S186_ETH_metal-Type1).
    bmi_host_sku: str = "GPCv6GB200S186_ETH_metal-Type1"
    # Shared Image Gallery image resource ID used for BMI OS.
    # The subscription containing this SIG can differ from the
    # deployment subscription.
    bmi_image_sig: str = ""
    # Admin user baked into the BMI image. Used for SSH from LISA.
    bmi_admin_username: str = "azhpcuser"
    # Optional SSH private key file for connecting to BMI nodes.
    # When empty, LISA will fall back to password / ssh agent.
    bmi_private_key_file: str = ""
    # Optional admin password baked into the BMI specialized image.
    # Either ``bmi_password`` or ``bmi_private_key_file`` must be set.
    bmi_password: str = ""

    # ── Jumphost ───────────────────────────────────────────────────────
    # Jumphost VM size.
    jumphost_vm_size: str = "Standard_DS2_v2"
    # Jumphost image URN (Canonical Ubuntu by default).
    jumphost_image: str = "Canonical:0001-com-ubuntu-server-jammy:22_04-lts-gen2:latest"
    # Jumphost admin user.
    jumphost_username: str = "lisatest"
    # Jumphost auth (in priority order):
    #   1. ``jumphost_private_key_file`` set  -> use that key (and its .pub)
    #   2. ``jumphost_password`` set          -> password auth
    #   3. neither set                        -> deployer auto-generates a
    #      2048-bit RSA keypair next to the artifacts dir and uses it.
    # Plaintext password (when supplied) is only kept in-memory for the
    # bootstrap SSH session that installs the iptables NAT rules.
    jumphost_private_key_file: str = ""
    jumphost_password: str = ""

    # ── Networking ─────────────────────────────────────────────────────
    # VNet address prefix.
    vnet_address_prefix: str = "10.0.0.0/16"
    # External subnet (jumphost public NIC).
    external_subnet_prefix: str = "10.0.2.0/24"
    # Internal subnet (BMIs + jumphost secondary NIC).
    internal_subnet_prefix: str = "10.0.1.0/24"
    # First TCP port on the jumphost public IP that maps to BMI #1:22.
    # BMI #2 gets nat_port_start+1, etc.
    nat_port_start: int = 50001

    # ── Deployment knobs ───────────────────────────────────────────────
    # ARM template deployment timeout in seconds. BMI provisioning can
    # take well over an hour on busy capacity pools.
    deployment_timeout: int = 7200
    # Extra timeout in seconds for waiting until all NAT ports are open
    # after deployment. GB200 bare-metal nodes can take 20-30 minutes to
    # fully boot after the ARM deployment reports Succeeded, so default to
    # 60 minutes here. Override via -v ready_timeout:NNNN.
    ready_timeout: int = 3600

    def __post_init__(self) -> None:
        # Treat passwords / secrets as secrets in logs.
        if self.jumphost_password:
            add_secret(self.jumphost_password)
        if self.bmi_password:
            add_secret(self.bmi_password)
        if self.azure_arm_access_token:
            add_secret(self.azure_arm_access_token)
        if self.service_principal_key:
            add_secret(self.service_principal_key)


@dataclass_json()
@dataclass
class BmiNodeContext:
    """
    Per-node deployment state.

    Captured after ``BmiDeployer.deploy()`` so LISA can construct a
    ``schema.RemoteNode`` that reaches the BMI through the jumphost NAT.
    """

    name: str = ""
    internal_ip: str = ""
    public_address: str = ""
    public_port: int = 22
    username: str = ""
    private_key_file: Optional[str] = None
    password: str = ""


@dataclass_json()
@dataclass
class BmiDeploymentInfo:
    """Result returned by ``BmiDeployer.deploy()``."""

    resource_group: str = ""
    location: str = ""
    jumphost_public_ip: str = ""
    nodes: List[BmiNodeContext] = field(default_factory=list)


def to_remote_node_schema(node_ctx: BmiNodeContext) -> schema.RemoteNode:
    """
    Convert a BMI node context into a LISA ``RemoteNode`` runbook entry.

    The BMI is reached externally via ``public_address:public_port`` (the
    jumphost public IP plus the NAT port). The internal ``address`` is the
    BMI private IP, useful for in-VNet traffic when LISA runs on the
    jumphost itself.
    """
    return schema.RemoteNode(
        name=node_ctx.name,
        address=node_ctx.internal_ip,
        port=22,
        public_address=node_ctx.public_address,
        public_port=node_ctx.public_port,
        username=node_ctx.username,
        password=node_ctx.password,
        private_key_file=node_ctx.private_key_file or "",
        use_public_address=True,
    )
