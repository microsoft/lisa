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
		$this.DestinationOsVhdPath = $ParamTable["DestinationOsVhdPath"]
		$vmGeneration = [string]($ParamTable["VMGeneration"])
		$this.TestProvider.VMGeneration = $vmGeneration

		$parameterErrors = ([TestController]$this).ParseAndValidateParameters($ParamTable)

		if (!($this.TestProvider.VMGeneration)) {
			# Set VM Generation default value to 1, if not specified.
			Write-LogInfo "-VMGeneration not specified. Using default VMGeneration = 1"
			$this.TestProvider.VMGeneration = 1
		} else {
			$supportedVMGenerations = @("1","2")
			if ($supportedVMGenerations.contains($vmGeneration)) {
				if ($vmGeneration -eq "2" -and $this.OsVHD `
							-and [System.IO.Path]::GetExtension($this.OsVHD) -ne ".vhdx") {
					$parameterErrors += "-VMGeneration 2 requires .vhdx files."
				}
			} else {
				$parameterErrors += "-VMGeneration $vmGeneration is not yet supported."
			}
		}

		if (!$this.OsVHD ) {
			$parameterErrors += "-OsVHD <'VHD_Name.vhd'> is required."
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
					Write-LogInfo "Set GlobalConfiguration.Global.HyperV.Hosts.ChildNodes[$($index)].ServerName to $Location"
				} else {
					Write-LogErr "Did you use -TestLocation XXXXXXX?"
					Write-LogErr "In HyperV mode, -TestLocation can be used to Override HyperV server mentioned in GlobalConfiguration XML file."
					Throw "Unable to access HyperV server - '$($Location)'"
				}
				$index++
			}
		} else {
			$this.TestLocation = $hyperVConfig.Hosts.ChildNodes[0].ServerName
			Write-LogInfo "Set Test Location to GlobalConfiguration.Global.HyperV.Hosts.ChildNodes[0].ServerName"
			Get-VM -ComputerName $this.TestLocation | Out-Null
		}

		if( $this.ResultDBTable ) {
			$hyperVConfig.ResultsDatabase.dbtable = ($this.ResultDBTable).Trim()
			Write-LogInfo "ResultDBTable : $this.ResultDBTable added to $($this.GlobalConfigurationFilePath)"
		}
		if( $this.ResultDBTestTag ) {
			$hyperVConfig.ResultsDatabase.testTag = ($this.ResultDBTestTag).Trim()
			Write-LogInfo "ResultDBTestTag: $this.ResultDBTestTag added to $($this.GlobalConfigurationFilePath)"
		}

		$this.GlobalConfig.Save($this.GlobalConfigurationFilePath )
		Write-LogInfo "Updated $($this.GlobalConfigurationFilePath) file."

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

		Set-Variable -Name VMGeneration -Value $this.TestProvider.VMGeneration -Scope Global
	}
}