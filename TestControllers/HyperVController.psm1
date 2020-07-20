##############################################################################################
# HyperVController.psm1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
	PS modules for LISAv2 test automation
	This module drives the test on HyperV

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
using Module "..\TestProviders\HyperVProvider.psm1"

Class HyperVController : TestController
{
	[string] $DestinationOsVhdPath

	HyperVController() {
		$this.TestProvider = New-Object -TypeName "HyperVProvider"
		$this.TestPlatform = "HyperV"
	}

	[void] ParseAndValidateParameters([Hashtable]$ParamTable) {
		$parameterErrors = ([TestController]$this).ParseAndValidateParameters($ParamTable)

		$this.DestinationOsVhdPath = $ParamTable["DestinationOsVhdPath"]

		# If VMGeneration is null/empty, set the default value '1', so as to make LISAv2 backward compatible
		if (!$this.VMGeneration) {
			Write-Loginfo "'-VMGeneration' is not set for HyperV platform, set the default value '1'"
			$this.VMGeneration = "1"
			$this.SyncEquivalentCustomParameters("VMGeneration", $this.VMGeneration)
		}
		if (("1", "2") -contains $this.VMGeneration) {
			if ($this.VMGeneration -eq "2" -and $this.OsVHD `
						-and [System.IO.Path]::GetExtension($this.OsVHD) -ne ".vhdx") {
				$parameterErrors += "-VMGeneration 2 requires .vhdx files."
			}
		}
		else {
			$parameterErrors += "-VMGeneration '$($this.VMGeneration)' is empty, or not yet supported."
		}

		if (!$this.OsVHD ) {
			$parameterErrors += "-OsVHD <'VHD_Name.vhd'> is required."
		}
		if (!$this.RGIdentifier) {
			$parameterErrors += "-RGIdentifier is not set"
		}
		if ($parameterErrors.Count -gt 0) {
			$parameterErrors | ForEach-Object { Write-LogErr $_ }
			throw "Failed to validate the test parameters provided. Please fix above issues and retry."
		} else {
			Write-LogInfo "Test parameters for HyperV have been validated successfully. Continue running the test."
		}
	}

	[void] PrepareTestEnvironment($XMLSecretFile) {
		([TestController]$this).PrepareTestEnvironment($XMLSecretFile)
		$hyperVConfig = $this.GlobalConfig.Global.HyperV
		$secrets = $this.XmlSecrets.secrets
		if ($this.XMLSecrets) {
			$hyperVConfig.TestCredentials.LinuxUsername = $secrets.linuxTestUsername
			$hyperVConfig.TestCredentials.LinuxPassword = $secrets.linuxTestPassword
			$hyperVConfig.ResultsDatabase.server = $secrets.DatabaseServer
			$hyperVConfig.ResultsDatabase.user = $secrets.DatabaseUser
			$hyperVConfig.ResultsDatabase.password = $secrets.DatabasePassword
			$hyperVConfig.ResultsDatabase.dbname = $secrets.DatabaseName
		}
		$this.VmUsername = $hyperVConfig.TestCredentials.LinuxUsername
		$this.VmPassword = $hyperVConfig.TestCredentials.LinuxPassword
		if ( $this.DestinationOsVHDPath ) {
			for( $index=0 ; $index -lt $hyperVConfig.Hosts.ChildNodes.Count ; $index++ ) {
				$hyperVConfig.Hosts.ChildNodes[$index].DestinationOsVHDPath = $this.DestinationOsVHDPath
			}
		}
		if ($this.TestLocation) {
			$Locations = $this.TestLocation.split(',')
			$index = 0
			foreach($Location in $Locations) {
				$hyperVConfig.Hosts.ChildNodes[$index].ServerName = $Location
				Get-VM -ComputerName $Location | Out-Null
				if ($?) {
					Write-LogInfo "Set GlobalConfig.Global.HyperV.Hosts.ChildNodes[$($index)].ServerName to $Location"
				} else {
					Write-LogErr "Did you use -TestLocation XXXXXXX?"
					Write-LogErr "In HyperV mode, -TestLocation can be used to Override HyperV server in GlobalConfig.Global.HyperV.Hosts.ChildNodes[$($index)].ServerName."
					Throw "Unable to access HyperV server - '$($Location)'"
				}
				$index++
			}
		} else {
			$this.TestLocation = $hyperVConfig.Hosts.ChildNodes[0].ServerName
			Write-LogInfo "Set Test Location to GlobalConfig.Global.HyperV.Hosts.ChildNodes[0].ServerName"
			Get-VM -ComputerName $this.TestLocation | Out-Null
		}

		if( $this.ResultDBTable ) {
			$hyperVConfig.ResultsDatabase.dbtable = ($this.ResultDBTable).Trim()
			Write-LogInfo "ResultDBTable : $this.ResultDBTable added to GlobalConfig.Global.HyperV.ResultsDatabase.dbtable"
		}
		if( $this.ResultDBTestTag ) {
			$hyperVConfig.ResultsDatabase.testTag = ($this.ResultDBTestTag).Trim()
			Write-LogInfo "ResultDBTestTag: $this.ResultDBTestTag added to GlobalConfig.Global.HyperV.ResultsDatabase.testTag"
		}

		Write-LogInfo "------------------------------------------------------------------"
		$serverCount = $this.TestLocation.split(',').Count
		for( $index=0 ; $index -lt $serverCount ; $index++ ) {
			Write-LogInfo "HyperV Host            : $($hyperVConfig.Hosts.ChildNodes[$($index)].ServerName)"
			Write-LogInfo "Destination VHD Path   : $($hyperVConfig.Hosts.ChildNodes[$($index)].DestinationOsVHDPath)"
		}
		Write-LogInfo "------------------------------------------------------------------"

		Write-LogInfo "Setting global variables"
		$this.SetGlobalVariables()
	}

	[void] SetGlobalVariables() {
		([TestController]$this).SetGlobalVariables()

		Set-Variable -Name VMIntegrationGuestService -Value "Guest Service Interface" -Scope Global
		Set-Variable -Name VMIntegrationKeyValuePairExchange -Value "Key-Value Pair Exchange" -Scope Global
	}

	[void] PrepareSetupTypeToTestCases([hashtable]$SetupTypeToTestCases, [object[]]$AllTests) {
		if (("sriov", "synthetic") -contains $this.CustomParams["Networking"]) {
			Add-SetupConfig -AllTests ([ref]$AllTests) -ConfigName "Networking" -ConfigValue $this.CustomParams["Networking"] -Force $this.ForceCustom
		}
		if (("managed", "unmanaged") -contains $this.CustomParams["DiskType"]) {
			Add-SetupConfig -AllTests ([ref]$AllTests) -ConfigName "DiskType" -ConfigValue $this.CustomParams["DiskType"] -Force $this.ForceCustom
		}
		if (("Specialized", "Generalized") -contains $this.CustomParams["ImageType"]) {
			Add-SetupConfig -AllTests ([ref]$AllTests) -ConfigName "ImageType" -ConfigValue $this.CustomParams["ImageType"] -Force $this.ForceCustom
		}
		if (("Windows", "Linux") -contains $this.CustomParams["OSType"]) {
			Add-SetupConfig -AllTests ([ref]$AllTests) -ConfigName "OSType" -ConfigValue $this.CustomParams["OSType"] -Force $this.ForceCustom
		}
		if (("1", "2") -contains $this.CustomParams["VMGeneration"]) {
			Add-SetupConfig -AllTests ([ref]$AllTests) -ConfigName "VMGeneration" -ConfigValue $this.CustomParams["VMGeneration"] -Force $this.ForceCustom
		}
		if (@($this.CustomParams["RGIdentifier"].Split(",")).Count -eq 1) {
			Add-SetupConfig -AllTests ([ref]$AllTests) -ConfigName "RGIdentifier" -ConfigValue $this.CustomParams["RGIdentifier"] -Force $this.ForceCustom
		}
		else {
			Write-LogErr "'RGIdentifier' could only be applied with multiple values, must not contain ',' in RGIdentifier value"
		}
		# As Hyper-V do not need to separate TestLocations ('localhost,AnotherServerName') for one TestCase.
		# Instead, multiple TestLocations must always stick together for every test case.
		# So, use a fake SplitBy to avoid TestLocations been Splitted for different TestCases.
		Add-SetupConfig -AllTests ([ref]$AllTests) -ConfigName "TestLocation" -ConfigValue $this.CustomParams["TestLocation"] -SplitBy ';' -Force $this.ForceCustom
		if ($this.TestIterations -gt 1) {
			$testIterationsParamValue = @(1..$this.TestIterations) -join ','
			Add-SetupConfig -AllTests ([ref]$AllTests) -ConfigName "TestIteration" -ConfigValue $testIterationsParamValue -Force $this.ForceCustom
		}
		Add-SetupConfig -AllTests ([ref]$AllTests) -ConfigName "OverrideVMSize" -ConfigValue $this.CustomParams["OverrideVMSize"] -Force $this.ForceCustom
		Add-SetupConfig -AllTests ([ref]$AllTests) -ConfigName "OsVHD" -ConfigValue $this.CustomParams["OsVHD"] -Force $this.ForceCustom

		foreach ($test in $AllTests) {
			# Put test case to hashtable, per setupType,OverrideVMSize,networking,diskType,osDiskType,switchName
			$key = "$($test.SetupConfig.SetupType),$($test.SetupConfig.OverrideVMSize),$($test.SetupConfig.Networking),$($test.SetupConfig.DiskType)," +
				"$($test.SetupConfig.OSDiskType),$($test.SetupConfig.SwitchName),$($test.SetupConfig.ImageType)," +
				"$($test.SetupConfig.OSType),$($test.SetupConfig.StorageAccountType),$($test.SetupConfig.TestLocation)," +
				"$($test.SetupConfig.OsVHD),$($test.SetupConfig.VMGeneration)"
			if ($test.SetupConfig.SetupType) {
				if ($SetupTypeToTestCases.ContainsKey($key)) {
					$SetupTypeToTestCases[$key] += $test
				} else {
					$SetupTypeToTestCases.Add($key, @($test))
				}
			}
		}
		$this.TotalCaseNum = @($AllTests).Count
	}
}