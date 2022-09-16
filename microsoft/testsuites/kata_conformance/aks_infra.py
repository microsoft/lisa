# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from threading import Lock
import datetime
import os
from azure.identity import DefaultAzureCredential
from azure.mgmt.containerservice import ContainerServiceClient
from azure.mgmt.resource import ResourceManagementClient, SubscriptionClient
from lisa.util import LisaException
from lisa.util.logger import Logger

global_credential_access_lock = Lock()


class AKSInfra:
    def __init__(
        self,
        log: Logger,
        subscription_id: str,
        tenant_id: str,
        client_id: str,
        client_secret: str
    ):
        self.log = log
        self._credential_setup(subscription_id, tenant_id, client_id, client_secret)
        self.kube_path = ""

    def _credential_setup(self, subscription_id, tenant_id, client_id, client_secret):
        if tenant_id:
            os.environ["AZURE_TENANT_ID"] = tenant_id
        if client_id:
            os.environ["AZURE_CLIENT_ID"] = client_id
        if client_secret:
            os.environ["AZURE_CLIENT_SECRET"] = client_secret
        if subscription_id:
            os.environ["AZURE_SUBSCRIPTION_ID"] = subscription_id

        self._subscription_id = subscription_id
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self.credential = DefaultAzureCredential()
        subscription = None

        with SubscriptionClient(self.credential) as self._sub_client:
            # suppress warning message by search for different credential types
            with global_credential_access_lock:
                subscription = self._sub_client.subscriptions.get(
                    self._subscription_id
                )
                self.log.info(
                    f"connected to subscription: "
                    f"{subscription.id}, '{subscription.display_name}'"
                )

        if not subscription:
            raise LisaException(
                f"Cannot find subscription id: '{self._subscription_id}'. "
                f"Make sure it exists and current account can access it."
            )

        self.rsc_mgmt_client = ResourceManagementClient(
            credential=self.credential,
            subscription_id=self._subscription_id
        )
        self.cntsrv_client = ContainerServiceClient(
            credential=self.credential,
            subscription_id=self._subscription_id
        )

    def create_aks_infra(
        self,
        kubernetes_version,
        worker_vm_size,
        node_count,
        azure_region,
        headers
    ) -> None:

        ts = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        aks_cluster_name = f"LISA_AKS_Conf_{ts}"
        self.resource_group_name = f"LISA_RG_Conf_{ts}"
        self.log.info("Creating Resource Group : " + self.resource_group_name)

        rg = self.rsc_mgmt_client.resource_groups.create_or_update(
            self.resource_group_name,
            {
                "location": azure_region
            }
        )
        self.log.info("Resource Group Created : " + self.resource_group_name)
        self.log.debug("Resource Group Details are as below : ")
        self.log.debug(rg)

        self.log.info("Creating AKS Cluster : " + aks_cluster_name)

        aks_cluster = self.cntsrv_client.managed_clusters.begin_create_or_update(
            self.resource_group_name,
            aks_cluster_name,
            {
                "dns_prefix": f"LISA-Kata-Conf-Test-DNS-{ts}",
                "kubernetes_version": kubernetes_version,
                "agent_pool_profiles": [
                    {
                        "name": "nodepool1",
                        "count": node_count,
                        "vm_size": worker_vm_size,
                        "max_pods": 110,
                        "min_count": 1,
                        "max_count": 100,
                        "os_type": "Linux",
                        "type": "VirtualMachineScaleSets",
                        "enable_auto_scaling": True,
                        "mode": "System"
                    }
                ],
                "servicePrincipalProfile": {},
                "identity": {
                    "type": "SystemAssigned"
                },
                "location": azure_region
            },
            headers=headers
        ).result()
        self.log.info("AKS Cluster Created : " + aks_cluster_name)
        self.log.debug("AKS Cluster Detail are as below : ")
        self.log.debug(aks_cluster)

        self.log.info("Setting AKS Cluster Credentials with kubeconfig file")
        kubeconfig = self.cntsrv_client.managed_clusters.list_cluster_user_credentials(
            self.resource_group_name, aks_cluster_name).kubeconfigs[0]
        home_directory = os.path.expanduser('~')
        self.kube_path = os.path.join(home_directory, ".kube", "config")
        if not os.path.exists(os.path.join(home_directory, ".kube")):
            os.mkdir(os.path.join(home_directory, ".kube"))
        with open(self.kube_path, "w") as f:
            f.write(kubeconfig.value.decode())
        os.environ["KUBECONFIG"] = self.kube_path
        self.log.debug("KUBECONFIG file is at : " + self.kube_path)
        self.log.info("AKS Cluster Credentials are configured")

    def delete_aks_infra(self):
        self.log.info("Deleting Resource Group : " + self.resource_group_name)
        self.rsc_mgmt_client.resources.delete(self.resource_group_name)
        self.log.info("Deleted Resource Group : " + self.resource_group_name)
