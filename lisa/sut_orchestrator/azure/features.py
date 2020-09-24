from typing import Any

from lisa.features import StartStop as BaseStartStop

from .common import get_compute_client, get_node_context, wait_operation


class StartStop(BaseStartStop):
    def _stop(self, wait: bool = True) -> Any:
        return self._execute(wait, "begin_stop")

    def _start(self, wait: bool = True) -> Any:
        return self._execute(wait, "begin_start")

    def _restart(self, wait: bool = True) -> Any:
        return self._execute(wait, "begin_restart")

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        node_context = get_node_context(self._node)
        self._vm_name = node_context.vm_name
        self._resource_group_name = node_context.resource_group_name

    def _execute(self, wait: bool, operator: str) -> Any:
        compute_client = get_compute_client(self._platform)
        operator_method = getattr(compute_client.virtual_machines, operator)
        result = operator_method(
            vm_name=self._vm_name, resource_group_name=self._resource_group_name
        )
        if wait:
            result = wait_operation(result)
        return result
