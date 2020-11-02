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
	Example 1 : Run tests by providing command line options.
	.\Run-LisaV2.ps1	-TestPlatform "Azure" -TestLocation "westus2" -RGIdentifier "mylisatest"
					-ARMImageName "Canonical UbuntuServer 16.04-LTS latest"
					-XMLSecretFile "C:\MySecrets.xml"
					-TestNames "VERIFY-DEPLOYMENT-PROVISION"

	Example 2 : Run tests using predefined parameters in XML file.
	.\Run-LisaV2.ps1 -ParametersFile .\XML\TestParameters.xml
	Note: Please refer .\XML\TestParameters.xml file for more details.

	Example 3 : Exclude some tests by TestName match
	.\Run-LisaV2.ps1 -TestPlatform "Azure" -TestLocation "westus2" -RGIdentifier "mylisatest"
					-ARMImageName "Canonical UbuntuServer 16.04-LTS latest"
					-XMLSecretFile "C:\MySecrets.xml"
					-ExcludeTests "VERIFY-DEPLOYMENT-PROVISION,VERIFY-DEPLOYMENT-PROVISION-SRIOV"

	Example 4 : Exclude some tests from Functional category, which has "DISK" keyword [Wildcards match]
	.\Run-LisaV2.ps1 -TestPlatform "Azure" -TestLocation "westus2" -RGIdentifier "mylisatest"
					-ARMImageName "Canonical UbuntuServer 16.04-LTS latest"
					-XMLSecretFile "C:\MySecrets.xml"
					-TestCategory Functional -ExcludeTests '*DISK*'

	Example 5 : Exclude some tests from Storage Area, which has 4 digit number [Regex match]
	.\Run-LisaV2.ps1 -TestPlatform "Azure" -TestLocation "westus2" -RGIdentifier "mylisatest"
					-ARMImageName "Canonical UbuntuServer 16.04-LTS latest"
					-XMLSecretFile "C:\MySecrets.xml"
					-TestArea Storage -ExcludeTests "[0-9][0-9][0-9][0-9]"
#>

[CmdletBinding()]
Param(
	[string] $ParametersFile = "",

	# [Required]
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
							#... [WSL: Mandatory, which can be the URL of the distro, or the path to the distro file on the local host]
							#... [Ready: Not needed, and will be ignored if provided]
	[string] $TestCategory = "",
	[string] $TestArea = "",
	[string] $TestTag = "",
	[string] $TestNames="",
	[string] $TestPriority="",
	[string] $TestSetup="",

	# [Optional] Exclude the tests from being executed. (Comma separated values)
	[string] $ExcludeTests = "",

	# [Optional] Enable kernel code coverage
	[switch] $EnableCodeCoverage,

	# [Optional] Parameters for Image preparation before running tests.
	[string] $CustomKernel = "",
	[string] $CustomLIS,

	# [Optional] Parameters for changing framework behavior.
	[int]    $TestIterations = 1,
	[string] $XMLSecretFile = "",
	[switch] $EnableTelemetry,
	[switch] $UseExistingRG,

	# [Optional] Parameters for setting TiPCluster, TipSessionId, DiskType=Managed/Unmanaged, Networking=SRIOV/Synthetic, ImageType=Specialized/Generalized, OSType=Windows/Linux.
	[string] $CustomParameters = "",

	# [Optional] Parameters for Overriding VM Configuration.
	[string] $CustomTestParameters = "",
	[string] $OverrideVMSize = "",
	[ValidateSet('Default','Keep','Delete',IgnoreCase = $true)]

	# ResourceCleanup options are used to config/control how to proceed the VM and RG resources cleanup between test cases and setupTypes, so
	# 1) At the end of each test setupType (which means next test case will definitely use another different deploy template)
	#		"Default" = By default delete resources if VM and RG resources are still exist, unless 'Keep' is specified
	#		"Keep"    = Always preserve resources for analysis
	#		"Delete"  = Always delete resources before any of the next setupType deployments happen.
	# 2) For each test belongs to the same setupType, we respect last test case result of running, Pass or Fail/Aborted
	#		if lastResult Pass, try to reuse existing deployed VM resources,
	#			unless '-DeployVMPerEachTest' or next test case needs different profile in deploy template, => Delete resources
	#		if lastResult Fail/Aborted, try to Preserve resources for analysis,
	#			unless '-UseExistingRG' or 'ResourceCleanup = Delete', => Delete resources
	#			unless '-ReuseVmOnFailure', => Reuse vm resources, even lastResult is failed.
	#		if 'ResourceCleanup = Keep', we respect to 'Keep' whenever trying to delete an successfully deployed VM resources
	#			but log warning messages when VM and resources need Manual deletion
	#				or when 'Keep' conflicts with other parameters of Run-LISAv2
	[string] $ResourceCleanup,
	[switch] $DeployVMPerEachTest,
	[string] $VMGeneration = "",

	[string] $ResultDBTable = "",
	[string] $ResultDBTestTag = "",
	[string] $TestPassID = "",

	[switch] $ExitWithZero,
	[switch] $ForceCustom,
	[switch] $ReuseVMOnFailure,
	[switch] $RunInParallel,
	[int]    $TotalCountInParallel,
	[string] $TestIdInParallel
)

Set-Location $PSScriptRoot
$CURRENT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
Import-Module "${CURRENT_DIR}\LISAv2-Framework" -Force

$params = @{}
$MyInvocation.MyCommand.Parameters.Keys | ForEach-Object {
	$value = (Get-Variable -Name $_ -Scope "Script" -ErrorAction "SilentlyContinue").Value
	if ($value) {
		$params[$_] = $value
		if ($params.TestNames) {
			$params.TestNames = $params.TestNames.replace(' ','')
		}
		Write-Host ($_ + " = " + $params[$_])
	}
}
$params["Verbose"] = $PSCmdlet.MyInvocation.BoundParameters["Verbose"]

try {
	if ($RunInParallel) {
		$params["ExitWithZero"] = $params.RunInParallel
		Start-LISAv2 @params -ParamsInParallel $params
	}
	else {
		Start-LISAv2 @params
	}
	exit 0
} catch {
	exit 1
}
