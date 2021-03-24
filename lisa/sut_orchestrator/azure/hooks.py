import re
from typing import List, Pattern, Tuple, Type

from lisa.util import SkippedException, hookimpl, hookspec, plugin_manager


class AzureHookSpec:
    @hookspec  # type: ignore
    def azure_deploy_failed(self, error_message: str) -> None:
        """
        It can be used to skipped some by design failed deployment, such as deploy gen1
        image on gen2 vm_size.
        """
        ...


class AzureHookSpecDefaultImpl:
    __error_maps: List[Tuple[str, Pattern[str], Type[Exception]]] = [
        (
            "gen1 image shouldn't run on gen2 vm size",
            re.compile(
                "^BadRequest: The selected VM size '.+?' "
                "cannot boot Hypervisor Generation '1'\\."
            ),
            SkippedException,
        )
    ]

    @hookimpl  # type: ignore
    def azure_deploy_failed(self, error_message: str) -> None:
        for message, pattern, exception_type in self.__error_maps:
            if pattern.findall(error_message):
                raise exception_type(f"{message}. {error_message}")


plugin_manager.add_hookspecs(AzureHookSpec)
plugin_manager.register(AzureHookSpecDefaultImpl())
