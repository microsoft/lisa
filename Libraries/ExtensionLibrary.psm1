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

Function VerifyExtensionFromAzure ([string]$ExtensionName, [string]$ServiceName, [string]$ResourceGroupName, $maxRetryCount=20, $retryIntervalInSeconds=10)
{
	$retryCount = 1
	do
	{
		if ( $UseAzureResourceManager )
		{
			LogMsg "Verifying $ExtensionName from Azure Using Get-AzureRmResource command ..."
			$ExtensionStatus = Get-AzureRmResource -ResourceGroupName $ResourceGroupName  -ResourceType "Microsoft.Compute/virtualMachines/extensions" -ExpandProperties
			if ( ($ExtensionStatus.Properties.ProvisioningState -eq "Succeeded") -and ( $ExtensionStatus.Properties.Type -eq $ExtensionName ) )
			{
				LogMsg "$ExtensionName extension status is Succeeded in Properties.ProvisioningState"
				$retValue = $true
				$waitForExtension = $false
			}
			else
			{
				LogErr "$ExtensionName extension status is Failed in Properties.ProvisioningState"
				$retValue = $false
				$waitForExtension = $true
				WaitFor -Seconds 30
			}
		}
		else
		{
			LogMsg "Verifying $ExtensionName from Azure Using Get-AzureVM command ..."
			$vmDetails = Get-AzureVM -ServiceName $ServiceName
			if ($ExtensionName -imatch "DockerExtension")
			{
				LogMsg "Verifying docker extension status using `$vmDetails.ResourceExtensionStatusList.ExtensionSettingStatus.Operation."
				$extAzureStatus = ( $vmDetails.ResourceExtensionStatusList.ExtensionSettingStatus.Status -eq "Success" ) -and ($vmDetails.ResourceExtensionStatusList.ExtensionSettingStatus.Operation -imatch "Enable Docker" )
			}
			else
			{
				$extAzureStatus = ( $vmDetails.ResourceExtensionStatusList.ExtensionSettingStatus.Status -eq "Success" ) -and ($vmDetails.ResourceExtensionStatusList.ExtensionSettingStatus.Name -imatch $ExtensionName )
			}
 			if ( $extAzureStatus )
			{
				
				LogMsg "$ExtensionName extension status is SUCCESS in (Get-AzureVM).ResourceExtensionStatusList.ExtensionSettingStatus"
				$retValue = $true
				$waitForExtension = $false
			}
			else
			{
				LogErr "$ExtensionName extension status is FAILED in (Get-AzureVM).ResourceExtensionStatusList.ExtensionSettingStatus"
				$retValue = $false
				$waitForExtension = $true
				WaitFor -Seconds 30
			}
		}
		$retryCount += 1
		if ( ($retryCount -le $maxRetryCount) -and $waitForExtension )
		{
			LogMsg "Retrying... $($maxRetryCount-$retryCount) attempts left..."
		}
		elseif ($waitForExtension)
		{
			LogMsg "Retry Attempts exhausted."
		}
	}
	while (($retryCount -le $maxRetryCount) -and $waitForExtension )
	return $retValue
}

Function DownloadExtensionLogFilesFromVarLog ($LogFilesPaths, $ExtensionName, $vmData, [switch] $deleteAfterDownload)
{
	foreach ($file in $LogFilesPaths.Split(","))
	{
		$fileName = $file.Split("/")[$file.Split("/").Count -1]
		if ( $file -imatch $ExtensionName )
		{
			if ( $deleteAfterDownload )
			{
				$out = RunLinuxCmd -username $user -password $password -ip $vmData.PublicIP -port $vmData.SSHPort -command "cat $file > $fileName && rm -rf $file" -runAsSudo
			}
			else
			{
				$out = RunLinuxCmd -username $user -password $password -ip $vmData.PublicIP -port $vmData.SSHPort -command "cat $file > $fileName" -runAsSudo
			}
			RemoteCopy -download -downloadFrom $vmData.PublicIP -files $fileName -downloadTo $LogDir -port $vmData.SSHPort -username $user -password $password
		}
		else
		{
			LogErr "Unexpected Extension Found : $($file.Split("/")[4]) with version $($file.Split("/")[5])"
			LogMsg "Skipping download for : $($file.Split("/")[4]) : $fileName"
		}
	}
}

