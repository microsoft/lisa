<#
.SYNOPSIS
    This script authenticates PS sessing using Azure principal account.

.DESCRIPTION
    This script authenticates PS sessing using Azure principal account.

.PARAMETER -customSecretsFilePath
    Type: string
    Required: Optinal.

.INPUTS
    AzureSecrets.xml file. If you are running this script in Jenkins, then make sure to add a secret file with ID: Azure_Secrets_File
    If you are running the file locally, then pass secrets file path to -customSecretsFilePath parameter.

.NOTES
    Version:        1.0
    Author:         Shital Savekar <v-shisav@microsoft.com>
    Creation Date:  14th December 2017
    Purpose/Change: Initial script development

.EXAMPLE
    .\AddAzureRmAccountFromSecretsFile.ps1 -customSecretsFilePath .\AzureSecrets.xml
#>

param
(
    [string]$customSecretsFilePath = $null
)

#---------------------------------------------------------[Initializations]--------------------------------------------------------

if ( $customSecretsFilePath ) {
    $secretsFile = $customSecretsFilePath
    Write-Host "Using provided secrets file: $($secretsFile | Split-Path -Leaf)"
}
if ($env:Azure_Secrets_File) {
    $secretsFile = $env:Azure_Secrets_File
    Write-Host "Using predefined secrets file: $($secretsFile | Split-Path -Leaf) in Jenkins Global Environments."
}
if ( $secretsFile -eq $null ) {
    Write-Host "ERROR: Azure Secrets file not found in Jenkins / user not provided -customSecretsFilePath" -ForegroundColor Red -BackgroundColor Black
    exit 1
}

#---------------------------------------------------------[Script Start]--------------------------------------------------------

if ( Test-Path $secretsFile ) {
    Write-Host "$($secretsFile | Split-Path -Leaf) found."
    Write-Host "---------------------------------"
    Write-Host "Authenticating Azure PS session.."
    $xmlSecrets = [xml](Get-Content $secretsFile)
    $ClientID = $xmlSecrets.secrets.SubscriptionServicePrincipalClientID
    $TenantID = $xmlSecrets.secrets.SubscriptionServicePrincipalTenantID
    $Key = $xmlSecrets.secrets.SubscriptionServicePrincipalKey
    $pass = ConvertTo-SecureString $key -AsPlainText -Force
    $mycred = New-Object System.Management.Automation.PSCredential ($ClientID, $pass)
    $out = Add-AzureRmAccount -ServicePrincipal -Tenant $TenantID -Credential $mycred
    $subIDSplitted = ($xmlSecrets.secrets.SubscriptionID).Split("-")
    $selectedSubscription = Select-AzureRmSubscription -SubscriptionId $xmlSecrets.secrets.SubscriptionID
    if ( $selectedSubscription.Subscription.Id -eq $xmlSecrets.secrets.SubscriptionID ) {
        Write-Host "Current Subscription : $($subIDSplitted[0])-xxxx-xxxx-xxxx-$($subIDSplitted[4])."
        Write-Host "---------------------------------"
    }
    else {
        Write-Host "There was error selecting $($subIDSplitted[0])-xxxx-xxxx-xxxx-$($subIDSplitted[4])."
        Write-Host "---------------------------------"
    }
}
else {
    Write-Host "$($secretsFile | Spilt-Path -Leaf) file is not added in Jenkins Global Environments OR it is not bound to 'Azure_Secrets_File' variable." -ForegroundColor Red -BackgroundColor Black
    Write-Host "Aborting."-ForegroundColor Red -BackgroundColor Black
    exit 1
}