Azure Deployment Template
==========================

`Bicep <https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/>`__ provides a more concise and readable way to define Azure infrastructure compared to ARM templates. However, as of now, the Azure Python SDK doesn't support direct deployment of Bicep templates. Therefore, we need to generate an ARM template from the Bicep template and deploy it using the Azure SDK.

To achieve this, follow these steps:

1. **Update Bicep Template**: Update the `arm_template.bicep` file with your desired infrastructure configuration.

2. **Generate ARM Template**: Run the following command to compile the Bicep template into an ARM template:

   .. code-block:: bash

      az bicep build -f .\arm_template.bicep --outfile .\autogen_arm_template.json

   Make sure you have the Bicep CLI installed. You can install it `here <https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/bicep-cli>`__. Put bicepconfig.json in the same directory as the Bicep template.

These steps allow you to leverage the benefits of Bicep for defining Azure infrastructure while still utilizing the Azure Python SDK for deployment.