Function GetExtensionStatusFromStatusFile ( $statusFilePaths, $ExtensionName, $vmData, $expextedFile, $maxRetryCount = 20, $retryIntervalInSeconds=10)
{
	$retryCount = 1
	do
	{
		foreach ($file in $statusFilePaths.Split(","))
		{
			$fileName = $file.Split("/")[$file.Split("/").Count -1]
			LogMsg "Verifying $ExtensionName from $file ..."
			if($fileName -imatch "\d.status")
			{
				if ( $file -imatch $ExtensionName ) 
				{
					$extensionErrorCount = 0
					$statusFileNotFound = $false
					$out = RunLinuxCmd -username $user -password $password -ip $vmData.PublicIP -port $vmData.SSHPort -command "cat $file > $fileName" -runAsSudo
					RemoteCopy -download -downloadFrom $vmData.PublicIP -files $fileName -downloadTo $LogDir -port $vmData.SSHPort -username $user -password $password
					$statusFile = [string](Get-Content -Path "$LogDir\$fileName")
					$extensionVarLibStatus = ConvertFrom-Json -InputObject $statusFile
					if ( $extensionVarLibStatus.Status.status -eq "success" )
					{
						LogMsg "$fileName reported status : $($extensionVarLibStatus.Status.status)"
					}
					else
					{
						LogErr "$fileName reported status : $($extensionVarLibStatus.Status.status)"
						$extensionErrorCount += 1
					}
					if ( $extensionVarLibStatus.Status.code -eq 0 )
					{
						LogMsg "$fileName reported code : $($extensionVarLibStatus.Status.code)"
					}
					else
					{
						LogErr "$fileName reported code : $($extensionVarLibStatus.Status.code)"
						LogMsg "Skipping this error because 'code' report is optional."
						#$extensionErrorCount += 1
					}
				}
				else
				{
					LogErr "Unexpected status file Found : $file"
					LogMsg "Skipping checking for this file"
				}
			}
		}
		if ( $extensionErrorCount -eq 0 )
		{
			LogMsg "Extension verified successfully."
			$retValue = $true
			$waitForExtension = $false

		}
		else
		{
			LogErr "Extension Verification Failed."
			$retValue = $false
			$waitForExtension = $true
			WaitFor -Seconds 30

		}		
		$retryCount += 1
		if ( ($retryCount -le $maxRetryCount) -and $waitForExtension )
		{
			LogMsg "Retrying... $($maxRetryCount-$retryCount) attempts left..."
		}
		elseif ($waitForExtension)
		{
			LogMsg "Retry Attempts exhausted."
		}
	}
	while (($retryCount -le $maxRetryCount) -and $waitForExtension )
	return $retValue
}

