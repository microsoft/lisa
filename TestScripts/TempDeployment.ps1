Import-Module .\tools\AzureSDK\Azure.psd1 -Force
Import-Module .\TestLibs\RDFELibstemp.psm1 -Force
$xmlConfig3 = [xml](Get-Content .\XML\Azure_ICA_backup.xml)
DeployVMs -xmlConfig $xmlConfig3 -setupType E2ESingleVM -Distro Ubuntu1204pre

#ICA-IEndpointSingleHS-UBUNTULTS-2-4-2013