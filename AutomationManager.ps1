##############################################################################################
# AutomationManager.ps1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
<#
.SYNOPSIS
	This script manages all the setup and test operations in Azure & Hyper-V environemnt.
		It is an entry script of Automation
		Installing AzureSDK
		- VHD preparation : Installing packages required by ICA, LIS drivers and WALA
		- Uplaoding test VHD to cloud
		- Invokes Azure test suite or Hyper-v tests

.PARAMETER
#	See param lines

.INPUTS
	Load dependent modules
	Set all parameters are ito global vars
	Azure login
	Start AzureTestSuite.ps1, if for Azure testing
#>
###############################################################################################
param (
[CmdletBinding()]
[string] $xmlConfigFile,
[switch] $eMail,
[switch] $runtests, [switch]$onCloud,
[switch] $vhdprep,
[switch] $upload,
[switch] $help,
[string] $RGIdentifier,
[string] $cycleName,
[string] $RunSelectedTests,
[string] $TestPriority,
[string] $osImage,
[switch] $EconomyMode,
[switch] $DoNotDeleteVMs,
[switch] $UseAzureResourceManager,
[string] $OverrideVMSize,
[switch] $EnableAcceleratedNetworking,
[string] $CustomKernel,
[string] $CustomLIS,
[string] $customLISBranch,
[string] $resizeVMsAfterDeployment,
[string] $ExistingResourceGroup,
[switch] $CleanupExistingRG,
[string] $XMLSecretFile,

# Experimental Feature
[switch] $UseManagedDisks,

[int] $CoreCountExceededTimeout = 3600,
[int] $TestIterations = 1,
[string] $TiPSessionId="",
[string] $TiPCluster="",
[switch] $ForceDeleteResources
)

Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global}

$xmlConfig = [xml](Get-Content $xmlConfigFile)
$user = $xmlConfig.config.$TestPlatform.Deployment.Data.UserName
$password = $xmlConfig.config.$TestPlatform.Deployment.Data.Password
$sshKey = $xmlConfig.config.$TestPlatform.Deployment.Data.sshKey
$sshPublickey = $xmlConfig.config.$TestPlatform.Deployment.Data.sshPublicKey

Set-Variable -Name user -Value $user -Scope Global
Set-Variable -Name password -Value $password -Scope Global
Set-Variable -Name sshKey -Value $sshKey -Scope Global
Set-Variable -Name sshPublicKey -Value $sshPublicKey -Scope Global
Set-Variable -Name sshPublicKeyThumbprint -Value $sshPublicKeyThumbprint -Scope Global
Set-Variable -Name PublicConfiguration -Value @() -Scope Global
Set-Variable -Name PrivateConfiguration -Value @() -Scope Global
Set-Variable -Name CurrentTestData -Value $CurrentTestData -Scope Global
Set-Variable -Name preserveKeyword -Value "preserving" -Scope Global
Set-Variable -Name TiPSessionId -Value $TiPSessionId -Scope Global
Set-Variable -Name TiPCluster -Value $TiPCluster -Scope Global

Set-Variable -Name global4digitRandom -Value $(Get-Random -SetSeed $(Get-Random) -Maximum 9999 -Minimum 1111) -Scope Global
Set-Variable -Name CoreCountExceededTimeout -Value $CoreCountExceededTimeout -Scope Global

Set-Variable -Name resultPass -Value "PASS" -Scope Global
Set-Variable -Name resultFail -Value "FAIL" -Scope Global
Set-Variable -Name resultAborted -Value "ABORTED" -Scope Global

if($EnableAcceleratedNetworking) {
	Set-Variable -Name EnableAcceleratedNetworking -Value $true -Scope Global
}

if($ForceDeleteResources) {
	Set-Variable -Name ForceDeleteResources -Value $true -Scope Global
}

if($resizeVMsAfterDeployment) {
	Set-Variable -Name resizeVMsAfterDeployment -Value $resizeVMsAfterDeployment -Scope Global
}

