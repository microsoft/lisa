Use Different Authentication Methods on Azure
=============================================

-  `Overview <#overview>`__
-  `Run on Azure <#run-on-azure>`__
-  `Available Authentication Methods <#available-authentication-methods>`__
-  `Schema Description <#schema-description>`__

Overview
--------
This document describes how to configure and use different authentication methods for running LISA tests on Azure. The available authentication methods include default credentials, certificates, client assertions, client secrets, workload identity, and tokens.
You can configure the `platform` section of your YAML file to choose the desired authentication method for connecting to Azure.

Run on Azure
-------------
To run LISA tests on Azure with different authentication methods, configure the `platform` section in your YAML file as shown below.

Available Authentication Methods
-------------------------------
1. `Default Credentials <#default-credentials>`__
2. `Certificate Authentication <#certificate-authentication>`__
3. `Assertion Authentication <#assertion-authentication>`__
4. `Workload Identity Authentication <#workload-identity-authentication>`__
5. `Token Authentication <#token-authentication>`__
6. `Client Secret Authentication <#client-secret-authentication>`__
7. `Azure CLI Authentication <#azure-cli-authentication>`__

Default Credentials
-------------------
Default authentication uses credentials from environment variables, Azure CLI, or managed identities. This method is useful when your environment is already authenticated through Azure CLI, Azure PowerShell, or managed identities.

Example:

.. code:: yaml

   platform:
     - type: azure
       azure:
         credential:
           type: default
           client_id: <client id>  # Optional
           tenant_id: <tenant id>  # Optional
           allow_all_tenants: false | true  # Optional. Default is `false`.

* **type**: `default` indicates default credential authentication.
* **client_id**: (Optional) Needed when there are multiple managed identities associated with the running machine.
* **tenant_id**: (Optional) Needed when you have multiple tenants.
* **allow_all_tenants**: (Optional) Specifies whether to allow cross-tenant authorization. Default is `false`.

Certificate Authentication
---------------------------
Authenticates as a service principal using a certificate. You will need to provide the certificate file path and optionally specify whether to send the certificate chain.

Example:

.. code:: yaml

   platform:
     - type: azure
       azure:
         credential:
           type: certificate
           tenant_id: <tenant id> # Required
           client_id: <client id> # Required
           cert_path: <path to certificate file> # Required
           client_send_cert_chain: false | true # Optional. Default is `false`.

* **type**: `certificate` indicates certificate-based authentication.
* **tenant_id**: ID of the principal's tenant. Also called its "directory" ID.
* **client_id**: The principal's client ID.
* **cert_path**: Path to a certificate file in PEM or PKCS12 format, including the private key.
* **client_send_cert_chain**: (Optional) If True, the credential will send the public certificate chain in the x5c header of each token request's JWT. This is required for Subject Name/Issuer (SNI) authentication. Defaults to `false`.

Assertion Authentication
------------------------
ClientAssertionCredential allows authentication using a pre-obtained JWT (Json Web Token) assertion instead of a client secret or certificate. It is primarily used for Service Principal authentication but can also work with other identities if a valid JWT is provided.

Example:

.. code:: yaml

   platform:
     - type: azure
       azure:
         credential:
           type: assertion
           tenant_id: <tenant id> # Required
           msi_client_id: <msi client id> # Required
           enterprise_app_client_id: <enterprise app client id> # Required

* **type**: `assertion` indicates assertion authentication.
* **tenant_id**: ID of the principal's tenant. Also called its "directory" ID.
* **enterprise_app_client_id**: The principal's client ID
* **msi_client_id**: Get a token from the managed identity endpoint for the specified client ID.

Workload Identity Authentication
--------------------------------
Azure Workload Identity authentication allows applications on VMs or Azure Kubernetes to access resources without service principals or managed identities. It uses Service Account Credentials (SACs), which are automatically created and managed by Azure, eliminating the need for credential storage and rotation.

Example:

.. code:: yaml

   platform:
     - type: azure
       azure:
         credential:
           type: workloadidentity
           client_id: <client id> # Required
           tenant_id: <tenant id> # Required
           allow_all_tenants: false | true  # Optional. Default is `false`.

* **type**: `workloadidentity` indicates workload identity authentication.
* **client_id**: The principal's client ID.
* **tenant_id**: ID of the principal's tenant. Also called its "directory" ID.
* **allow_all_tenants**: (Optional) Specifies whether to allow cross-tenant authorization. Default is `false`.

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
           token: <token> # Required

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
           client_id: <client id> # Required
           tenant_id: <tenant id> # Required
           client_secret: <client secret> # Required

Azure CLI Authentication
-----------------------
This authentication uses the Azure CLI for authentication, which requires previously logging in to Azure via "az login". It will use the CLI's currently logged in identity.

Example:

.. code:: yaml

   platform:
     - type: azure
       azure:
         credential:
           type: azcli
           tenant_id: <tenant id> # Optional
           allow_all_tenants: false | true  # Optional. Default is `false`.

* **type**: `azcli` indicates Azure CLI authentication.
* **tenant_id**: (Optional) Needed to specify a specific tenant for authentication.
* **allow_all_tenants**: (Optional) Specifies whether to allow cross-tenant authorization. Default is `false`.

Schema Description
--------------------

The configuration follows this schema:

-  **azure.credential.type**: Specifies the authentication method to use. Possible values:
  -  **default**: Uses default credentials (e.g., environment variables, Azure CLI, or managed identities).
  -  **certificate**: Uses certificate-based authentication. Requires `cert_path` and optionally `client_send_cert_chain`.
  -  **assertion**: Uses client assertion authentication. Requires `msi_client_id` and `enterprise_app_client_id`.
  -  **secret**: Uses client secret authentication. Requires `client_secret`.
  -  **workloadidentity**: Uses workload identity authentication.
  -  **token**: Uses token-based authentication. Requires a valid `token`.
  -  **azcli**: Uses Azure CLI authentication. Requires previously logging in via "az login" and uses the CLI's currently logged in identity.

**Schema Inheritance:** The `default` authentication method defines a base schema that all other authentication types inherit from. Fields such as `allow_all_tenants` are applicable to all authentication methods.
