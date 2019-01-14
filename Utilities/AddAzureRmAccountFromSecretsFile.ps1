
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
    [string]$customSecretsFilePath,
    [string]$LogFileName = "AddAzureRmAccountFromSecretsFile.log"
)

$ErrorActionPreference = "Stop"
#---------------------------------------------------------[Initializations]--------------------------------------------------------
if (!$global:LogFileName){
     Set-Variable -Name LogFileName -Value $LogFileName -Scope Global -Force
}
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Definition
$rootPath = Split-Path -Parent $scriptPath
Get-ChildItem (Join-Path $rootPath "Libraries") -Recurse | `
    Where-Object { $_.FullName.EndsWith(".psm1") } | `
    ForEach-Object { Import-Module $_.FullName -Force -Global -DisableNameChecking }

Add-AzureAccountFromSecretsFile -CustomSecretsFilePath $customSecretsFilePath