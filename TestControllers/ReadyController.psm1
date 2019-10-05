##############################################################################################
# ReadyController.psm1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
	PS modules for LISAv2 test automation
	This module drives the test on given Linux machines

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
using Module "..\TestProviders\ReadyProvider.psm1"

Class ReadyController : TestController
{
	[string] $DestinationOsVhdPath

	ReadyController() {
		$this.TestProvider = New-Object -TypeName "ReadyProvider"
		$this.TestPlatform = "Any"
	}

	[void] ParseAndValidateParameters([Hashtable]$ParamTable) {
		$parameterErrors = ([TestController]$this).ParseAndValidateParameters($ParamTable)

		if ( $ParamTable.RGIdentifier ) {
			if ( ($ParamTable.RGIdentifier.Contains(" ")) `
			-or !($ParamTable.RGIdentifier.Contains(":")) `
			-or !($ParamTable.RGIdentifier.Contains(".")) ) {
				$parameterErrors += "-TestLocation format error (expected format: 1.1.1.1:22;2.2.2.2:22)."
			}
		}

		if ($parameterErrors.Count -gt 0) {
			$parameterErrors | ForEach-Object { Write-LogErr $_ }
			throw "Failed to validate the test parameters provided. Please fix above issues and retry."
		} else {
			Write-LogInfo "Test parameters for the Ready environment have been validated successfully. Continue running the test."
		}
	}

	[void] PrepareTestEnvironment($XMLSecretFile) {
		([TestController]$this).PrepareTestEnvironment($XMLSecretFile)
		$readyVConfig = $this.GlobalConfig.Global.Ready
		$secrets = $this.XmlSecrets.secrets
		if ($this.XMLSecrets) {
			$readyVConfig.TestCredentials.LinuxUsername = $secrets.linuxTestUsername
			$readyVConfig.TestCredentials.LinuxPassword = $secrets.linuxTestPassword
			$readyVConfig.ResultsDatabase.server = $secrets.DatabaseServer
			$readyVConfig.ResultsDatabase.user = $secrets.DatabaseUser
			$readyVConfig.ResultsDatabase.password = $secrets.DatabasePassword
			$readyVConfig.ResultsDatabase.dbname = $secrets.DatabaseName
		}
		$this.VmUsername = $readyVConfig.TestCredentials.LinuxUsername
		$this.VmPassword = $readyVConfig.TestCredentials.LinuxPassword
		
		if( $this.ResultDBTable ) {
			$readyVConfig.ResultsDatabase.dbtable = ($this.ResultDBTable).Trim()
			Write-LogInfo "ResultDBTable : $this.ResultDBTable added to GlobalConfig.Global.Ready.ResultsDatabase.dbtable"
		}
		if( $this.ResultDBTestTag ) {
			$readyVConfig.ResultsDatabase.testTag = ($this.ResultDBTestTag).Trim()
			Write-LogInfo "ResultDBTestTag: $this.ResultDBTestTag added to GlobalConfig.Global.HReadyyperV.ResultsDatabase.testTag"
		}

		Write-LogInfo "------------------------------------------------------------------"
		$serverCount = $this.RGIdentifier.split(';').Count
		for( $index=0 ; $index -lt $serverCount ; $index++ ) {
			Write-LogInfo "Target Machines   : $($this.VmUsername) @ $($this.RGIdentifier.split(';')[$index])"
		}
		Write-LogInfo "------------------------------------------------------------------"

		Write-LogInfo "Setting global variables"
		$this.SetGlobalVariables()
	}

	[void] SetGlobalVariables() {
		([TestController]$this).SetGlobalVariables()
	}
}