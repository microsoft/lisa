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

#. Prepare SSH key pair

   LISA connects to the Azure test VM by SSH with key authentication;
   please have your key pair (public key and private key) ready before
   running the test.

   You can skip this step if you already have a key pair. However, if
   you don't have a key pair, run below command to create a new one.

   .. code:: bash

      ssh-keygen

.. warning::

   Don't use passphrase to protect your key. LISA doesn't
   support that.

#. Run LISA

   Use above ``<subscription id>`` and ``<private key file>`` to run
   LISA with the default :doc:`runbook <runbook>`. It might take
   several minutes to complete.

   .. code:: bash

      lisa -r ./microsoft/runbook/azure.yml -v subscription_id:<subscription id> -v "admin_private_key_file:<private key file>"

#. Verify test result

   After the test is completed, you can check the LISA console log, or the html
   report file for the test results. Refer to :doc:`Understand test results
   <understand_results>` for more detailed explanation of the logs and report.
   See an example html report as below:

   .. figure:: ../img/smoke_test_result.png
      :alt: image

.. note::
   See :doc:`Run LISA <run>` for more advanced usages.
