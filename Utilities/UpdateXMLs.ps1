##############################################################################################
# UpdateXMLs.ps1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
    Update GlobalConfigurations.xml

.PARAMETER
    <Parameters>

.INPUTS


.NOTES
    Creation Date:
    Purpose/Change:

.EXAMPLE

#>
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