# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
<#
.SYNOPSIS
	This is the shim entry script for LISAv2.
	LISAv2 is the test framework running Linux test automation on Azure and HyperV platforms,
	including remote test launching in dev system.

.PARAMETER
	See source code for the detailed parameters

.NOTES
	PREREQUISITES:
	1) Prepare necessary 3rd party tools and put them into the Tools folder;
	2) Review the XML configuration files under XML folder and make necessary change for your environment.
	See more from https://github.com/LIS/LISAv2 for helps including README and How-to-use document.

.EXAMPLE
	.\Run-LisaV2.ps1	-TestPlatform "Azure" -TestLocation "westus2" -RGIdentifier "mylisatest"
					-ARMImageName "Canonical UbuntuServer 16.04-LTS latest"
					-XMLSecretFile "C:\MySecrets.xml"
					-TestNames "BVT-VERIFY-DEPLOYMENT-PROVISION"

	.\Run-LisaV2.ps1 -ParametersFile .\XML\TestParameters.xml
	Note: Please refer .\XML\TestParameters.xml file for more details.

#>

[CmdletBinding()]
Param(
	[string] $ParametersFile = "",

	# [Required]
	[ValidateSet('Azure','HyperV', IgnoreCase = $false)]
	[string] $TestPlatform = "",

	# [Required] for Azure.
	[string] $TestLocation="",
	[string] $ARMImageName = "",
	[string] $StorageAccount="",

	# [Required] for Two Hosts HyperV
	[string] $DestinationOsVHDPath="",

	# [Required] Common for HyperV and Azure.
	[string] $RGIdentifier = "",
	[string] $OsVHD = "",   #... [Azure: Required only if -ARMImageName is not provided.]
							#... [HyperV: Mandatory]
	[string] $TestCategory = "",
	[string] $TestArea = "",
	[string] $TestTag = "",
	[string] $TestNames="",
	[string] $TestPriority="",

	# [Optional] Parameters for Image preparation before running tests.
	[string] $CustomKernel = "",
	[string] $CustomLIS,

	# [Optional] Parameters for changing framework behavior.
	[int]    $TestIterations = 1,
	[string] $TiPSessionId,
	[string] $TiPCluster,
	[string] $XMLSecretFile = "",
	[switch] $EnableTelemetry,
	[switch] $UseExistingRG,

	# [Optional] Parameters for Overriding VM Configuration.
	[string] $CustomParameters = "",
	[string] $OverrideVMSize = "",
	[switch] $EnableAcceleratedNetworking,
	[switch] $ForceDeleteResources,
	[switch] $UseManagedDisks,
	[switch] $DoNotDeleteVMs,
	[switch] $DeployVMPerEachTest,
	[string] $VMGeneration = "",

	[string] $ResultDBTable = "",
	[string] $ResultDBTestTag = "",

	[switch] $ExitWithZero
)


$CURRENT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
Import-Module "${CURRENT_DIR}\LISAv2-Framework"

$params = @{}
$MyInvocation.MyCommand.Parameters.Keys | ForEach-Object {
	$value = (Get-Variable -Name $_ -Scope "Script" -ErrorAction "SilentlyContinue").Value
	if ($value) {
		$params[$_] = $value
	}
}
$params["Verbose"] = $PSCmdlet.MyInvocation.BoundParameters["Verbose"]

try {
	Start-LISAv2 @params
	exit 0
} catch {
	exit 1
}