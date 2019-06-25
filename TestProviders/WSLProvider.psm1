##############################################################################################
# WSLProvider.psm1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
	PS modules for LISAv2 test automation
	This module provides the test operations on Windows Subsystem of Linux

.PARAMETER
	<Parameters>

.INPUTS


.NOTES
	Creation Date:
	Purpose/Change:

.EXAMPLE


#>
###############################################################################################
using Module ".\TestProvider.psm1"

Class WSLProvider : TestProvider
{
	[Array] $DistroFilePath
	[hashtable] $SessionMap

	WSLProvider() {
		$this.DistroFilePath = @()
		$this.SessionMap = @{}
	}

	[void] Initialize([string]$TestLocation) {
		foreach ($server in $TestLocation.Split(',')) {
			$this.SessionMap.Add($server, (New-PSSession -ComputerName $server))
		}
	}

	[object] DeployVMs([xml] $GlobalConfig, [object] $SetupTypeData, [object] $TestCaseData, [string] $TestLocation, [string] $RGIdentifier, [bool] $UseExistingRG, [string] $ResourceCleanup) {
		$allVMData = @()
		$deploySuccess = $true
		try {
			Write-LogInfo "Current test setup: $($SetupTypeData.Name)"
			$hostIndex = 0
			$vmIndex = 0
			$testLocations = $TestLocation.Split(',')
			$curtime = ([string]((Get-Date).Ticks / 1000000)).Split(".")[0]
			foreach ($vmXml in $SetupTypeData.ResourceGroup.VirtualMachine) {
				if ($vmXml.DeployOnDifferentHyperVHost -eq "yes") {
					$hostIndex++
					if ($testLocations.Count -le $hostIndex) {
						Write-LogErr "Multiple servers should be specified with -TestLocation for setup $($SetupTypeData.Name)"
						$deploySuccess = $false
						break
					}
				}
				$distroFile = $this.DistroFilePath[$hostIndex]
				$server = $testLocations[$hostIndex]
				$dstPath = $GlobalConfig.Global.WSL.Hosts.ChildNodes[$hostIndex].DestinationOsVHDPath

				# Get the installed distros on the server
				$oldInstalledDistros = $this.GetInstalledWSLDistros($server)

				# Extract the distro package to target folder
				$dirName = "LISAv2-$($SetupTypeData.Name)-$RGIdentifier-$global:TestID-$curtime-role-$vmIndex"
				if ($vmXml.RoleName) {
					$dirName = "LISAv2-$($SetupTypeData.Name)-$RGIdentifier-$global:TestID-$curtime-$($vmXml.RoleName)"
				}
				$distroDir = Join-Path $dstPath $dirName
				Invoke-Command -Session $this.SessionMap[$server] -ScriptBlock ${Function:Extract-ZipFile} -ArgumentList $distroFile,$distroDir

				$distroCommand = Invoke-Command -Session $this.SessionMap[$server] -ScriptBlock {
					param ($distroDir)
					$file = Get-ChildItem -Path $distroDir -Filter *.exe | Select-Object -Last 1
					$launchDistroCommand = Join-Path $distroDir $file.Name
					return $launchDistroCommand
				} -ArgumentList $distroDir

				if (!$distroCommand.EndsWith("exe")) {
					Write-LogErr "Fail to find the exe file of WSL distro"
					$deploySuccess = $false
					break
				} else {
					Write-LogInfo "The distro launch command: $distroCommand"
				}

				Write-LogInfo "Installing the WSL distro with root"
				$job = Invoke-Command -ComputerName $server -AsJob -ScriptBlock {
					param ($command)
					& $command install --root
				} -ArgumentList $distroCommand
				Wait-Job -Job $job -Timeout 90

				Write-LogInfo "Adding user account $global:user, and configuring the SSH service"
				$publicPort = ($vmXml.EndPoints | Where-Object Name -eq SSH).PublicPort
				Write-LogInfo "Open port $publicPort on server $server"
				Invoke-Command -Session $this.SessionMap[$server] -ScriptBlock {
					param ($username, $password, $port)
					$encyptedPassword = & $launchDistroCommand run openssl passwd -crypt $password
					& $launchDistroCommand run useradd -m -p $encyptedPassword -s /bin/bash $username
					& $launchDistroCommand run usermod -aG sudo $username
					$sshConfigFile = Join-Path (Split-Path -Path $launchDistroCommand -Parent) "rootfs\etc\ssh\sshd_config"
					((Get-Content $sshConfigFile) -replace ".*PasswordAuthentication .*", "PasswordAuthentication yes") `
						-replace ".*Port .*", "Port $port" | Set-Content $sshConfigFile
					netsh advfirewall firewall add rule name="Open Port $port for LISAv2 run $global:TestID" dir=in action=allow protocol=TCP localport=$port
					& $launchDistroCommand run ssh-keygen -A
					& $launchDistroCommand run service ssh restart
				} -ArgumentList $global:user,$global:password,$publicPort

				$publicIp = Get-AndTestHostPublicIp -ComputerName $server
				$objNode = New-Object -TypeName PSObject
				Add-Member -InputObject $objNode -MemberType NoteProperty -Name WSLHost -Value $server -Force
				Add-Member -InputObject $objNode -MemberType NoteProperty -Name LaunchDistroCommand -Value $distroCommand -Force
				Add-Member -InputObject $objNode -MemberType NoteProperty -Name PublicIP -Value $publicIp -Force
				Add-Member -InputObject $objNode -MemberType NoteProperty -Name SSHPort -Value $publicPort -Force
				Add-Member -InputObject $objNode -MemberType NoteProperty -Name RoleName -Value $server.ToUpper() -Force

				$newInstalledDistros = $this.GetInstalledWSLDistros($server)
				$alreadyInstalled = $true
				foreach ($distro in $newInstalledDistros) {
					if ($oldInstalledDistros -notcontains $distro) {
						$alreadyInstalled = $false
						Add-Member -InputObject $objNode -MemberType NoteProperty -Name DistroName -Value $distro -Force
					}
				}
				# Only single same WSL distro can be installed on one host
				if ($alreadyInstalled) {
					Write-LogInfo "The WSL distro was already installed, the test will reuse the existing distro."
				}

				$allVMData += $objNode
				$vmIndex++
			}
		} catch {
			$deploySuccess = $false
			$ErrorMessage = $_.Exception.Message
			$ErrorLine = $_.InvocationInfo.ScriptLineNumber
			Write-LogErr "EXCEPTION in WSLProvider : $ErrorMessage at line: $ErrorLine"
		}
		if (!$deploySuccess){
			if ($allVMData) {
				$this.DeleteTestVMs($allVMData, $SetupTypeData, $false)
			}
		} else {
			$isVmAlive = Is-VmAlive -AllVMDataObject $allVMData
			if ($isVmAlive -eq "True") {
				return $allVMData
			}
			else
			{
				Write-LogErr "Unable to connect SSH ports.."
			}
		}
		return $null
	}

	[void] DeleteTestVMs($allVMData, $SetupTypeData, $UseExistingRG) {
		foreach ($vmData in $AllVMData) {
			try {
				Write-LogInfo "Close port $($vmData.SSHPort) on server $($vmData.WSLHost)"
				Invoke-Command -Session $this.SessionMap[$vmData.WSLHost] -ScriptBlock {
					param ($port)
					netsh advfirewall firewall del rule name="Open Port $port for LISAv2 run $global:TestID"
				} -ArgumentList $vmData.SSHPort
				if ($vmData.DistroName) {
					Write-LogInfo "Unregister WSL distro $($vmData.DistroName)"
					Invoke-Command -Session $this.SessionMap[$vmData.WSLHost] -ScriptBlock {
						param ($distroName)
						& wslconfig /u $distroName
						Remove-Item -Path (Split-Path -Path $launchDistroCommand -Parent) -Recurse -Force
					} -ArgumentList $vmData.DistroName
				} else {
					Write-LogInfo "Skip unregistering WSL distro"
				}
			} catch {
				$ErrorMessage = $_.Exception.Message
				$ErrorLine = $_.InvocationInfo.ScriptLineNumber
				Write-LogErr "EXCEPTION om WSLProvider: $ErrorMessage at line: $ErrorLine"
			}
		}
	}

	[void] RunTestCleanup() {
		try {
			foreach ($session in $this.SessionMap.Values) {
				Remove-PSSession -Session $session
			}
		} catch {
			$ErrorMessage = $_.Exception.Message
			$ErrorLine = $_.InvocationInfo.ScriptLineNumber
			Write-LogErr "EXCEPTION in WSLProvider: $ErrorMessage at line: $ErrorLine"
		}
	}

	[object] GetInstalledWSLDistros($Server) {
		Write-LogInfo "Getting the installed WSL distros on server $Server"
		$installedDistros = @()
		$distros = Invoke-Command -Session $this.SessionMap[$Server] -ScriptBlock {
			$outputList = & wslconfig /l
			$distroList = @()
			for ($index=1; $index -lt $outputList.Length; $index++) {
				$distro = $outputList[$index].Replace("`0", "").Replace("(Default)", "")
				if ($distro -ne "") {
					$distroList += $distro.Trim()
				}
			}
			return $distroList
		}
		$installedDistros += $distros
		Write-LogInfo "$installedDistros"
		return $installedDistros
	}
}