Function SetAzureVMExtension ( $publicConfigString, $privateConfigString, $ExtensionName, $ExtensionVersion, $LatestExtensionVersion, $Publisher, $vmData, $maxRetryCount = 20, $retryIntervalInSeconds=10)
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
		LogMsg "attempt [$retryCount/$maxRetryCount] : Setting $ExtensionName for $($vmData.RoleName) ..."

		if ( $UseAzureResourceManager )
		{
			$RGName = $vmData.ResourceGroupName
			$VMName = $vmData.RoleName
			$Location = (Get-AzureRmResourceGroup -Name $RGName).Location
			if ( $publicConfigString -and $privateConfigString )
			{
				LogMsg "Public Config : $publicConfigString"
				LogMsg "Private Config : $privateConfigString"
				$ExtStatus = Set-AzureRmVMExtension -ResourceGroupName $RGName -VMName $VMName -Location $Location -Name $ExtensionName -Publisher $Publisher -ExtensionType $ExtensionName -TypeHandlerVersion $LatestExtensionVersion -Settingstring $publicConfigString -ProtectedSettingString $privateConfigString -Verbose
			}
			else
			{
				if ($publicConfigString)
				{
					LogMsg "Public Config : $publicConfigString"
					$ExtStatus = Set-AzureRmVMExtension -ResourceGroupName $RGName -VMName $VMName -Location $Location -Name $ExtensionName -Publisher $Publisher -ExtensionType $ExtensionName -TypeHandlerVersion $LatestExtensionVersion -Settingstring $publicConfigString -Verbose
				}
				if ($privateConfigString)
				{
					LogMsg "Private Config : $privateConfigString"
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
				WaitFor -Seconds 30
			}			

		}
		else
		{

			if ( $publicConfigString -and $privateConfigString )
			{
				LogMsg "Public Config : $publicConfigString"
				LogMsg "Private Config : $privateConfigString"
				$ExtStatus = Get-AzureVM -ServiceName $vmData.ServiceName -Name $vmData.RoleName | Set-AzureVMExtension -ExtensionName $ExtensionName -Publisher $Publisher -Version $ExtensionVersion -PrivateConfiguration $privateConfigString -PublicConfiguration $publicConfigString | Update-AzureVM -Verbose
			}
			else
			{
				if ($publicConfigString)
				{
					LogMsg "Public Config : $publicConfigString"
					$ExtStatus = Get-AzureVM -ServiceName $vmData.ServiceName -Name $vmData.RoleName | Set-AzureVMExtension -ExtensionName $ExtensionName  -Publisher $Publisher -Version $ExtensionVersion -PublicConfiguration $publicConfigString | Update-AzureVM -Verbose
				}
				if ($privateConfigString )
				{
					LogMsg "Private Config : $privateConfigString"
					$ExtStatus = Get-AzureVM -ServiceName $vmData.ServiceName -Name $vmData.RoleName | Set-AzureVMExtension -ExtensionName $ExtensionName -Publisher $Publisher -Version $ExtensionVersion -PrivateConfiguration $privateConfigString | Update-AzureVM -Verbose
				}
			}

			if ( $ExtStatus.OperationStatus -eq "Succeeded" )
			{
				$retValue = $true
				$waitForExtension = $false
			}
			else
			{
				WaitFor -Seconds 30
			}
		}

		$retryCount += 1
		if ( ($retryCount -le $maxRetryCount) -and $waitForExtension )
		{
			LogMsg "Retrying... $($maxRetryCount-$retryCount) attempts left..."
		}
		elseif ($waitForExtension)
		{
			LogMsg "Retry Attempts exhausted."
		}
	}
	while (($retryCount -le $maxRetryCount) -and $waitForExtension )

	return $retValue
}

Function GetStatusFileNameToVerfiy ($vmData, $expectedExtensionName, [switch]$upcoming, $maxRetryCount = 20, $retryInterval = 10)
{
	$statusFileCounter = 0
	$waitForStatusFile = $true
	$retryCount = 0
	LogMsg "Getting current *.status file info..."
	do
		{
		$retryCount += 1		
		$currentExtFiles = GetFilePathsFromLinuxFolder -folderToSearch "/var/lib/waagent" -IpAddress $vmData.PublicIP -SSHPort $vmData.SSHPort -username $user -password $password -maxRetryCount 5
		foreach ($line in $currentExtFiles[0].Split(","))
		{
			$tempFileName = $($line.Split('/')[ $line.Split('/').Count - 1 ])
			if ( ($tempFileName -imatch "\d.status") -and ($line -imatch $expectedExtensionName))
			{
				LogMsg "Found : $line."
				$statusFileCounter += 1 
			}
		}
		if ( $upcoming )
		{
			if ($statusFileCounter -eq 0)
			{
				LogMsg "No any previous *.status file found. Hence setting expected status file as $statusFileCounter.status"
				$statusFileToVerfiy = "$statusFileCounter.status"
			}
			else
			{
				LogMsg "Hence setting expected status file as $statusFileCounter.status"
				$statusFileToVerfiy = "$statusFileCounter.status"
			}
			$waitForStatusFile = $false
		}
		else
		{
			if ($statusFileCounter -eq 0)
			{
				LogMsg "No any previous *.status file found."
				WaitFor -seconds 10
			}
			else
			{
				$waitForStatusFile = $false
				LogMsg "Hence setting status file as $($statusFileCounter-1).status"
				$statusFileToVerfiy = "$($statusFileCounter-1).status"
			}
		}
	}
	while (($retryCount -le $maxRetryCount) -and $waitForStatusFile )
	
	return $statusFileToVerfiy
}