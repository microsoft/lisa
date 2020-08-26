import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

from azure.identity import DefaultAzureCredential  # type: ignore
from azure.mgmt.resource import (  # type: ignore
    ResourceManagementClient,
    SubscriptionClient,
)
from dataclasses_json import LetterCase, dataclass_json  # type:ignore
from marshmallow import validate

from lisa import schema
from lisa.environment import Environment
from lisa.platform_ import Platform
from lisa.util import constants
from lisa.util.exceptions import LisaException

AZURE = "azure"


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class AzurePlatformSchema:
    service_principal_tenant_id: str = field(
        default="",
        metadata=schema.metadata(
            data_key="servicePrincipalTenantId",
            validate=validate.Regexp(constants.GUID_REGEXP),
        ),
    )
    service_principal_client_id: str = field(
        default="",
        metadata=schema.metadata(
            data_key="servicePrincipalClientId",
            validate=validate.Regexp(constants.GUID_REGEXP),
        ),
    )
    service_principal_key: str = field(default="")
    subscription_id: str = field(
        default="",
        metadata=schema.metadata(
            data_key="subscriptionId", validate=validate.Regexp(constants.GUID_REGEXP),
        ),
    )

    resource_group_name: str = field(default="")
    location: str = field(default="westus2")

    log_level: str = field(
        default=logging.getLevelName(logging.WARN),
        metadata=schema.metadata(
            data_key="logLevel",
            validate=validate.OneOf(
                [
                    logging.getLevelName(logging.ERROR),
                    logging.getLevelName(logging.WARN),
                    logging.getLevelName(logging.INFO),
                    logging.getLevelName(logging.DEBUG),
                ]
            ),
        ),
    )

    dry_run: bool = False


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class AzureNodeSchema:
    vm_size: str = field(default="")


class AzurePlatform(Platform):
    def __init__(self) -> None:
        super().__init__()
        self._credential: DefaultAzureCredential = None
        self._enviornment_counter = 0

    @classmethod
    def platform_type(cls) -> str:
        return AZURE

    @property
    def platform_schema(self) -> Optional[Type[Any]]:
        return AzurePlatformSchema

    @property
    def node_schema(self) -> Optional[Type[Any]]:
        return AzureNodeSchema

    def _request_environment(self, environment: Environment) -> Environment:
        assert self._rm_client

        assert environment.runbook, "env data cannot be None"
        env_runbook: schema.Environment = environment.runbook

        if self._azure_runbook.resource_group_name:
            resource_group_name = self._azure_runbook.resource_group_name
            self._log.info(f"reusing resource group: {resource_group_name}")
        else:
            normalized_run_name = constants.NORMALIZE_PATTERN.sub(
                "_", constants.RUN_NAME
            )
            resource_group_name = f"{normalized_run_name}_e{self._enviornment_counter}"
            self._enviornment_counter += 1
            self._log.info(f"creating resource group: {resource_group_name}")

        if self._azure_runbook.dry_run:
            self._log.info(f"dry_run: {self._azure_runbook.dry_run}")
        else:
            resource_group = self._rm_client.resource_groups.create_or_update(
                resource_group_name, {"location": self._azure_runbook.location}
            )
            self._log.info(f"created resource group is {resource_group}")
            nodes_parameters: List[Dict[str, Any]] = []
            for node_runbook in env_runbook.nodes:
                assert isinstance(node_runbook, schema.NodeSpec)
                node_parameter: Dict[str, Any] = dict()
                node_parameter["vcpu"] = node_runbook.cpu_count
                nodes_parameters.append(node_parameter)
            self._rm_client.deployments.validate(nodes_parameters)

        return environment

    def _delete_environment(self, environment: Environment) -> None:
        pass

    def _initialize(self) -> None:
        # set needed environment variables for authentication
        self._azure_runbook = self._runbook.get_extended_runbook(AzurePlatformSchema)
        assert self._azure_runbook, "platform runbook cannot be empty"

        # set azure log to warn level only
        logging.getLogger("azure").setLevel(self._azure_runbook.log_level)

        os.environ["AZURE_TENANT_ID"] = self._azure_runbook.service_principal_tenant_id
        os.environ["AZURE_CLIENT_ID"] = self._azure_runbook.service_principal_client_id
        os.environ["AZURE_CLIENT_SECRET"] = self._azure_runbook.service_principal_key

        self._credential = DefaultAzureCredential()

        self._sub_client = SubscriptionClient(self._credential)

        self._subscription_id = self._azure_runbook.subscription_id
        subscription = self._sub_client.subscriptions.get(self._subscription_id)
        if not subscription:
            raise LisaException(
                f"cannot find subscription id: '{self._subscription_id}'"
            )
        self._log.info(f"connected to subscription: '{subscription.display_name}'")

        self._rm_client = ResourceManagementClient(
            credential=self._credential, subscription_id=self._subscription_id
        )
