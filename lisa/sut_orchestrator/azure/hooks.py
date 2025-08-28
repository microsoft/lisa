import re
from functools import partial
from typing import Any, Dict, List, Pattern, Tuple

from lisa.environment import Environment
from lisa.sut_orchestrator.azure.common import AzureCapability
from lisa.util import (
    ResourceAwaitableException,
    SkippedException,
    hookimpl,
    hookspec,
    plugin_manager,
)


class AzureHookSpec:
    @hookspec
    def azure_deploy_failed(self, error_message: str) -> None:
        """
        It can be used to skipped some by design failed deployment, such as deploy gen1
        image on gen2 vm_size.
        """
        ...

    @hookspec
    def azure_update_arm_template(
        self, template: Any, environment: Environment
    ) -> None:
        """
        Implement it to update loaded arm_template.

        Args:
            template: the dict object, which is loaded from the arm_template.json.
            environment: the deploying environment.
        """
        ...

    @hookspec
    def azure_update_vm_capabilities(
        self, location: str, capabilities: Dict[str, AzureCapability]
    ) -> None:
        """
        Implement it to update the vm capabilities.

        Args:
            capabilities: the dict object mapping VM SKU name to Azure capability,
                which is compiled from the output of _resource_sku_to_capability()
        """
        ...


class AzureHookSpecDefaultImpl:
    __error_maps: List[Tuple[str, Pattern[str], Any]] = [
        (
            "gen1 image shouldn't run on gen2 vm size",
            re.compile(
                "^BadRequest: The selected VM size '.+?' "
                "cannot boot Hypervisor Generation '1'\\."
            ),
            SkippedException,
        ),
        (
            # QuotaExceeded: Operation could not be completed as it results in
            # exceeding approved standardMSFamily Cores quota. Additional
            # details - Deployment Model: Resource Manager, Location: westus2,
            # Current Limit: 1000, Current Usage: 896, Additional Required: 128,
            # (Minimum) New Limit Required: 1024. Submit a request for Quota
            # increase at
            # https://aka.ms/ProdportalCRP/#blade/Microsoft_Azure_Capacity/
            # by specifying parameters listed in the ‘Details’ section for
            # deployment to succeed. Please read more about quota limits at
            # https://docs.microsoft.com/en-us/azure/azure-supportability/per-vm-quota-requests
            "",
            # If current usage is 0, it means current limit cannot fit the
            # deployment. So, the deployment won't pass without larger limit.
            # For example, limit is 100, but the environment needs 128. It's
            # impossible to wait for enough.
            re.compile(
                r"Additional details - Deployment Model: .* Current Usage: (?!0).+, "
                r"Additional Required: \d+,"
            ),
            ResourceAwaitableException,
        ),
        (
            # AllocationFailed: Allocation failed. We do not have sufficient
            # capacity for the requested VM size in this region. Read more about
            # improving likelihood of allocation success at
            # http://aka.ms/allocation-guidance
            "",
            re.compile(r"^AllocationFailed: Allocation failed."),
            partial(ResourceAwaitableException, "vm size"),
        ),
        (
            "Your subscription is not registered for Virtual Machine Hibernation "
            "feature. Please register and try again. More details please refer "
            "https://learn.microsoft.com/en-us/azure/virtual-machines/hibernate-resume-troubleshooting?tabs=troubleshootLinuxCantHiber%2CtroubleshootWindowsGuestCantHiber",  # noqa: E501
            re.compile(
                r"The subscription is not registered for the private preview of"
                " VirtualMachine Hibernation feature"
            ),
            SkippedException,
        ),
        (
            # ResourceCollectionRequestsThrottled - Too many requests to Azure API
            "Azure API throttling detected. The deployment was throttled "
            "due to too many requests",
            re.compile(
                r"ResourceCollectionRequestsThrottled.*Operation '.*' failed as server "
                r"encountered too many requests.*Please try after '\d+' seconds"
            ),
            ResourceAwaitableException,
        ),
        (
            # ResourceGroupQuotaExceeded - Resource group limit reached
            "Resource group quota exceeded. Please delete some "
            "resource groups before retrying",
            re.compile(
                r"ResourceGroupQuotaExceeded.*Creating the resource group.*would "
                r"exceed the quota of '\d+'.*current resource group count is '\d+'"
            ),
            ResourceAwaitableException,
        ),
    ]

    @hookimpl
    def azure_deploy_failed(self, error_message: str) -> None:
        for message, pattern, exception_type in self.__error_maps:
            if pattern.findall(error_message):
                raise exception_type(f"{message}. {error_message}")


plugin_manager.add_hookspecs(AzureHookSpec)
plugin_manager.register(AzureHookSpecDefaultImpl())