if ( $OverrideVMSize ) {
	Set-Variable -Name OverrideVMSize -Value $OverrideVMSize -Scope Global
}

if ( $CustomKernel ) {
	Set-Variable -Name CustomKernel -Value $CustomKernel -Scope Global
}

if ( $CustomLIS ) {
	Set-Variable -Name CustomLIS -Value $CustomLIS -Scope Global
}

if ( $customLISBranch ) {
	Set-Variable -Name customLISBranch -Value $customLISBranch -Scope Global
}

if ( $RunSelectedTests ) {
	Set-Variable -Name RunSelectedTests -Value $RunSelectedTests -Scope Global
}

if ($ExistingResourceGroup) {
	Set-Variable -Name ExistingRG -Value $ExistingResourceGroup -Scope Global
}

if ($CleanupExistingRG) {
	Set-Variable -Name CleanupExistingRG -Value $true -Scope Global
} else {
	Set-Variable -Name CleanupExistingRG -Value $false -Scope Global
}

if ($UseManagedDisks) {
	Set-Variable -Name UseManagedDisks -Value $true -Scope Global
} else {
	Set-Variable -Name UseManagedDisks -Value $false -Scope Global
}

if ( $XMLSecretFile ) {
	$xmlSecrets = ([xml](Get-Content $XMLSecretFile))
	Set-Variable -Value $xmlSecrets -Name xmlSecrets -Scope Global -Force
	LogMsg "XmlSecrets set as global variable."
} elseif ($env:Azure_Secrets_File) {
	$xmlSecrets = ([xml](Get-Content $env:Azure_Secrets_File))
	Set-Variable -Value $xmlSecrets -Name xmlSecrets -Scope Global -Force
	LogMsg "XmlSecrets set as global variable."
}

