##############################################################################################
# PrepareEnvOfNestedVMsTestOnHyperv.ps1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#

.EXAMPLE
  .\JenkinsPipelines\Scripts\PrepareEnvOfNestedVMsTestOnHyperv.ps1 -serviceHosts "example_host1,example_host2"   `
                                        -vmNamesToBeRemoved "example_VM1,example_VM2"   `
                                        -srcPath "https://YourStorageAccount.blob.core.windows.net/vhds/example.vhd"      `
                                        -dstPath "d:\\vhd\\example.vhd"         `
                                        -user '*****'  -passwd '*******'   -enable_Network

#>
##############################################################################################

param(
	[string]$serviceHosts,
	[string]$vmNamesToBeRemoved,
	[string]$srcPath = "",
	[string]$dstPath = "",
	$user,
	$passwd,
	[switch]$enable_Network
)

Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | `
     ForEach-Object { Import-Module $_.FullName -Force -Global -DisableNameChecking }

Function Remove-PreviousVM ($computerName, $vmName) {
	LogMsg "Delete the $vmName on $computerName if it exits."
	$vm = Get-VM -ComputerName $computerName | Where-Object {$_.Name -eq $vmName}
	if($vm) {
		Stop-VM -ComputerName $computerName -Name $vmName -Force
		Remove-VM -ComputerName $computerName -Name $vmName -Force
		LogMsg "Delete the $vmName on $computerName done."
	}
}

Function Get-OSvhd ([string]$computerName, [string]$srcPath, [string]$dstPath, $session) {
	LogMsg "Copy $srcPath to $dstPath on $computerName ..."
	Invoke-Command -session $session -ScriptBlock {
		param($dstPath)
		$target = ( [io.fileinfo] $dstPath ).DirectoryName
		if( -not (Test-Path $target) ) {
			LogMsg "Create the directory: $target"
			New-Item -Path $target -ItemType "directory" -Force
		}
	} -ArgumentList $dstPath

	if( $srcPath.Trim().StartsWith("http") ){
		Invoke-Command -session $session -ScriptBlock {
			param($srcPath, $dstPath)

			Import-Module BitsTransfer
			$displayName = "MyBitsTransfer" + (Get-Date)
			Start-BitsTransfer -Source $srcPath -Destination $dstPath -DisplayName $displayName -Asynchronous
			$btjob = Get-BitsTransfer $displayName
			$lastStatus = $btjob.JobState
			do{
				if($lastStatus -ne $btjob.JobState) {
					$lastStatus = $btjob.JobState
				}

				if($lastStatus -like "*Error*") {
					Remove-BitsTransfer $btjob
					LogMsg "Error connecting $srcPath to download."
					return 1
				}
			} while ($lastStatus -ne "Transferring")

			do{
				LogMsg (Get-Date) $btjob.BytesTransferred $btjob.BytesTotal ($btjob.BytesTransferred/$btjob.BytesTotal*100)
				Start-Sleep -s 20
			} while ($btjob.BytesTransferred -lt $btjob.BytesTotal)

			LogMsg (Get-Date) $btjob.BytesTransferred $btjob.BytesTotal ($btjob.BytesTransferred/$btjob.BytesTotal*100)
			Complete-BitsTransfer $btjob
		} -ArgumentList $srcPath, $dstPath
	}
	else {
		Copy-Item $srcPath -Destination $dstPath -ToSession $session
	}
	LogMsg "Copy $srcPath to $dstPath on $computerName Done."
}

function Main()
{
	try
	{
		$ExitCode = 1
		# Delete the previous VMs of network test on HyperV
		if($enable_Network) {
			foreach ( $serviceHost in $serviceHosts.Split(",").Trim() ) {
				foreach ( $vmName in $vmNamesToBeRemoved.Split(",").Trim() ) {
					Remove-PreviousVM -computerName $serviceHost -vmName $vmName
				}
			}
		}

		# Copy/download the vhd from a share path or an azure blob
		$cred = Get-Cred -user $user -password $passwd
		if($srcPath -and $dstPath) {
			foreach ( $serviceHost in $serviceHosts.Split(",").Trim() ) {
				$session = New-PsSession -ComputerName $serviceHost -Credential $cred
				Get-OSvhd -computerName $serviceHost -srcPath $srcPath -dstPath $dstPath -session $session
			}
		}
		$ExitCode = 0
	}
	catch {
		$ExitCode = 1
		ThrowException ($_)
	}
	finally {
		LogMsg "Exiting with code: $ExitCode"
		exit $ExitCode
	}
}

Main
