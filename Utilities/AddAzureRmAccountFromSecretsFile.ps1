
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
    The Secrets.xml file.
    If running in Jenkins, then please add a env variable for secret file with ID: Azure_Secrets_File;
    If running locally, then pass the secrets file path to -customSecretsFilePath parameter.

.NOTES

.EXAMPLE
    .\AddAzureRmAccountFromSecretsFile.ps1 -customSecretsFilePath .\AzureSecrets.xml
#>
###############################################################################################

param
(
    [string]$customSecretsFilePath
)

$ErrorActionPreference = "Stop"
#---------------------------------------------------------[Initializations]--------------------------------------------------------
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Definition
$rootPath = Split-Path -Parent $scriptPath
Get-ChildItem (Join-Path $rootPath "Libraries") -Recurse | `
    Where-Object { $_.FullName.EndsWith(".psm1") } | `
    ForEach-Object { Import-Module $_.FullName -Force -Global -DisableNameChecking }

if ( $customSecretsFilePath ) {
    $secretsFile = $customSecretsFilePath
    LogMsg "Using provided secrets file: $secretsFile"
}
if ($env:Azure_Secrets_File) {
    $secretsFile = $env:Azure_Secrets_File
    LogMsg "Using secrets file: $secretsFile, defined in environments."
}
if ( ($null -eq $secretsFile) -or ($secretsFile -eq [string]::Empty)) {
    LogErr "ERROR: The Secrets file is not being set."
    ThrowException ("XML Secrets file not provided")
}

#---------------------------------------------------------[Script Start]--------------------------------------------------------

if ( Test-Path $secretsFile ) {
    LogMsg "$secretsFile found."
    LogMsg "---------------------------------"
    LogMsg "Authenticating Azure PS session.."
    $XmlSecrets = [xml](Get-Content $secretsFile)
    $ClientID = $XmlSecrets.secrets.SubscriptionServicePrincipalClientID
    $TenantID = $XmlSecrets.secrets.SubscriptionServicePrincipalTenantID
    $Key = $XmlSecrets.secrets.SubscriptionServicePrincipalKey
    $pass = ConvertTo-SecureString $key -AsPlainText -Force
    $mycred = New-Object System.Management.Automation.PSCredential ($ClientID, $pass)
    $subIDSplitted = ($XmlSecrets.secrets.SubscriptionID).Split("-")
    $subIDMasked = "$($subIDSplitted[0])-xxxx-xxxx-xxxx-$($subIDSplitted[4])"

    $null = Add-AzureRmAccount -ServicePrincipal -Tenant $TenantID -Credential $mycred
    $selectedSubscription = Select-AzureRmSubscription -SubscriptionId $XmlSecrets.secrets.SubscriptionID
    if ( $selectedSubscription.Subscription.Id -eq $XmlSecrets.secrets.SubscriptionID ) {
        LogMsg "Current Subscription : $subIDMasked."
        LogMsg "---------------------------------"
    }
    else {
        LogMsg "There was an error when selecting $subIDMasked."
        LogMsg "---------------------------------"
    }
}
else {
    LogErr "Secret file $secretsFile does not exist"
    ThrowException ("XML Secrets file not provided")
}