try {
	$TestResultsDir = "TestResults"
	if (! (test-path $TestResultsDir)) {
		mkdir $TestResultsDir | out-null
	}

	if (! (test-path ".\report")) {
		mkdir ".\report" | out-null
	}

	$testStartTime = [DateTime]::Now.ToUniversalTime()
	Set-Variable -Name testStartTime -Value $testStartTime -Scope Global
	Set-Content -Value "" -Path .\report\testSummary.html -Force -ErrorAction SilentlyContinue | Out-Null
	Set-Content -Value "" -Path .\report\AdditionalInfo.html -Force -ErrorAction SilentlyContinue | Out-Null
	Set-Variable -Name LogFile -Value $LogFile -Scope Global
	Set-Variable -Name Distro -Value $RGIdentifier -Scope Global
	Set-Variable -Name onCloud -Value $onCloud -Scope Global
	Set-Variable -Name xmlConfig -Value $xmlConfig -Scope Global
	LogMsg "'$LogDir' saved to .\report\lastLogDirectory.txt"
	Set-Content -Path .\report\lastLogDirectory.txt -Value $LogDir -Force
	Set-Variable -Name vnetIsAllConfigured -Value $false -Scope Global

	if($EconomyMode) {
		Set-Variable -Name EconomyMode -Value $true -Scope Global
		Set-Variable -Name DoNotDeleteVMs -Value $DoNotDeleteVMs -Scope Global
	} else {
		Set-Variable -Name EconomyMode -Value $false -Scope Global
		if($DoNotDeleteVMs) {
			Set-Variable -Name DoNotDeleteVMs -Value $true -Scope Global
		} else {
			Set-Variable -Name DoNotDeleteVMs -Value $false -Scope Global
		}
	}

	$AzureSetup = $xmlConfig.config.$TestPlatform.General
	LogMsg  ("Info : AzureAutomationManager.ps1 - LIS on Azure Automation")
	LogMsg  ("Info : Created test results directory:$LogDir" )
	LogMsg  ("Info : Using config file $xmlConfigFile")
	if ( ( $xmlConfig.config.$TestPlatform.General.ARMStorageAccount -imatch "ExistingStorage" ) -or ($xmlConfig.config.$TestPlatform.General.StorageAccount -imatch "ExistingStorage" )) {
		$regionName = $xmlConfig.config.$TestPlatform.General.Location.Replace(" ","").Replace('"',"").ToLower()
		$regionStorageMapping = [xml](Get-Content .\XML\RegionAndStorageAccounts.xml)

		if ( $xmlConfig.config.$TestPlatform.General.ARMStorageAccount -imatch "standard") {
			$xmlConfig.config.$TestPlatform.General.ARMStorageAccount = $regionStorageMapping.AllRegions.$regionName.StandardStorage
			LogMsg "Info : Selecting existing standard storage account in $regionName - $($regionStorageMapping.AllRegions.$regionName.StandardStorage)"
		}

		if ( $xmlConfig.config.$TestPlatform.General.ARMStorageAccount -imatch "premium") {
			$xmlConfig.config.$TestPlatform.General.ARMStorageAccount = $regionStorageMapping.AllRegions.$regionName.PremiumStorage
			LogMsg "Info : Selecting existing premium storage account in $regionName - $($regionStorageMapping.AllRegions.$regionName.PremiumStorage)"
		}
	}

	Set-Variable -Name UseAzureResourceManager -Value $true -Scope Global

	if ( $TestPlatform -eq "Azure") {
		$SelectedSubscription = Select-AzureRmSubscription -SubscriptionId $AzureSetup.SubscriptionID
		$subIDSplitted = ($SelectedSubscription.Subscription.SubscriptionId).Split("-")
		$userIDSplitted = ($SelectedSubscription.Account.Id).Split("-")
		LogMsg "SubscriptionName       : $($SelectedSubscription.Subscription.Name)"
		LogMsg "SubscriptionId         : $($subIDSplitted[0])-xxxx-xxxx-xxxx-$($subIDSplitted[4])"
		LogMsg "User                   : $($userIDSplitted[0])-xxxx-xxxx-xxxx-$($userIDSplitted[4])"
		LogMsg "ServiceEndpoint        : $($SelectedSubscription.Environment.ActiveDirectoryServiceEndpointResourceId)"
		LogMsg "CurrentStorageAccount  : $($AzureSetup.ARMStorageAccount)"
	} elseif  ( $TestPlatform -eq "HyperV") {
		LogMsg "HyperV Host            : $($xmlConfig.config.Hyperv.Host.ServerName)"
		LogMsg "Source VHD Path        : $($xmlConfig.config.Hyperv.Host.SourceOsVHDPath)"
		LogMsg "Destination VHD Path   : $($xmlConfig.config.Hyperv.Host.DestinationOsVHDPath)"
	}

	if($DoNotDeleteVMs) {
		LogMsg "PLEASE NOTE: DoNotDeleteVMs is set. VMs will not be deleted after test is finished even if, test gets PASS."
	}

	$testCycle =  GetCurrentCycleData -xmlConfig $xmlConfig -cycleName $cycleName
	$testSuiteResultDetails=.\AzureTestSuite.ps1 $xmlConfig -Distro $Distro -cycleName $cycleName -TestIterations $TestIterations
	$logDirFilename = [System.IO.Path]::GetFilenameWithoutExtension($xmlConfigFile)
	$summaryAll = GetTestSummary -testCycle $testCycle -StartTime $testStartTime -xmlFileName $logDirFilename -distro $Distro -testSuiteResultDetails $testSuiteResultDetails
	$PlainTextSummary += $summaryAll[0]
	$HtmlTextSummary += $summaryAll[1]
	Set-Content -Value $HtmlTextSummary -Path .\report\testSummary.html -Force | Out-Null
	$PlainTextSummary = $PlainTextSummary.Replace("<br />", "`r`n")
	$PlainTextSummary = $PlainTextSummary.Replace("<pre>", "")
	$PlainTextSummary = $PlainTextSummary.Replace("</pre>", "")
	LogMsg  "$PlainTextSummary"

	if($eMail){
		SendEmail $xmlConfig -body $HtmlTextSummary
	}
}

catch {
	ThrowException($_)
}
Finally {
	exit
}