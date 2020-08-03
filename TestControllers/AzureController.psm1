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

Class AzureController : TestController
{
	[string] $ARMImageName
	[string] $StorageAccount

	AzureController() {
		$this.TestProvider = New-Object -TypeName "AzureProvider"
		$this.TestPlatform = "Azure"
	}

	[void] ParseAndValidateParameters([Hashtable]$ParamTable) {
		$parameterErrors = ([TestController]$this).ParseAndValidateParameters($ParamTable)

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
			if ($ArmImagesToBeUsed | Where-Object {$_.Split(" ").Count -ne 4}) {
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
		} else {
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
			if ($this.UseExistingRG) {
				$existingRG = Get-AzResourceGroup -Name $this.RGIdentifier -ErrorAction SilentlyContinue
				if (!$existingRG) {
					if ($this.CustomParams["TipSessionId"] -or $this.CustomParams["TipCluster"]) {
						# Create resource group for TiP if resource group does not exist, as '$this.TestLocation' always available after ParseAndValidateParameters()
						Write-LogInfo "Resource group '$($this.RGIdentifier)' does not exist, create it for TiP"
						Create-ResourceGroup -RGName $this.RGIdentifier -location $this.TestLocation | Out-Null
					}
					else {
						throw "'-RGIdentifier' must be an existing Resource Group Name when Run-LISAv2 with '-UseExistingRG' on Azure Platform"
					}
				}
				else {
					$allExistingResources = Get-AzResource -ResourceGroupName $this.RGIdentifier
					if (($this.CustomParams["TipSessionId"] -or $this.CustomParams["TipCluster"]) -and $allExistingResources) {
						Write-LogInfo "Try to cleanup all resources from Resource Group '$($this.RGIdentifier)' for testing with TiP..."
						$isResoruceCleanedExceptAvailabilitySet = Delete-ResourceGroup -RGName $this.RGIdentifier -UseExistingRG $this.UseExistingRG
						if ($isResoruceCleanedExceptAvailabilitySet) {
							$allExistingResources | Where-Object { $_.ResourceType -imatch "availabilitySets" } | ForEach-Object {
								if (Remove-AzResource -ResourceGroupName $this.RGIdentifier -ResourceName $_.Name -ResourceType $_.ResourceType -Force) {
									Write-LogInfo "`tCleanup resource group '$($this.RGIdentifier)' successfully."
								}
								else {
									throw "Failed to cleanup resources from '$($this.RGIdentifier)', please remove all resources manually."
								}
							}
						}
						else {
							throw "Failed to cleanup resources from '$($this.RGIdentifier)', please remove all resources manually."
						}
					}
					elseif (!$allExistingResources) {
						Write-LogInfo "Resource group '$($this.RGIdentifier)' is empty, new resources will be deployed"
					}
				}
			}
		}
		# Invoke Base.PrepareTestEnvironment($XMLSecretFile)
		([TestController]$this).PrepareTestEnvironment($XMLSecretFile)
		$RegionAndStorageMapFile = "$PSScriptRoot\..\XML\RegionAndStorageAccounts.xml"
		if (Test-Path $RegionAndStorageMapFile) {
			$RegionAndStorageMap = [xml](Get-Content $RegionAndStorageMapFile)
		} else {
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
		if ($this.TestLocation) {
			if ( $this.StorageAccount -imatch "^ExistingStorage_Standard" ) {
				$azureConfig.Subscription.ARMStorageAccount = $RegionAndStorageMap.AllRegions.$($this.TestLocation).StandardStorage
				Write-LogInfo "Selecting existing standard storage account in $($this.TestLocation) - $($azureConfig.Subscription.ARMStorageAccount)"
			}
			elseif ( $this.StorageAccount -imatch "^ExistingStorage_Premium" ) {
				$azureConfig.Subscription.ARMStorageAccount = $RegionAndStorageMap.AllRegions.$($this.TestLocation).PremiumStorage
				Write-LogInfo "Selecting existing premium storage account in $($this.TestLocation) - $($azureConfig.Subscription.ARMStorageAccount)"
			}
			elseif ($this.StorageAccount -and ($this.StorageAccount -inotmatch "^Auto_Complete_RG=.+")) {
				# $this.StorageAccount should be some exact name of Storage Account
				$sc = Get-AzStorageAccount | Where-Object {$_.StorageAccountName -eq $this.StorageAccount}
				if (!$sc) {
					Throw "Provided storage account $($this.StorageAccount) does not exist, abort testing."
				}
				if($sc.Location -ne $this.TestLocation) {
					Throw "Provided storage account $($this.StorageAccount) location $($sc.Location) is different from test location $($this.TestLocation), abort testing."
				}
				$azureConfig.Subscription.ARMStorageAccount = $this.StorageAccount.Trim()
				Write-LogInfo "Selecting custom storage account : $($azureConfig.Subscription.ARMStorageAccount) as per your test region."
			}
			else { # else means $this.StorageAccount is empty, or $this.StorageAccount is like 'Auto_Complete_RG=Xxx'
				$azureConfig.Subscription.ARMStorageAccount = $RegionAndStorageMap.AllRegions.$($this.TestLocation).StandardStorage
				Write-LogInfo "Auto selecting storage account : $($azureConfig.Subscription.ARMStorageAccount) as per your test region."
			}
		}
		else {
			# Parameter '-TestLocation' is null, to avoid null exception, auto selecting the first standard storage account
			# per storage accounts from .\XML\RegionAndStorageAccounts.xml (or copied from secrets xml file)
			# this will be updated after auto selected the proper TestLocation/Region for each test on Azure platform
			$azureConfig.Subscription.ARMStorageAccount = $RegionAndStorageMap.AllRegions.ChildNodes[0].StandardStorage
		}

		if ($this.ResultDBTable) {
			$azureConfig.ResultsDatabase.dbtable = ($this.ResultDBTable).Trim()
			Write-LogInfo "ResultDBTable : $($this.ResultDBTable) added to GlobalConfig.Global.HyperV.ResultsDatabase.dbtable"
		}
		if ($this.ResultDBTestTag) {
			$azureConfig.ResultsDatabase.testTag = ($this.ResultDBTestTag).Trim()
			Write-LogInfo "ResultDBTestTag: $($this.ResultDBTestTag) added to GlobalConfig.Global.HyperV.ResultsDatabase.testTag"
		}

		Write-LogInfo "------------------------------------------------------------------"

		$SelectedSubscription = Set-AzContext -SubscriptionId $azureConfig.Subscription.SubscriptionID
		$subIDSplitted = ($SelectedSubscription.Subscription.SubscriptionId).Split("-")
		Write-LogInfo "SubscriptionName       : $($SelectedSubscription.Subscription.Name)"
		Write-LogInfo "SubscriptionId         : $($subIDSplitted[0])-xxxx-xxxx-xxxx-$($subIDSplitted[4])"
		Write-LogInfo "User                   : $($SelectedSubscription.Account.Id)"
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

	[void] PrepareTestImage() {
		#If Base OS VHD is present in another storage account, then copy to test storage account first.
		if ($this.OsVHD) {
			$ARMStorageAccount = $this.GlobalConfig.Global.Azure.Subscription.ARMStorageAccount
			if ($ARMStorageAccount -imatch "^NewStorage_") {
				Throw "LISAv2 only supports copying VHDs to existing storage account.`n
				Please use <ARMStorageAccount>Auto_Complete_RG=XXXResourceGroupName<ARMStorageAccount> or `n
				<ARMStorageAccount>Existing_Storage_Standard<ARMStorageAccount> `n
				<ARMStorageAccount>Existing_Storage_Premium<ARMStorageAccount>"
			}
			$useSASURL = $false
			if (($this.OsVHD -imatch 'sp=') -and ($this.OsVHD -imatch 'sig=')) {
				$useSASURL = $true
			}

			if (!$useSASURL -and ($this.OsVHD -inotmatch "/")) {
				$this.OsVHD = 'http://{0}.blob.core.windows.net/vhds/{1}' -f $ARMStorageAccount, $this.OsVHD
			}

			#Check if the test storage account is same as VHD's original storage account.
			$givenVHDStorageAccount = $this.OsVHD.Replace("https://","").Replace("http://","").Split(".")[0]
			$sourceContainer =  $this.OsVHD.Split("/")[$this.OsVHD.Split("/").Count - 2]
			$vhdName = $this.OsVHD.Split("?")[0].split('/')[-1]

			if ($givenVHDStorageAccount -ne $ARMStorageAccount) {
				Write-LogInfo "Your test VHD is not in target storage account ($ARMStorageAccount)."
				Write-LogInfo "Your VHD will be copied to $ARMStorageAccount now."

				#Copy the VHD to current storage account.
				#Check if the OsVHD is a SasUrl
				if ($useSASURL) {
					$copyStatus = Copy-VHDToAnotherStorageAccount -SasUrl $this.OsVHD -destinationStorageAccount $ARMStorageAccount -destinationStorageContainer "vhds" -vhdName $vhdName
					$this.OsVHD = 'http://{0}.blob.core.windows.net/vhds/{1}' -f $ARMStorageAccount, $vhdName
				} else {
					$copyStatus = Copy-VHDToAnotherStorageAccount -sourceStorageAccount $givenVHDStorageAccount -sourceStorageContainer $sourceContainer -destinationStorageAccount $ARMStorageAccount -destinationStorageContainer "vhds" -vhdName $vhdName
				}
				if (!$copyStatus) {
					Throw "Failed to copy the VHD to $ARMStorageAccount"
				}
			} else {
				$sc = Get-AzStorageAccount | Where-Object {$_.StorageAccountName -eq $ARMStorageAccount}
				$storageKey = (Get-AzStorageAccountKey -ResourceGroupName $sc.ResourceGroupName -Name $ARMStorageAccount)[0].Value
				$context = New-AzStorageContext -StorageAccountName $ARMStorageAccount -StorageAccountKey $storageKey
				$blob = Get-AzStorageBlob -Blob $vhdName -Container $sourceContainer -Context $context -ErrorAction Ignore
				if (!$blob) {
					Throw "Provided VHD not existed, abort testing."
				}
			}
			Set-Variable -Name BaseOsVHD -Value $this.OsVHD -Scope Global
			Write-LogInfo "New Base VHD name - $($this.OsVHD)"
		}
	}

	[void] PrepareSetupTypeToTestCases([hashtable]$SetupTypeToTestCases, [System.Collections.ArrayList]$AllTests) {
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

		foreach ($test in $AllTests) {
			# Put test case to hashtable, per setupType,OverrideVMSize,networking,diskType,osDiskType,switchName
			$key = "$($test.SetupConfig.SetupType),$($test.SetupConfig.OverrideVMSize),$($test.SetupConfig.Networking),$($test.SetupConfig.DiskType)," +
				"$($test.SetupConfig.OSDiskType),$($test.SetupConfig.SwitchName),$($test.SetupConfig.ImageType)," +
				"$($test.SetupConfig.OSType),$($test.SetupConfig.StorageAccountType),$($test.SetupConfig.TestLocation)," +
				"$($test.SetupConfig.ARMImageName),$($test.SetupConfig.OsVHD),$($test.SetupConfig.VMGeneration)"
			if ($test.SetupConfig.SetupType) {
				if ($SetupTypeToTestCases.ContainsKey($key)) {
					$SetupTypeToTestCases[$key] += $test
				} else {
					$SetupTypeToTestCases.Add($key, @($test))
				}
			}
		}

		$AllTests.SetupConfig.OverrideVMSize | Sort-Object -Unique | Foreach-Object {
			if (!($global:AllTestVMSizes.$_)) { $global:AllTestVMSizes["$_"] = @{} }
		}
		$this.TotalCaseNum = ([System.Collections.ArrayList]$AllTests).Count
	}

	[void] LoadTestCases($WorkingDirectory, $CustomTestParameters) {
		([TestController]$this).LoadTestCases($WorkingDirectory, $CustomTestParameters)

		$SetupTypeXMLs = Get-ChildItem -Path "$WorkingDirectory\XML\VMConfigurations\*.xml"
		foreach ($file in $SetupTypeXMLs.FullName) {
			$setupXml = [xml]( Get-Content -Path $file)
			foreach ($SetupType in $setupXml.TestSetup.ChildNodes) {
				$vmSizes = $SetupType.ResourceGroup.VirtualMachine.InstanceSize | Sort-Object -Unique
				$vmSizes | ForEach-Object {
					if (!$global:AllTestVMSizes."$_") { $global:AllTestVMSizes["$_"] = @{} }
				}
			}
		}

		Measure-SubscriptionCapabilities
	}
}
