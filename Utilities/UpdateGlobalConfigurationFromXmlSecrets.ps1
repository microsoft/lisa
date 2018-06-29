##############################################################################################
# UpdateXMLs.ps1
# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for full license information.
# Description : 
# Operations :
#              
## Author : lisasupport@microsoft.com
###############################################################################################
param(
    [string]$XmlSecretsFilePath= ""
)

$xmlGlobalConfigPath = Resolve-Path -Path ".\XML\GlobalConfigurations.xml"
$XmlSecrets = [xml](Get-Content $XmlSecretsFilePath)
$GlobalXML = [xml](Get-Content $xmlGlobalConfigPath)
$GlobalXML.Global.Azure.Subscription.SubscriptionID = $XmlSecrets.secrets.SubscriptionID

$GlobalXML.Global.Azure.TestCredentials.LinuxUsername = $XmlSecrets.secrets.linuxTestUsername
$GlobalXML.Global.Azure.TestCredentials.LinuxPassword = $XmlSecrets.secrets.linuxTestPassword

$GlobalXML.Global.Azure.ResultsDatabase.server = $XmlSecrets.secrets.DatabaseServer
$GlobalXML.Global.Azure.ResultsDatabase.user = $XmlSecrets.secrets.DatabaseUser
$GlobalXML.Global.Azure.ResultsDatabase.password = $XmlSecrets.secrets.DatabasePassword
$GlobalXML.Global.Azure.ResultsDatabase.dbname = $XmlSecrets.secrets.DatabaseName
$GlobalXML.Save($xmlGlobalConfigPath)

Write-Host "Updated GlobalConfigurations.xml"