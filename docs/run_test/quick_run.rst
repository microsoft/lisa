Getting started with Azure
==========================

In this document you will find the test procedure using a powerful cloud
computing service `Azure <https://azure.microsoft.com/>`__. Follow the
steps below to configure your local computer and run LISA test against
Linux VM on Azure.

#. Sign in to Azure

   Make sure either `Azure CLI
   <https://docs.microsoft.com/en-us/cli/azure/install-azure-cli>`__ or `Azure
   PowerShell
   <https://docs.microsoft.com/en-us/powershell/azure/install-az-ps>`__ has been
   installed on your local computer. Then log in to your Azure subscription to
   authenticate your current session. LISA also supports other Azure
   authentications, for more information, please refer to :doc: `runbook
   reference <runbook>`.

   Here, let's choose ``Azure CLI`` for the setup. You should see a page
   pop up and all your Azure subscriptions shown in console after
   running the following command.

   .. code:: bash

      az login

#. Get the subscription ID

   A subscription ID is a unique identifier for your server. LISA needs
   to know the Azure subscription ID for your testing. Run below command
   to retrieve subscription information.

   .. code:: bash

      az account show --subscription "<your subscription Name>"

   You should get something in the following format. For now you only
   need the ``<subscription id>`` for future use.

   .. code:: json

      {
          "environmentName": "AzureCloud",
          "homeTenantId": "<tenant id>",
          "id": "<subscription id>",
          "isDefault": true,
          "managedByTenants": [],
          "name": "<subscription name>",
          "state": "Enabled",
          "tenantId": "<tenant id>",
          "user": {
              "name": "<user account>",
              "type": "user"
          }
      }

   Note although the example subscription named “AzureCloud” has the
   attribute ``isDefault`` as true, it's not necessary to do so as long
   as you provide the correct ``<subscription id>``.

#. Run LISA

   Use above ``<subscription id>`` to run LISA with the default :doc:`runbook <runbook>`. It might take
   several minutes to complete.

   .. code:: bash

      lisa -r ./microsoft/runbook/azure.yml -v subscription_id:<subscription id>

   If you use the docker on Linux, use below command to run LISA.

   - ``-v ~/.azure:/root/.azure`` is to mount the azure credential file to the docker container.
   - ``-v ./runtime/log:/app/lisa/runtime`` is to mount the log folder to the docker container. You can get the test result from the log folder ``./runtime/log``.

   .. code:: bash

      docker run --rm -v ~/.azure:/root/.azure -v ./runtime/log:/app/lisa/runtime -i mcr.microsoft.com/lisa/runtime:latest lisa -r microsoft/runbook/azure.yml -v subscription_id:<subscription id>

   If you use Windows Docker Desktop. It needs to generate tokens to authenticate with Azure.
   First, generate the token using the below command on Linux.

   .. code:: bash

      LISA_azure_arm_access_token=$(az account get-access-token --query accessToken -o tsv)

   Or generate the token using the below command on Windows.

   .. code:: bash

      $LISA_azure_arm_access_token=$(az account get-access-token --query accessToken -o tsv)

   Then, specify the auth type as token and pass the token to the Docker container.

   - ``-e LISA_auth_type=token`` is to specify the auth type as token.
   - ``-e S_LISA_azure_arm_access_token=$LISA_azure_arm_access_token`` is to pass the token to the Docker container.

   This is for the Linux docker image on Windows. The container log path is ``/app/lisa/runtime``.

   .. code:: bash

      docker run -it --rm -e LISA_auth_type=token -e S_LISA_azure_arm_access_token=$LISA_azure_arm_access_token -v ./runtime/log:/app/lisa/runtime -i mcr.microsoft.com/lisa/runtime:latest lisa -r microsoft/runbook/azure.yml -v subscription_id:<subscription id>

   This is for the Windows docker image on Windows. The container log path is ``C:/app/lisa/runtime``.

   .. code:: bash

      docker run -it --rm -e LISA_auth_type=token -e S_LISA_azure_arm_access_token=$LISA_azure_arm_access_token -v ./runtime/log:C:/app/lisa/runtime -i mcr.microsoft.com/lisa/runtime:latest lisa -r microsoft/runbook/azure.yml -v subscription_id:<subscription id>

#. Verify test result

   After the test is completed, you can check the LISA console log, or the html
   report file for the test results. Refer to :doc:`Understand test results
   <understand_results>` for more detailed explanation of the logs and report.
   See an example html report as below:

   .. figure:: ../img/smoke_test_result.png
      :alt: image

#. Test specific cases with debug runbook

   LISA provides a debug runbook to run specific test cases by name. This is useful for debugging and testing individual cases.

   Simple example with case and origin:

   .. code:: bash

      lisa -r microsoft/runbook/debug.yml \
        -v "case:hello" \
        -v "origin:azure.yml" \
        -v subscription_id:<subscription id>

.. note::
   See :doc:`Run LISA <run>` for more advanced usages.
