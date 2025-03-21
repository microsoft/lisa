Use Different Authentication Methods on Azure
=============================================

-  `Overview <#overview>`__
-  `Run on Azure <#run-on-azure>`__
-  `Available Authentication Methods <#available-authentication-methods>`__

Overview
--------
This document describes how to configure and use different authentication methods for running LISA tests on Azure. The available authentication methods include default credentials, certificates, client assertions, client secrets, workload identity, and tokens.

You can configure the `platform` section of your YAML file to choose the desired authentication method for connecting to Azure.

Run on Azure
-------------
To run LISA tests on Azure with different authentication methods, configure the `platform` section in your YAML file as shown below.

Available Authentication Methods
-------------------------------
1. `Default Credentials <#default-credentials>`
2. `Certificate Authentication <#certificate-authentication>`
3. `Assertion Authentication <#assertion-authentication>`
4. `Client Secret Authentication <#client-secret-authentication>`
5. `Workload Identity Authentication <#workload-identity-authentication>`
6. `Token Authentication <#token-authentication>`

Default Credentials
-------------------
Default authentication uses credentials from environment variables, Azure CLI, or managed identities. This method is useful when your environment is already authenticated through Azure CLI or managed identities.

Example:
.. code:: yaml

   platform:
     - type: azure
       azure:
         credential:
           type: default

Certificate Authentication
---------------------------
This method requires a certificate for authentication. You will need to provide the certificate file path and optionally specify whether to send the certificate chain.

Example:
.. code:: yaml

   platform:
     - type: azure
       azure:
         credential:
           type: certificate
           certificate_file: <certificate file>
           client_send_cert_chain: false  # Set to true to send certificate chain

Assertion Authentication
------------------------
Client assertion is used when you need to authenticate via a client assertion, such as for managed identity or enterprise applications. You need to provide the MSI client ID and the enterprise application client ID.

Example:
.. code:: yaml

   platform:
     - type: azure
       azure:
         credential:
           type: assertion
           msi_client_id: <msi client id>
           enterprise_app_client_id: <enterprise app client id>

Client Secret Authentication
----------------------------
Client secret authentication requires the use of a client secret for authentication. You need to provide the client secret in your configuration.

Example:
.. code:: yaml

   platform:
     - type: azure
       azure:
         credential:
           type: secret
           client_secret: <client secret>

Workload Identity Authentication
--------------------------------
This method uses Azure workload identity for authentication. It is typically used in scenarios where the workload itself needs to authenticate to Azure resources using an identity.

Example:
.. code:: yaml

   platform:
     - type: azure
       azure:
         credential:
           type: workloadidentity

Token Authentication
--------------------
Token authentication requires an Azure token for authentication. You need to provide a valid Azure token in your configuration.

Example:
.. code:: yaml

   platform:
     - type: azure
       azure:
         credential:
           type: token
           token: <token>

Schema Description
------------------

The configuration follows this schema:

- `platform`: Defines the platform type. In this case, it is `azure`.
- `type`: Specifies the type of the platform. Here it should be set to `azure`.
- `azure.credential.type`: Specifies the authentication method to use. Possible values:
  - `default`: Uses default credentials (e.g., environment variables, Azure CLI, or managed identities).
  - `certificate`: Uses certificate-based authentication. You need to provide the `certificate_file` and optionally specify `client_send_cert_chain`.
  - `assertion`: Uses client assertion authentication. You need to provide `msi_client_id` and `enterprise_app_client_id`.
  - `secret`: Uses client secret authentication. You need to provide `client_secret`.
  - `workloadidentity`: Uses workload identity authentication.
  - `token`: Uses token-based authentication. You need to provide a valid `token`.

This schema allows you to select the most appropriate authentication method based on your environment and security requirements.

For more detailed guidance on configuring these authentication methods, refer to the Azure documentation for each authentication type.
