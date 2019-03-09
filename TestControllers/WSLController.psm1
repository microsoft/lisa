##############################################################################################
# WSLController.psm1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
	PS modules for LISAv2 test automation
	This module drives the test on Windows Subsystem of Linux

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
using Module "..\TestProviders\WSLProvider.psm1"

Class WSLController : TestController
{
	[string] $DestinationOsVhdPath

	WSLController() {
		$this.TestPlatform = "WSL"
		$this.TestProvider = New-Object -TypeName "WSLProvider"
	}

	[void] ParseAndValidateParameters([Hashtable]$ParamTable) {
		$this.DestinationOsVhdPath = $ParamTable["DestinationOsVhdPath"]

		$parameterErrors = ([TestController]$this).ParseAndValidateParameters($ParamTable)

		if (!$this.OsVHD ) {
			$parameterErrors += "-OsVHD <'Path-To-Distro.zip'> is required. It can be the URL of the distro, or the path to the distro file on the local host."
		}
		if ($parameterErrors.Count -gt 0) {
			$parameterErrors | ForEach-Object { Write-LogErr $_ }
			throw "Failed to validate the test parameters provided. Please fix above issues and retry."
		} else {
			Write-LogInfo "Test parameters for WSL have been validated successfully. Continue running the test."
		}
	}

	[void] PrepareTestEnvironment($XMLSecretFile) {
		([TestController]$this).PrepareTestEnvironment($XMLSecretFile)
		$wslConfig = $this.GlobalConfig.Global.WSL
		$secrets = $this.XmlSecrets.secrets
		if ($this.XMLSecrets) {
			$wslConfig.TestCredentials.LinuxUsername = $secrets.linuxTestUsername
			$wslConfig.TestCredentials.LinuxPassword = $secrets.linuxTestPassword
			$wslConfig.ResultsDatabase.server = $secrets.DatabaseServer
			$wslConfig.ResultsDatabase.user = $secrets.DatabaseUser
			$wslConfig.ResultsDatabase.password = $secrets.DatabasePassword
			$wslConfig.ResultsDatabase.dbname = $secrets.DatabaseName
		}
		$this.VmUsername = $wslConfig.TestCredentials.LinuxUsername
		$this.VmPassword = $wslConfig.TestCredentials.LinuxPassword
		if ( $this.DestinationOsVHDPath )
		{
			for( $index=0 ; $index -lt $wslConfig.Hosts.ChildNodes.Count ; $index++ ) {
				$wslConfig.Hosts.ChildNodes[$index].DestinationOsVHDPath = $this.DestinationOsVHDPath
			}
		}
		if ($this.TestLocation)
		{
			$Locations = $this.TestLocation.split(',')
			$index = 0
			foreach($Location in $Locations)
			{
				$wslConfig.Hosts.ChildNodes[$index].ServerName = $Location
				Write-LogInfo "Set GlobalConfiguration.Global.WSL.Hosts.ChildNodes[$($index)].ServerName to $Location"
				$index++
			}
		}
		else
		{
			$this.TestLocation = $wslConfig.Hosts.ChildNodes[0].ServerName
			Write-LogInfo "Set Test Location to GlobalConfiguration.Global.WSL.Hosts.ChildNodes[0].ServerName"
		}

		if( $this.ResultDBTable )
		{
			$wslConfig.ResultsDatabase.dbtable = ($this.ResultDBTable).Trim()
			Write-LogInfo "ResultDBTable : $this.ResultDBTable added to $($this.GlobalConfigurationFilePath)"
		}
		if( $this.ResultDBTestTag )
		{
			$wslConfig.ResultsDatabase.testTag = ($this.ResultDBTestTag).Trim()
			Write-LogInfo "ResultDBTestTag: $this.ResultDBTestTag added to $($this.GlobalConfigurationFilePath)"
		}

		$this.GlobalConfig.Save($this.GlobalConfigurationFilePath )
		Write-LogInfo "Updated $($this.GlobalConfigurationFilePath) file."

		Write-LogInfo "------------------------------------------------------------------"
		$serverCount = $this.TestLocation.split(',').Count
		for( $index=0 ; $index -lt $serverCount ; $index++ ) {
			$server = $wslConfig.Hosts.ChildNodes[$($index)].ServerName
			Get-VM -ComputerName $server | Out-Null
			if ($?) {
				$state = Invoke-Command -ComputerName $server -ScriptBlock {
					$feature = Get-WindowsOptionalFeature -Online | Where-Object FeatureName -imatch Microsoft-Windows-Subsystem-Linux
					if (!$feature) {
						return 'Disabled'
					} else {
						return $feature.State
					}
				}
				if ($state.Value -ne 'Enabled') {
					Throw "Microsoft-Windows-Subsystem-Linux feature is not enabled on Windows Server $server"
				}
			} else {
				Throw "Unable to access Windows Server $server"
			}

			Write-LogInfo "WSL Host                 : $($wslConfig.Hosts.ChildNodes[$($index)].ServerName)"
			Write-LogInfo "Source Distro            : $($this.OsVHD)"
			Write-LogInfo "Destination Distro Path  : $($wslConfig.Hosts.ChildNodes[$($index)].DestinationOsVHDPath)"
		}
		Write-LogInfo "------------------------------------------------------------------"

		Write-LogInfo "Setting global variables"
		$this.SetGlobalVariables()
		$this.TestProvider.Initialize($this.TestLocation)
	}

	[void] SetGlobalVariables() {
		([TestController]$this).SetGlobalVariables()

		Set-Variable -Name VMGeneration -Value $this.TestProvider.VMGeneration -Scope Global
	}

	[void] PrepareTestImage() {
		$this.TestProvider.DistroFilePath = @()
		$serverCount = $this.TestLocation.Split(',').Count
		for ($index=0; $index -lt $serverCount; $index++){
			$serverName = $this.GlobalConfig.Global.WSL.Hosts.ChildNodes[$index].ServerName
			$dstPath = $this.GlobalConfig.Global.WSL.Hosts.ChildNodes[$index].DestinationOsVHDPath
			$wslDistro = $this.OsVHD
			$dstFile = Join-Path $dstPath "$($this.RGIdentifier)-$($global:TestID).zip"

			Write-LogInfo "Start to copy $wslDistro to $dstPath on $serverName ..."
			$session = New-PSSession -ComputerName $serverName
			Invoke-Command -Session $session -ScriptBlock {
				param($dstPath)
				$target = ( [io.fileinfo] $dstPath ).DirectoryName
				if( -not (Test-Path $target) ) {
					New-Item -Path $target -ItemType "directory" -Force
				}
			} -ArgumentList $dstPath

			if ($wslDistro.Trim().StartsWith("http")) {
				Invoke-Command -Session $session -ScriptBlock {
					param($srcPath, $dstFile)
					Import-Module BitsTransfer
					$displayName = "MyBitsTransfer" + (Get-Date)
					Start-BitsTransfer -Source $srcPath -Destination $dstFile -DisplayName $displayName -Asynchronous
					$btJob = Get-BitsTransfer $displayName
					do{
						if($btJob.JobState -like "*Error*") {
							Remove-BitsTransfer $btJob
							throw "Error connecting $srcPath to download."
						}
						Start-Sleep -s 5
					} while ($btJob.BytesTransferred -lt $btJob.BytesTotal)
					Complete-BitsTransfer $btJob
				} -ArgumentList $wslDistro, $dstFile
			}
			else {
				Copy-Item -Path $wslDistro -Destination $dstFile -ToSession $session
			}
			Write-LogInfo "Copy $wslDistro to $dstPath on $serverName done."
			$this.TestProvider.DistroFilePath += $dstFile
		}
	}
}