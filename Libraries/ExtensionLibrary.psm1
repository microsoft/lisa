##############################################################################################
# ExtensionLibrary.psm1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
    Azure extension test library.

.PARAMETER
    <Parameters>

.INPUTS


.NOTES
    Creation Date:
    Purpose/Change:

.EXAMPLE


#>
###############################################################################################

Function Verify-ExtensionFromAzure ([string]$ExtensionName, [string]$ServiceName, [string]$ResourceGroupName, $maxRetryCount=20, $retryIntervalInSeconds=10)
{
	$retryCount = 1
	do
	{
		Write-LogInfo "Verifying $ExtensionName from Azure Using Get-AzureRmResource command ..."
		$ExtensionStatus = Get-AzureRmResource -ResourceGroupName $ResourceGroupName  -ResourceType "Microsoft.Compute/virtualMachines/extensions" -ExpandProperties
		if ( ($ExtensionStatus.Properties.ProvisioningState -eq "Succeeded") -and ( $ExtensionStatus.Properties.Type -eq $ExtensionName ) )
		{
			Write-LogInfo "$ExtensionName extension status is Succeeded in Properties.ProvisioningState"
			$retValue = $true
			$waitForExtension = $false
		}
		else
		{
			Write-LogErr "$ExtensionName extension status is Failed in Properties.ProvisioningState"
			$retValue = $false
			$waitForExtension = $true
			Wait-Time -Seconds 30
		}
		$retryCount += 1
		if ( ($retryCount -le $maxRetryCount) -and $waitForExtension )
		{
			Write-LogInfo "Retrying... $($maxRetryCount-$retryCount) attempts left..."
		}
		elseif ($waitForExtension)
		{
			Write-LogInfo "Retry Attempts exhausted."
		}
	}
	while (($retryCount -le $maxRetryCount) -and $waitForExtension )
	return $retValue
}

Function Download-ExtensionLogFilesFromVarLog ($LogFilesPaths, $ExtensionName, $vmData, [switch] $deleteAfterDownload)
{
	foreach ($file in $LogFilesPaths.Split(","))
	{
		$fileName = $file.Split("/")[$file.Split("/").Count -1]
		if ( $file -imatch $ExtensionName )
		{
			if ( $deleteAfterDownload )
			{
				$null = Run-LinuxCmd -username $user -password $password -ip $vmData.PublicIP -port $vmData.SSHPort -command "cat $file > $fileName && rm -rf $file" -runAsSudo
			}
			else
			{
				$null = Run-LinuxCmd -username $user -password $password -ip $vmData.PublicIP -port $vmData.SSHPort -command "cat $file > $fileName" -runAsSudo
			}
			Copy-RemoteFiles -download -downloadFrom $vmData.PublicIP -files $fileName -downloadTo $LogDir -port $vmData.SSHPort -username $user -password $password
		}
		else
		{
			Write-LogErr "Unexpected Extension Found : $($file.Split("/")[4]) with version $($file.Split("/")[5])"
			Write-LogInfo "Skipping download for : $($file.Split("/")[4]) : $fileName"
		}
	}
}

Function Get-ExtensionStatusFromStatusFile ( $statusFilePaths, $ExtensionName, $vmData, $expextedFile, $maxRetryCount = 20, $retryIntervalInSeconds=10)
{
	$retryCount = 1
	do
	{
		foreach ($file in $statusFilePaths.Split(","))
		{
			$fileName = $file.Split("/")[$file.Split("/").Count -1]
			Write-LogInfo "Verifying $ExtensionName from $file ..."
			if($fileName -imatch "\d.status")
			{
				if ( $file -imatch $ExtensionName )
				{
					$extensionErrorCount = 0
					$null = Run-LinuxCmd -username $user -password $password -ip $vmData.PublicIP -port $vmData.SSHPort -command "cat $file > $fileName" -runAsSudo
					Copy-RemoteFiles -download -downloadFrom $vmData.PublicIP -files $fileName -downloadTo $LogDir -port $vmData.SSHPort -username $user -password $password
					$statusFile = [string](Get-Content -Path "$LogDir\$fileName")
					$extensionVarLibStatus = ConvertFrom-Json -InputObject $statusFile
					if ( $extensionVarLibStatus.Status.status -eq "success" )
					{
						Write-LogInfo "$fileName reported status : $($extensionVarLibStatus.Status.status)"
					}
					else
					{
						Write-LogErr "$fileName reported status : $($extensionVarLibStatus.Status.status)"
						$extensionErrorCount += 1
					}
					if ( $extensionVarLibStatus.Status.code -eq 0 )
					{
						Write-LogInfo "$fileName reported code : $($extensionVarLibStatus.Status.code)"
					}
					else
					{
						Write-LogErr "$fileName reported code : $($extensionVarLibStatus.Status.code)"
						Write-LogInfo "Skipping this error because 'code' report is optional."
						#$extensionErrorCount += 1
					}
				}
				else
				{
					Write-LogErr "Unexpected status file Found : $file"
					Write-LogInfo "Skipping checking for this file"
				}
			}
		}
		if ( $extensionErrorCount -eq 0 )
		{
			Write-LogInfo "Extension verified successfully."
			$retValue = $true
			$waitForExtension = $false

		}
		else
		{
			Write-LogErr "Extension Verification Failed."
			$retValue = $false
			$waitForExtension = $true
			Wait-Time -Seconds 30

		}
		$retryCount += 1
		if ( ($retryCount -le $maxRetryCount) -and $waitForExtension )
		{
			Write-LogInfo "Retrying... $($maxRetryCount-$retryCount) attempts left..."
		}
		elseif ($waitForExtension)
		{
			Write-LogInfo "Retry Attempts exhausted."
		}
	}
	while (($retryCount -le $maxRetryCount) -and $waitForExtension )
	return $retValue
}

