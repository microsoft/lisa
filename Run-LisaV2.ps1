##############################################################################################
# Run-LisaV2.ps1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
<#
.SYNOPSIS
	This is the entrance script for LISAv2.
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
###############################################################################################

[CmdletBinding()]
Param(
	#Do not use. Reserved for Jenkins use.
	$BuildNumber=$env:BUILD_NUMBER,

	#[Optional]
	[string] $ParametersFile = "",

	#[Required]
	[ValidateSet('Azure','HyperV', IgnoreCase = $false)]
	[string] $TestPlatform = "",

	#[Required] for Azure.
	[string] $TestLocation="",
	[string] $ARMImageName = "",
	[string] $StorageAccount="",

	#[Required] for HyperV
	[string] $SourceOsVHDPath="",

	#[Required] for Two Hosts HyperV
	[string] $DestinationOsVHDPath="",

	#[Required] Common for HyperV and Azure.
	[string] $RGIdentifier = "",
	[string] $OsVHD = "",   #... [Azure: Required only if -ARMImageName is not provided.]
							#... [HyperV: Mandatory]
	[string] $TestCategory = "",
	[string] $TestArea = "",
	[string] $TestTag = "",
	[string] $TestNames="",
	[string] $TestPriority="",

	#[Optional] Parameters for Image preparation before running tests.
	[string] $CustomKernel = "",
	[string] $CustomLIS,

	#[Optional] Parameters for changing framework behavior.
	[string] $CoreCountExceededTimeout,
	[int]    $TestIterations,
	[string] $TiPSessionId,
	[string] $TiPCluster,
	[string] $XMLSecretFile = "",
	[switch] $EnableTelemetry,

	#[Optional] Parameters for Overriding VM Configuration.
	[string] $CustomParameters = "",
	[string] $OverrideVMSize = "",
	[switch] $EnableAcceleratedNetworking,
	[string] $OverrideHyperVDiskMode = "",
	[switch] $ForceDeleteResources,
	[switch] $UseManagedDisks,
	[switch] $DoNotDeleteVMs,
	[switch] $DeployVMPerEachTest,
	[string] $VMGeneration = "",

	[string] $ResultDBTable = "",
	[string] $ResultDBTestTag = "",

	[switch] $ExitWithZero
)

