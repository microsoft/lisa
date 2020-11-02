##############################################################################################
# AzureController.psm1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
	PS modules for LISAv2 test automation
	This module drives the test on Azure

.PARAMETER
	<Parameters>

.INPUTS


.NOTES
	Creation Date:
	Purpose/Change:

.EXAMPLE


#>
###############################################################################################
using Module ".\TestController.psm1"
using Module "..\TestProviders\AzureProvider.psm1"

Class AzureController : TestController {
	[string] $ARMImageName
	[string] $StorageAccount

	AzureController() {
		$this.TestProvider = New-Object -TypeName "AzureProvider"
		$this.TestPlatform = "Azure"
	}

	[void] ParseAndValidateParameters([Hashtable]$ParamTable) {
		$parameterErrors = ([TestController]$this).ParseAndValidateParameters($ParamTable)

		if ($this.TestLocation) {
			$this.TestLocation = $this.TestLocation.Replace('"', "").ToLower()
			$this.SyncEquivalentCustomParameters("TestLocation", $this.TestLocation)
		}
		if (!$this.RGIdentifier) {
			$parameterErrors += "-RGIdentifier is not set"
		}
		if ($ParamTable["StorageAccount"] -imatch "^NewStorage_") {
			Throw "LISAv2 only supports specified storage account by '-StorageAccount' or candidate parameters values as below. `n
			Please use '-StorageAccount ""Auto_Complete_RG=XXXResourceGroupName""' or `n
			'-StorageAccount ""Existing_Storage_Standard""' or `n
			'-StorageAccount ""Existing_Storage_Premium""'"
		}
		else {
			$this.StorageAccount = $ParamTable["StorageAccount"]
		}

		$this.ARMImageName = $ParamTable["ARMImageName"]
		$this.SyncEquivalentCustomParameters("ARMImageName", $this.ARMImageName)
		# After triming multi blanks internally between publisher, offer, sku, and version. Keep sync again between '-ARMImageName' and '-CustomParameters ARMImageName=xxx'
		if ($this.ARMImageName) {
			$this.ARMImageName = $this.ARMImageName -replace '\s{2,}', ' '
			$ParamTable["ARMImageName"] = $this.ARMImageName
			$this.SyncEquivalentCustomParameters("ARMImageName", $this.ARMImageName)
		}

		# Validate -ARMImageName and -OsVHD
		# when both OsVHD and ARMImageName exist, parameterErrors += "..."
		if ($this.OsVHD -and $this.ARMImageName) {
			$parameterErrors += "'-OsVHD' could not coexist with '-ARMImageName' when testing against 'Azure' Platform."
		}
		elseif ($this.OsVHD) {
			if ($this.OsVHD -and [System.IO.Path]::GetExtension($this.OsVHD) -ne ".vhd" -and !$this.OsVHD.Contains("vhd")) {
				$parameterErrors += "-OsVHD $($this.OsVHD) does not have .vhd (.vhdx is not supported) extension required by Platform Azure."
			}
			if ($this.VMGeneration -and (("1", "2") -notcontains $this.VMGeneration)) {
				$parameterErrors += "-VMGeneration '$($this.VMGeneration)' is not supported."
			}
		}
		elseif (!$this.ARMImageName) {
			# Both $this.OsVHD and $this.ARMImageName are empty, <DefaultARMImageName> from .\XML\GlobalConfigurations.xml should be applied as default value
			# $this.GlobalConfig has been set by base ([TestController]$this).ParseAndValidateParameters() at the beginning of this overwritten function
			if (!$this.GlobalConfig.Global.Azure.DefaultARMImageName) {
				$parameterErrors += "-OsVHD <'VHD_Name.vhd'>, or -ARMImageName '<Publisher> <Offer> <Sku> <Version>,<Publisher> <Offer> <Sku> <Version>,...', or <DefaultARMImageName> from .\XML\GlobalConfigurations.xml if required."
			}
		}
		elseif ($this.ARMImageName) {
			$ArmImagesToBeUsed = @($this.ARMImageName.Trim(", ").Split(',').Trim())
			if ($ArmImagesToBeUsed | Where-Object { $_.Split(" ").Count -ne 4 }) {
				$parameterErrors += ("Invalid value for the provided ARMImageName parameter: <'$($this.ARMImageName)'>." + `
						"The ARM image should be in the format: '<Publisher> <Offer> <Sku> <Version>,<Publisher> <Offer> <Sku> <Version>,...'")
			}
		}

		if ($this.CustomParams["TipSessionId"] -or $this.CustomParams["TipCluster"]) {
			if (!$this.CustomParams["TipSessionId"] -or !$this.CustomParams["TipCluster"]) {
				$parameterErrors += "Both 'TipSessionId' and 'TipCluster' are necessary in CustomParameters when Run-LISAv2 with TiP."
			}
			# Force $this.UseExistingRG = $true when testing with TiP, and always stick to the provided Resoruce Group by '-RGIdentifier'
			$this.UseExistingRG = $true
			$this.TestProvider.RunWithTiP = $true
			if (!$this.TestLocation) {
				$parameterErrors += "'-TestLocation' is necessary when Run-LISAv2 with 'TiPSessionId' and 'TiPCluster'."
			}
			if (!$this.CustomParams["PlatformFaultDomainCount"]) {
				Write-LogWarn "'PlatformFaultDomainCount' is not provided in CustomParameters, use default value 1"
				$this.CustomParams["PlatformFaultDomainCount"] = 1
			}
			if (!$this.CustomParams["PlatformUpdateDomainCount"]) {
				Write-LogWarn "'PlatformUpdateDomainCount' is not provided in CustomParameters, use default value 1"
				$this.CustomParams["PlatformUpdateDomainCount"] = 1
			}
		}
		else {
			if (!$this.CustomParams["PlatformFaultDomainCount"]) {
				$this.CustomParams["PlatformFaultDomainCount"] = 2
			}
			if (!$this.CustomParams["PlatformUpdateDomainCount"]) {
				$this.CustomParams["PlatformUpdateDomainCount"] = 5
			}
		}
		$this.TestProvider.EnableTelemetry = $ParamTable["EnableTelemetry"]
		if ($this.CustomParams["EnableNSG"] -and $this.CustomParams["EnableNSG"] -eq "true") {
			$this.TestProvider.EnableNSG = $true
		}

		if ($parameterErrors.Count -gt 0) {
			$parameterErrors | ForEach-Object { Write-LogErr $_ }
			throw "Failed to validate the test parameters provided. Please fix above issues and retry."
		}
		else {
			Write-LogInfo "Test parameters for Azure have been validated successfully. Continue running the test."
		}
	}

	[void] PrepareTestEnvironment($XMLSecretFile) {
		if ($XMLSecretFile -and (Test-Path $XMLSecretFile)) {
			# Connect AzureAccount and Set Azure Context
			Add-AzureAccountFromSecretsFile -CustomSecretsFilePath $XMLSecretFile
			# Place prepare storage accounts before invoke Base.PrepareTestEnvironment($XMLSecretFile)
			if ($this.StorageAccount -imatch "^Auto_Complete_RG=.+") {
				$storageAccountRG = $this.StorageAccount.Trim('= ').Split('=').Trim()[1]
				# Prepare storage accounts (create new storage accounts if needed), and update AzureSecretFile with new set of StorageAccounts
				# and update content of .XML\RegionAndStorageAccounts.xml
				PrepareAutoCompleteStorageAccounts -storageAccountsRGName $storageAccountRG -XMLSecretFile $XMLSecretFile
			}
			if ($this.UseExistingRG -and !$this.RunInParallel) {
				$allExistingResources = Get-AzResource -ResourceGroupName $this.RGIdentifier -ErrorAction SilentlyContinue
				if ($this.TestProvider.RunWithTiP -and $allExistingResources -and ($this.ResourceCleanup -eq "Delete")) {
					Write-LogInfo "Try to cleanup all resources from existing Resource Group '$($this.RGIdentifier)'..."
					$isRGDeleted = Delete-ResourceGroup -RGName $this.RGIdentifier -UseExistingRG $this.UseExistingRG
					if (!$isRGDeleted) {
						throw "Failed to cleanup resources from '$($this.RGIdentifier)', please remove all resources manually."
					}
				}
				elseif (!$allExistingResources) {
					Write-LogWarn "Resource group '$($this.RGIdentifier)' is empty, new resources will be deployed"
				}
			}
		}
		# Invoke Base.PrepareTestEnvironment($XMLSecretFile)
		([TestController]$this).PrepareTestEnvironment($XMLSecretFile)
		$RegionAndStorageMapFile = "$PSScriptRoot\..\XML\RegionAndStorageAccounts.xml"
		if (Test-Path $RegionAndStorageMapFile) {
			$RegionAndStorageMap = [xml](Get-Content $RegionAndStorageMapFile)
		}
		else {
			throw "File '$RegionAndStorageMapFile' does not exist"
		}
		$azureConfig = $this.GlobalConfig.Global.Azure
		# $this.XMLSecrets will be assigned after Base.PrepareTestEnvironment($XMLSecretFile)
		if ($this.XMLSecrets) {
			$secrets = $this.XMLSecrets.secrets
			$azureConfig.Subscription.SubscriptionID = $secrets.SubscriptionID
			$azureConfig.TestCredentials.LinuxUsername = $secrets.linuxTestUsername
			$azureConfig.TestCredentials.LinuxPassword = if ($secrets.linuxTestPassword) { $secrets.linuxTestPassword } else { "" }
			$azureConfig.TestCredentials.sshPrivateKey = Get-SSHKey -XMLSecretFile $XMLSecretFile
			$azureConfig.ResultsDatabase.server = if ($secrets.DatabaseServer) { $secrets.DatabaseServer } else { "" }
			$azureConfig.ResultsDatabase.user = if ($secrets.DatabaseUser) { $secrets.DatabaseUser } else { "" }
			$azureConfig.ResultsDatabase.password = if ($secrets.DatabasePassword) { $secrets.DatabasePassword } else { "" }
			$azureConfig.ResultsDatabase.dbname = if ($secrets.DatabaseName) { $secrets.DatabaseName } else { "" }
		}
		$this.VmUsername = $azureConfig.TestCredentials.LinuxUsername
		$this.VmPassword = $azureConfig.TestCredentials.LinuxPassword
		$this.SSHPrivateKey = $azureConfig.TestCredentials.sshPrivateKey

		# global variables: StorageAccount, TestLocation
		if ($this.TestLocation -and ($this.TestLocation.Trim(", ").Split(",").Trim().Count -eq 1)) {
			if ( $this.StorageAccount -imatch "^ExistingStorage_Standard" ) {
				$azureConfig.Subscription.ARMStorageAccount = $RegionAndStorageMap.AllRegions.$($this.TestLocation).StandardStorage
				Write-LogInfo "Selecting existing standard storage account in $($this.TestLocation) - $($azureConfig.Subscription.ARMStorageAccount)"
			}
			elseif ( $this.StorageAccount -imatch "^ExistingStorage_Premium" ) {
				$azureConfig.Subscription.ARMStorageAccount = $RegionAndStorageMap.AllRegions.$($this.TestLocation).PremiumStorage
				$this.SyncEquivalentCustomParameters("StorageAccountType", "Premium_LRS")
				Write-LogInfo "Selecting existing premium storage account in $($this.TestLocation) - $($azureConfig.Subscription.ARMStorageAccount)"
			}
			elseif ($this.StorageAccount -and ($this.StorageAccount -inotmatch "^Auto_Complete_RG=.+")) {
				# $this.StorageAccount should be some exact name of Storage Account
				$sc = Get-AzStorageAccount | Where-Object { $_.StorageAccountName -eq $this.StorageAccount }
				if (!$sc) {
					Throw "Provided storage account $($this.StorageAccount) does not exist, abort testing."
				}
				if ($sc.Location -ne $this.TestLocation) {
					Throw "Provided storage account $($this.StorageAccount) location $($sc.Location) is different from test location $($this.TestLocation), abort testing."
				}
				$azureConfig.Subscription.ARMStorageAccount = $this.StorageAccount.Trim()
				Write-LogInfo "Selecting custom storage account : $($azureConfig.Subscription.ARMStorageAccount) as per your test region."
			}
			else {
				# else means $this.StorageAccount is empty, or $this.StorageAccount is like 'Auto_Complete_RG=Xxx'
				$azureConfig.Subscription.ARMStorageAccount = $RegionAndStorageMap.AllRegions.$($this.TestLocation).StandardStorage
				Write-LogInfo "Auto selecting storage account : $($azureConfig.Subscription.ARMStorageAccount) as per your test region."
			}

			# Restore $this.OsVHD to full URI with target storage account and container info, when '-OsVHD' is just provided with file BaseName and '-TargeLocation' is a single region
			if ($this.OsVHD -and $this.OsVHD -inotmatch "/") {
				$this.OsVHD = 'http://{0}.blob.core.windows.net/vhds/{1}' -f $azureConfig.Subscription.ARMStorageAccount, $this.OsVHD
				$this.SyncEquivalentCustomParameters("OsVHD", $this.OsVHD)
			}
		}
		else {
			if ($this.StorageAccount -imatch "^ExistingStorage_Premium") {
				$azureConfig.Subscription.ARMStorageAccount = $RegionAndStorageMap.AllRegions.ChildNodes[0].PremiumStorage
				$this.SyncEquivalentCustomParameters("StorageAccountType", "Premium_LRS")
			}
			elseif ($this.StorageAccount -and ($this.StorageAccount -inotmatch "^ExistingStorage_Standard") -and ($this.StorageAccount -inotmatch "^Auto_Complete_RG=.+")) {
				# $this.StorageAccount should be some exact name of Storage Account
				$sc = Get-AzStorageAccount | Where-Object { $_.StorageAccountName -eq $this.StorageAccount }
				if (!$sc) {
					Throw "Provided storage account $($this.StorageAccount) does not exist, abort testing."
				}
				if ($sc.Sku.Name -eq "Premium_LRS") {
					$this.SyncEquivalentCustomParameters("StorageAccountType", "Premium_LRS")
				}
				if (!$this.TestLocation) {
					Write-LogWarn "'-TestLocation' parameter is empty, choose the storage account '$($this.StorageAccount)' location '$($sc.Location)' as default TestLocation"
					$this.TestLocation = $sc.Location
					$this.SyncEquivalentCustomParameters("TestLocation", $this.TestLocation)
				}
				$azureConfig.Subscription.ARMStorageAccount = $this.StorageAccount.Trim()
				# Restore $this.OsVHD to full URI with target storage account and container info, when '-OsVHD' is just provided with file BaseName and '-TargeLocation' is a single region
				if ($this.OsVHD -and $this.OsVHD -inotmatch "/") {
					$this.OsVHD = 'http://{0}.blob.core.windows.net/vhds/{1}' -f $azureConfig.Subscription.ARMStorageAccount, $this.OsVHD
					$this.SyncEquivalentCustomParameters("OsVHD", $this.OsVHD)
				}
			}
			else {
				# Parameter '-TestLocation' is null or $this.StorageAccount -imatch "^ExistingStorage_Standard", by default, select the first standard storage account
				# per storage accounts from .\XML\RegionAndStorageAccounts.xml (or copied from secrets xml file)
				# this will be updated after auto selected the proper TestLocation/Region for each test on Azure platform
				$azureConfig.Subscription.ARMStorageAccount = $RegionAndStorageMap.AllRegions.ChildNodes[0].StandardStorage
			}
		}

		if ($this.ResultDBTable) {
			$azureConfig.ResultsDatabase.dbtable = ($this.ResultDBTable).Trim()
			Write-LogInfo "ResultDBTable : $($this.ResultDBTable) added to GlobalConfig.Global.Azure.ResultsDatabase.dbtable"
		}
		if ($this.ResultDBTestTag) {
			$azureConfig.ResultsDatabase.testTag = ($this.ResultDBTestTag).Trim()
			Write-LogInfo "ResultDBTestTag: $($this.ResultDBTestTag) added to GlobalConfig.Global.Azure.ResultsDatabase.testTag"
		}

		Write-LogInfo "------------------------------------------------------------------"

		$SelectedSubscription = Set-AzContext -SubscriptionId $azureConfig.Subscription.SubscriptionID
		$azureConfig.Subscription.AccountType = $SelectedSubscription.Account.Type
		$subIDSplitted = ($SelectedSubscription.Subscription.SubscriptionId).Split("-")
		Write-LogInfo "SubscriptionName       : $($SelectedSubscription.Subscription.Name)"
		Write-LogInfo "SubscriptionId         : $($subIDSplitted[0])-xxxx-xxxx-xxxx-$($subIDSplitted[4])"
		Write-LogInfo "AccountId              : $($SelectedSubscription.Account.Id)"
		Write-LogInfo "ServiceEndpoint        : $($SelectedSubscription.Environment.ActiveDirectoryServiceEndpointResourceId)"
		Write-LogInfo "CurrentStorageAccount  : $($azureConfig.Subscription.ARMStorageAccount)"

		Write-LogInfo "------------------------------------------------------------------"

		Write-LogInfo "Setting global variables"
		$this.SetGlobalVariables()
	}

	[void] SetGlobalVariables() {
		([TestController]$this).SetGlobalVariables()

		if (!$global:AllTestVMSizes) {
			Set-Variable -Name AllTestVMSizes -Value @{} -Option ReadOnly -Scope Global
		}
	}

	[void] PrepareSetupTypeToTestCases([hashtable]$SetupTypeToTestCases, [System.Collections.ArrayList]$AllTests) {
		if (!$this.TestIdInParallel) {
			# Inject Networking=SRIOV/Synthetic, DiskType=Managed, OverrideVMSize to test case data
			if (("sriov", "synthetic") -contains $this.CustomParams["Networking"]) {
				Add-SetupConfig -AllTests $AllTests -ConfigName "Networking" -ConfigValue $this.CustomParams["Networking"] -Force $this.ForceCustom
			}
			if (("managed", "unmanaged") -contains $this.CustomParams["DiskType"]) {
				Add-SetupConfig -AllTests $AllTests -ConfigName "DiskType" -ConfigValue $this.CustomParams["DiskType"] -Force $this.ForceCustom
			}
			if (("Specialized", "Generalized") -contains $this.CustomParams["ImageType"]) {
				Add-SetupConfig -AllTests $AllTests -ConfigName "ImageType" -ConfigValue $this.CustomParams["ImageType"] -Force $this.ForceCustom
			}
			if (("Windows", "Linux") -contains $this.CustomParams["OSType"]) {
				Add-SetupConfig -AllTests $AllTests -ConfigName "OSType" -ConfigValue $this.CustomParams["OSType"] -Force $this.ForceCustom
			}
			if ($this.CustomParams.TiPSessionId -and $this.CustomParams.TiPCluster -and $this.CustomParams.PlatformFaultDomainCount -and $this.CustomParams.PlatformUpdateDomainCount) {
				Add-SetupConfig -AllTests $AllTests -ConfigName "TiPSessionId" -ConfigValue $this.CustomParams.TiPSessionId -Force $true
				Add-SetupConfig -AllTests $AllTests -ConfigName "TiPCluster" -ConfigValue $this.CustomParams.TiPCluster -Force $true
				Add-SetupConfig -AllTests $AllTests -ConfigName "PlatformFaultDomainCount" -ConfigValue $this.CustomParams.PlatformFaultDomainCount -Force $true
				Add-SetupConfig -AllTests $AllTests -ConfigName "PlatformUpdateDomainCount" -ConfigValue $this.CustomParams.PlatformUpdateDomainCount -Force $true
			}
			else {
				Add-SetupConfig -AllTests $AllTests -ConfigName "PlatformFaultDomainCount" -ConfigValue $this.CustomParams.PlatformFaultDomainCount -Force $this.ForceCustom
				Add-SetupConfig -AllTests $AllTests -ConfigName "PlatformUpdateDomainCount" -ConfigValue $this.CustomParams.PlatformUpdateDomainCount -Force $this.ForceCustom
			}

			# Multiple TestLocations (parameter '-TestLocation' with value like 'eastus,westus') means to deploy from different Regions,
			# so spliting with default Splitby (','), and apply multi single ConfigValues to $AllTests one by one.
			Add-SetupConfig -AllTests $AllTests -ConfigName "TestLocation" -ConfigValue $this.CustomParams["TestLocation"] -Force $this.ForceCustom
			if ($this.TestIterations -gt 1) {
				$testIterationsParamValue = @(1..$this.TestIterations) -join ','
				Add-SetupConfig -AllTests $AllTests -ConfigName "TestIteration" -ConfigValue $testIterationsParamValue -Force $this.ForceCustom
			}
			Add-SetupConfig -AllTests $AllTests -ConfigName "OverrideVMSize" -ConfigValue $this.CustomParams["OverrideVMSize"] -Force $this.ForceCustom
			Add-SetupConfig -AllTests $AllTests -ConfigName "OsVHD" -ConfigValue $this.CustomParams["OsVHD"] -Force $this.ForceCustom
			# 'OsVHD' should not coexist with 'ARMImageName', when OsVHD exist, take OsVHD as prioritized than ARMImageName
			if (!$this.CustomParams["OsVHD"]) {
				Add-SetupConfig -AllTests $AllTests -ConfigName "ARMImageName" -ConfigValue $this.CustomParams["ARMImageName"] -DefaultConfigValue $this.GlobalConfig.Global.Azure.DefaultARMImageName -Force $this.ForceCustom
			}
			else {
				# Only when 'OsVHD' exist from parameters, then we should Add-SetupConfig for 'VMGeneration',
				#   because HyperVGeneration property for Azure Gallery Image is only decided by the 'ARMImageName' (Publisher, Provider, SKU, Version),
				#   and from ARM template constraint, there's no Generation property to be applied when deploying with Gallery image with (Publisher, Provider, SKU, Version)
				Add-SetupConfig -AllTests $AllTests -ConfigName "VMGeneration" -ConfigValue $this.CustomParams["VMGeneration"] -DefaultConfigValue "1" -Force $this.ForceCustom
			}
			if ($this.CustomParams["StorageAccountType"]) {
				Add-SetupConfig -AllTests $AllTests -ConfigName "StorageAccountType" -ConfigValue $this.CustomParams["StorageAccountType"] -Force $this.ForceCustom
			}
			if ($this.CustomParams["SetupType"]) {
				Add-SetupConfig -AllTests $AllTests -ConfigName "SetupType" -ConfigValue $this.CustomParams["SetupType"] -Force $this.ForceCustom
			}
			if ($this.CustomParams["SecureBoot"] -imatch "^(true|false)$") {
				Add-SetupConfig -AllTests $AllTests -ConfigName "SecureBoot" -ConfigValue $this.CustomParams["SecureBoot"].ToLower() -Force $this.ForceCustom
			}
			if ($this.CustomParams["vTPM"] -imatch "^(true|false)$") {
				Add-SetupConfig -AllTests $AllTests -ConfigName "vTPM" -ConfigValue $this.CustomParams["vTPM"].ToLower() -Force $this.ForceCustom
			}
		}

		foreach ($test in $AllTests) {
			# Put test case to hashtable, per setupType,OverrideVMSize,networking,diskType,osDiskType,switchName
			$key = Get-TestSetupKey -TestData $test
			if ($test.SetupConfig.SetupType) {
				if ($SetupTypeToTestCases.ContainsKey($key)) {
					$SetupTypeToTestCases[$key] += $test
				}
				else {
					$SetupTypeToTestCases.Add($key, @($test))
				}
			}
		}

		$AllTests.SetupConfig.OverrideVMSize | Sort-Object -Unique | Foreach-Object {
			if (!($global:AllTestVMSizes.$_)) { $global:AllTestVMSizes["$_"] = @{} }
		}
		$allTestSetupTypes = $AllTests.SetupConfig.SetupType | Sort-Object -Unique
		$SetupTypeXMLs = Get-ChildItem -Path "$PSScriptRoot\..\XML\VMConfigurations\*.xml"
		foreach ($file in $SetupTypeXMLs.FullName) {
			$setupXml = [xml]( Get-Content -Path $file)
			foreach ($SetupType in $setupXml.TestSetup.ChildNodes) {
				if ($allTestSetupTypes -contains $SetupType.LocalName) {
					$vmSizes = $SetupType.ResourceGroup.VirtualMachine.InstanceSize | Sort-Object -Unique
					$vmSizes | ForEach-Object {
						if (!$global:AllTestVMSizes."$_") {
							$global:AllTestVMSizes["$_"] = @{}
						}
					}
				}
			}
		}
		$this.TotalCaseNum = ([System.Collections.ArrayList]$AllTests).Count
	}

	[void] LoadTestCases($WorkingDirectory, $CustomTestParameters) {
		([TestController]$this).LoadTestCases($WorkingDirectory, $CustomTestParameters)
		if (!$this.RunInParallel) {
			Measure-SubscriptionCapabilities
		}
	}
}
