# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
"""
Pluggy hookspecs for the BMI platform.

Mirrors ``lisa.sut_orchestrator.azure.hooks`` so out-of-tree extensions can
mutate the loaded BMI ARM template (e.g. inject NSG rules) before deployment.
"""

from typing import Any, Dict, Optional

from lisa.environment import Environment
from lisa.util import hookspec, plugin_manager


class BmiHookSpec:
    @hookspec
    def bmi_update_arm_template(
        self,
        template: Dict[str, Any],
        parameters: Dict[str, Any],
        environment: Optional[Environment],
    ) -> None:
        """Mutate the BMI ARM template in-place before deployment.

        Args:
            template: dict loaded from ``autogen_bmi_template.json``.
            parameters: ARM deployment parameters
                ({paramName: {"value": ...}} pairs), readable by the hook
                to compute things like the NAT destination port range.
            environment: deploying LISA environment, or ``None`` when the
                deployer is invoked outside of an environment context.
        """
        ...

    @hookspec
    def bmi_refresh_nsg_for_agent_ip(
        self,
        net_client: Any,
        rg_name: str,
        nsg_name: str,
        dest_ports: Any,
    ) -> None:
        """Refresh agent-IP-based NSG rule with the current external IP.

        Called when LISA detects the active connection back to the BMI
        environment has been silently dropped (NSG fingerprint), typically
        because the pipeline agent's SNAT egress IP has rotated since the
        deploy-time snapshot.
        """
        ...


plugin_manager.add_hookspecs(BmiHookSpec)
