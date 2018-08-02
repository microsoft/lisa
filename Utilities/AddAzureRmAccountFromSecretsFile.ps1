
##############################################################################################
# AddAzureRmAccountFromSecretsFile.ps1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.SYNOPSIS
    This script authenticates PS session using Azure principal account.

.PARAMETER -customSecretsFilePath
    Type: string
    Required: Optional.

.INPUTS
    AzureSecrets.xml file. If you are running this script in Jenkins, then make sure to add a secret 
    file with ID: Azure_Secrets_File
    If you are running the file locally, then pass secrets file path to -customSecretsFilePath parameter.

.NOTES
    Creation Date:  14th December 2017
    Purpose/Change: Initial script development

.EXAMPLE
    .\AddAzureRmAccountFromSecretsFile.ps1 -customSecretsFilePath .\AzureSecrets.xml
#>
###############################################################################################

param
(
    [string]$customSecretsFilePath = $null
)

#---------------------------------------------------------[Initializations]--------------------------------------------------------
Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global }

if ( $customSecretsFilePath ) {
    $secretsFile = $customSecretsFilePath
    LogMsg "Using provided secrets file: $($secretsFile | Split-Path -Leaf)"
}
if ($env:Azure_Secrets_File) {
    $secretsFile = $env:Azure_Secrets_File
    LogMsg "Using predefined secrets file: $($secretsFile | Split-Path -Leaf) in Jenkins Global Environments."
}
if ( $secretsFile -eq $null ) {
    LogMsg "ERROR: Azure Secrets file not found in Jenkins / user not provided -customSecretsFilePath" -ForegroundColor Red -BackgroundColor Black
    ThrowException ("XML Secrets file not provided")
}

#---------------------------------------------------------[Script Start]--------------------------------------------------------

if ( Test-Path $secretsFile ) {
    LogMsg "$($secretsFile | Split-Path -Leaf) found."
    LogMsg "---------------------------------"
    LogMsg "Authenticating Azure PS session.."
    $XmlSecrets = [xml](Get-Content $secretsFile)
    $ClientID = $XmlSecrets.secrets.SubscriptionServicePrincipalClientID
    $TenantID = $XmlSecrets.secrets.SubscriptionServicePrincipalTenantID
    $Key = $XmlSecrets.secrets.SubscriptionServicePrincipalKey
    $pass = ConvertTo-SecureString $key -AsPlainText -Force
    $mycred = New-Object System.Management.Automation.PSCredential ($ClientID, $pass)
    $out = Add-AzureRmAccount -ServicePrincipal -Tenant $TenantID -Credential $mycred
    $subIDSplitted = ($XmlSecrets.secrets.SubscriptionID).Split("-")
    $selectedSubscription = Select-AzureRmSubscription -SubscriptionId $XmlSecrets.secrets.SubscriptionID
    if ( $selectedSubscription.Subscription.Id -eq $XmlSecrets.secrets.SubscriptionID ) {
        LogMsg "Current Subscription : $($subIDSplitted[0])-xxxx-xxxx-xxxx-$($subIDSplitted[4])."
        LogMsg "---------------------------------"
    }
    else {
        LogMsg "There was error selecting $($subIDSplitted[0])-xxxx-xxxx-xxxx-$($subIDSplitted[4])."
        LogMsg "---------------------------------"
    }
}
else {
    LogMsg "$($secretsFile | Spilt-Path -Leaf) file is not added in Jenkins Global Environments OR it is not bound to 'Azure_Secrets_File' variable." -ForegroundColor Red -BackgroundColor Black
    LogMsg "Aborting."-ForegroundColor Red -BackgroundColor Black
    ThrowException ("XML Secrets file not provided")
}