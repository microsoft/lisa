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
    [string]$SubscriptionID,
    [string]$LinuxUsername,
    [string]$LinuxPassword 
)
$GlobalXML = [xml](Get-Content ".\XML\GlobalConfigurations.xml")
$GlobalXML.Global.Azure.Subscription.SubscriptionID = $SubscriptionID
$GlobalXML.Global.Azure.TestCredentials.LinuxUsername = $LinuxUsername
$GlobalXML.Global.Azure.TestCredentials.LinuxPassword = $LinuxPassword
$GlobalXML.Save(".\XML\GlobalConfigurations.xml")
Write-Host "Updated GlobalConfigurations.xml"