# Import the Functions from Library Files.
Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | `
	ForEach-Object { Import-Module $_.FullName -Force -Global -DisableNameChecking }

try {
	$TestID = "{0}{1}" -f $(-join ((65..90) | Get-Random -Count 4 | ForEach-Object {[char]$_})), $(Get-Random -Maximum 99999 -Minimum 11111)
	Write-Host "Test ID generated for this test run: $TestID"
	Set-Variable -Name "TestID" -Value $TestID -Scope Global -Force

	# Prepare the workspace
	$MaxDirLength = 32
	$WorkingDirectory = Split-Path -parent $MyInvocation.MyCommand.Definition
	if ( $WorkingDirectory.Length -gt $MaxDirLength) {
		$OriginalWorkingDirectory = $WorkingDirectory
		$WorkingDirectory = Move-ToNewWorkingSpace $OriginalWorkingDirectory | Select-Object -Last 1
	}
	Set-Variable -Name WorkingDirectory -Value $WorkingDirectory  -Scope Global

	# Prepare log folder
	$LogDir = Join-Path $WorkingDirectory "TestResults\$(Get-Date -Format 'yyyy-dd-MM-HH-mm-ss-ffff')"
	$LogFileName = "LISAv2-Test-$TestID.log"
	Set-Variable -Name LogDir      -Value $LogDir      -Scope Global -Force
	Set-Variable -Name LogFileName -Value $LogFileName -Scope Global -Force
	New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
	LogMsg "Created LogDir: $LogDir"

	# Import parameters from file if -ParametersFile is given, and set them as global variables
	if ($ParametersFile) {
		Import-TestParameters -ParametersFile $ParametersFile
	}
	# Processing parameters provided in the command runtime
	$paramList = (Get-Command -Name $PSCmdlet.MyInvocation.InvocationName).Parameters;
	foreach ($paramName in $paramList.Keys) {
		$paramObject = Get-Variable -Name $paramName -Scope Script -ErrorAction SilentlyContinue
		$paramValue = $paramObject.Value
		if (($null -ne $paramValue) -and ("" -ne $paramValue)) {
			$paramExistingObject = Get-Variable -Name $paramName -Scope Global -ErrorAction SilentlyContinue
			if ($null -ne $paramExistingObject) {
				$paramExistingValue = $paramExistingObject.Value
				if (($null -ne $paramExistingValue) -and ("" -ne $paramExistingValue) -and ($paramValue -ne $paramExistingValue)) {
					LogMsg "Overriding: $paramName = $paramValue (was $paramExistingValue)"
				}
			}
			Set-Variable -Name $paramName -Value $paramValue -Scope Global -Force
		}
	}
	# Change the value of Local variable to the same value of the the corresponding Global variable
	$GlobalVariables = Get-Variable -Scope Global -ErrorAction SilentlyContinue
	foreach ($var in $GlobalVariables) {
		[void](Set-Variable -Name $var.Name -Value $var.Value -Scope Local -ErrorAction SilentlyContinue)
	}
	# Validate the test parameters.
	Validate-Parameters

	# Handle the Secrets file
	if ($env:Azure_Secrets_File) {
		$XMLSecretFile = $env:Azure_Secrets_File
		LogMsg "The Secrets file is defined by an environment variable."
	}
	if ($XMLSecretFile -ne [string]::Empty) {
		if ((Test-Path -Path $XMLSecretFile) -eq $true) {
			$xmlSecrets = ([xml](Get-Content $XMLSecretFile))
			Set-Variable -Value $xmlSecrets -Name XmlSecrets -Scope Global -Force

			# Download the tools required for LISAv2 execution.
			Get-LISAv2Tools -XMLSecretFile $XMLSecretFile

			# Update the configuration files based on the settings in the XMLSecretFile
			UpdateGlobalConfigurationXML $XMLSecretFile
			UpdateXMLStringsFromSecretsFile $XMLSecretFile

			if ($TestPlatform -eq "Azure") {
				.\Utilities\AddAzureRmAccountFromSecretsFile.ps1 -customSecretsFilePath $XMLSecretFile
			}
		} else {
			LogErr "The Secret file provided: $XMLSecretFile does not exist"
		}
	} else {
		LogErr "Failed to update configuration files. '-XMLSecretFile [FilePath]' is not provided."
	}

	Validate-XmlFiles -ParentFolder $WorkingDirectory

	$TestConfigurationXmlFile = "$WorkingDirectory\TestConfiguration.xml"
	Import-TestCases $WorkingDirectory $TestConfigurationXmlFile

	#This function will inject default / custom replaceable test parameters to TestConfiguration.xml
	$ReplaceableTestParameters = [xml](Get-Content -Path "$WorkingDirectory\XML\Other\ReplaceableTestParameters.xml")
	Inject-CustomTestParameters $CustomParameters $ReplaceableTestParameters $TestConfigurationXmlFile

	$xmlConfig = [xml](Get-Content $TestConfigurationXmlFile)
	$xmlConfig.Save("$TestConfigurationXmlFile")
	LogMsg "The auto created $TestConfigurationXmlFile has been validated successfully."

	$command = ".\AutomationManager.ps1 -xmlConfigFile '$TestConfigurationXmlFile' -cycleName 'TC-$TestID' -RGIdentifier '$RGIdentifier'"
	if ( $CustomKernel) { $command += " -CustomKernel '$CustomKernel'" }
	if ( $OverrideVMSize ) { $command += " -OverrideVMSize $OverrideVMSize" }
	if ( $EnableAcceleratedNetworking ) { $command += " -EnableAcceleratedNetworking" }
	if ( $ForceDeleteResources ) { $command += " -ForceDeleteResources" }
	if ( $DoNotDeleteVMs ) { $command += " -DoNotDeleteVMs" }
	if ( $DeployVMPerEachTest ) { $command += " -DeployVMPerEachTest" }
	if ( $CustomLIS) { $command += " -CustomLIS $CustomLIS" }
	if ( $CoreCountExceededTimeout ) { $command += " -CoreCountExceededTimeout $CoreCountExceededTimeout" }
	if ( $TestIterations -gt 1 ) { $command += " -TestIterations $TestIterations" }
	if ( $TiPSessionId) { $command += " -TiPSessionId $TiPSessionId" }
	if ( $TiPCluster) { $command += " -TiPCluster $TiPCluster" }
	if ($UseManagedDisks) {	$command += " -UseManagedDisks" }
	if ($XMLSecretFile) { $command += " -XMLSecretFile '$XMLSecretFile'" }
	LogMsg $command

	Invoke-Expression -Command $command

	$zipFile = "$TestPlatform"
	if ( $TestCategory ) { $zipFile += "-$TestCategory"	}
	if ( $TestArea ) { $zipFile += "-$TestArea" }
	if ( $TestTag ) { $zipFile += "-$($TestTag)" }
	$zipFile += "-$TestID-TestLogs.zip"
	New-ZipFile -zipFileName $zipFile -sourceDir $LogDir

	$reportXmlJUnit = $TestReportXml.Replace(".xml", "-junit.xml")
	if (Test-Path -Path $TestReportXml ) {
		Copy-Item -Path $TestReportXml -Destination $reportXmlJUnit -Force -ErrorAction SilentlyContinue
		LogMsg "Copied : $TestReportXml --> $reportXmlJUnit"
		LogMsg "Analyzing results.."
		$resultXML = [xml](Get-Content $TestReportXml -ErrorAction SilentlyContinue)
		LogMsg "PASS  : $($resultXML.testsuites.testsuite.tests - $resultXML.testsuites.testsuite.errors - $resultXML.testsuites.testsuite.failures)"
		LogMsg "FAIL  : $($resultXML.testsuites.testsuite.failures)"
		LogMsg "ABORT : $($resultXML.testsuites.testsuite.errors)"
		if ( ( $resultXML.testsuites.testsuite.failures -eq 0 ) -and ( $resultXML.testsuites.testsuite.errors -eq 0 ) -and ( $resultXML.testsuites.testsuite.tests -gt 0 )) {
			$ExitCode = 0
		} else {
			$ExitCode = 1
		}
	} else {
		LogErr "Summary file: $TestReportXml does not exist. Exiting with ErrorCode 1."
		$ExitCode = 1
	}
} catch {
	$line = $_.InvocationInfo.ScriptLineNumber
	$script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
	$ErrorMessage =  $_.Exception.Message

	LogErr "EXCEPTION : $ErrorMessage"
	LogErr "Source : Line $line in script $script_name."
	$ExitCode = 1
} finally {
	if ( $ExitWithZero -and ($ExitCode -ne 0) ) {
		LogMsg "Suppress the exit code from $ExitWithZero to 0. (-ExitWithZero specified in command line)"
		$ExitCode = 0
	}

	if ( $OriginalWorkingDirectory ) {
		Move-BackToOriginalWorkingSpace $WorkingDirectory $OriginalWorkingDirectory
	}
	Get-Variable -Exclude PWD,*Preference,ExitCode | Remove-Variable -Force -ErrorAction SilentlyContinue
	LogMsg "LISAv2 exits with code: $ExitCode"

	exit $ExitCode
}