Function Set-AzureVMExtension ( $publicConfigString, $privateConfigString, $ExtensionName, $ExtensionVersion, $LatestExtensionVersion, $Publisher, $vmData, $maxRetryCount = 20, $retryIntervalInSeconds=10)
{
	$retryCount = 1
	$waitForExtension = $true
	$retValue = $false
	if (!$privateConfigString -and !$publicConfigString )
	{
		Throw "Neither Public Configuration nor Private Configuration provided. Aborting this test."
	}
	do
	{
		Write-LogInfo "attempt [$retryCount/$maxRetryCount] : Setting $ExtensionName for $($vmData.RoleName) ..."

		$RGName = $vmData.ResourceGroupName
		$VMName = $vmData.RoleName
		$Location = (Get-AzureRmResourceGroup -Name $RGName).Location
		if ( $publicConfigString -and $privateConfigString )
		{
			Write-LogInfo "Public Config : $publicConfigString"
			Write-LogInfo "Private Config : $privateConfigString"
			$ExtStatus = Set-AzureRmVMExtension -ResourceGroupName $RGName -VMName $VMName -Location $Location -Name $ExtensionName -Publisher $Publisher -ExtensionType $ExtensionName -TypeHandlerVersion $LatestExtensionVersion -Settingstring $publicConfigString -ProtectedSettingString $privateConfigString -Verbose
		}
		else
		{
			if ($publicConfigString)
			{
				Write-LogInfo "Public Config : $publicConfigString"
				$ExtStatus = Set-AzureRmVMExtension -ResourceGroupName $RGName -VMName $VMName -Location $Location -Name $ExtensionName -Publisher $Publisher -ExtensionType $ExtensionName -TypeHandlerVersion $LatestExtensionVersion -Settingstring $publicConfigString -Verbose
			}
			if ($privateConfigString)
			{
				Write-LogInfo "Private Config : $privateConfigString"
				$ExtStatus = Set-AzureRmVMExtension -ResourceGroupName $RGName -VMName $VMName -Location $Location -Name $ExtensionName -Publisher $Publisher -ExtensionType $ExtensionName -TypeHandlerVersion $LatestExtensionVersion -ProtectedSettingString $privateConfigString -Verbose
			}
		}
		if ( ![string]::IsNullOrEmpty($ExtStatus.StatusCode) -and $ExtStatus.StatusCode.ToString() -eq "OK" )
		{
			$retValue = $true
			$waitForExtension = $false
		}
		else
		{
			Wait-Time -Seconds 30
		}

		$retryCount += 1
		if ( ($retryCount -le $maxRetryCount) -and $waitForExtension )
		{
			Write-LogInfo "Retrying... $($maxRetryCount-$retryCount) attempts left..."
		}
		elseif ($waitForExtension)
		{
			Write-LogInfo "Retry Attempts exhausted."
		}
	}
	while (($retryCount -le $maxRetryCount) -and $waitForExtension )

	return $retValue
}

Function Get-StatusFileNameToVerfiy ($vmData, $expectedExtensionName, [switch]$upcoming, $maxRetryCount = 20, $retryInterval = 10)
{
	$statusFileCounter = 0
	$waitForStatusFile = $true
	$retryCount = 0
	Write-LogInfo "Getting current *.status file info..."
	do
		{
		$retryCount += 1
		$currentExtFiles = Get-FilePathsFromLinuxFolder -folderToSearch "/var/lib/waagent" -IpAddress $vmData.PublicIP -SSHPort $vmData.SSHPort -username $user -password $password -maxRetryCount 5
		foreach ($line in $currentExtFiles[0].Split(","))
		{
			$tempFileName = $($line.Split('/')[ $line.Split('/').Count - 1 ])
			if ( ($tempFileName -imatch "\d.status") -and ($line -imatch $expectedExtensionName))
			{
				Write-LogInfo "Found : $line."
				$statusFileCounter += 1
			}
		}
		if ( $upcoming )
		{
			if ($statusFileCounter -eq 0)
			{
				Write-LogInfo "No any previous *.status file found. Hence setting expected status file as $statusFileCounter.status"
				$statusFileToVerfiy = "$statusFileCounter.status"
			}
			else
			{
				Write-LogInfo "Hence setting expected status file as $statusFileCounter.status"
				$statusFileToVerfiy = "$statusFileCounter.status"
			}
			$waitForStatusFile = $false
		}
		else
		{
			if ($statusFileCounter -eq 0)
			{
				Write-LogInfo "No any previous *.status file found."
				Wait-Time -seconds 10
			}
			else
			{
				$waitForStatusFile = $false
				Write-LogInfo "Hence setting status file as $($statusFileCounter-1).status"
				$statusFileToVerfiy = "$($statusFileCounter-1).status"
			}
		}
	}
	while (($retryCount -le $maxRetryCount) -and $waitForStatusFile )

	return $statusFileToVerfiy
}
