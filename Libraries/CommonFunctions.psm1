##############################################################################################
# CommonFunctions.psm1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
	Azure common test modules.

.PARAMETER
	<Parameters>

.INPUTS

.NOTES
	Creation Date:
	Purpose/Change:

.EXAMPLE

#>
###############################################################################################

Function ThrowException($Exception)
{
	try
	{
		$line = $Exception.InvocationInfo.ScriptLineNumber
		$script_name = ($Exception.InvocationInfo.ScriptName).Replace($PWD,".")
		$ErrorMessage =  $Exception.Exception.Message
	}
	catch
	{
		LogErr "Failed to display Exception"
	}
	finally
	{
		$now = [Datetime]::Now.ToUniversalTime().ToString("MM/dd/yyyy HH:mm:ss")
		Write-Host "$now : [OOPS   ]: $ErrorMessage"  -ForegroundColor Red
		Write-Host "$now : [SOURCE ]: Line $line in script $script_name."  -ForegroundColor Red
		Throw "Calling function - $($MyInvocation.MyCommand)"
	}
}

function LogVerbose ()
{
	param
	(
		[string]$text
	)
	try
	{
		if ($password)
		{
			$text = $text.Replace($password,"******")
		}
		$now = [Datetime]::Now.ToUniversalTime().ToString("MM/dd/yyyy HH:mm:ss")
		if ( $VerboseCommand )
		{
			Write-Verbose "$now : $text" -Verbose
		}
	}
	catch
	{
		ThrowException($_)
	}
}

function Write-Log()
{
	param
	(
		[ValidateSet('INFO','WARN','ERROR', IgnoreCase = $false)]
		[string]$logLevel,
		[string]$text
	)
	try
	{
		if ($password)
		{
			$text = $text.Replace($password,"******")
		}
		$now = [Datetime]::Now.ToUniversalTime().ToString("MM/dd/yyyy HH:mm:ss")
		$logType = $logLevel.PadRight(5, ' ')
		$finalMessage = "$now : [$logType] $text"
		$fgColor = "White"
		switch ($logLevel)
		{
			"INFO"	{$fgColor = "White"; continue}
			"WARN"	{$fgColor = "Yellow"; continue}
			"ERROR"	{$fgColor = "Red"; continue}
		}
		Write-Host $finalMessage -ForegroundColor $fgColor
		$logFolder = ""
		$logFile = "Logs.txt"
		if ($LogDir)
		{
			$logFolder = $LogDir
			$logFile = "Logs.txt"
		}
		else
		{
			$logFolder = ".\Temp"
			$logFile = "TempLogs.txt"
		}
		if ($CurrentTestLogDir )
		{
			$logFolder = $CurrentTestLogDir
			$logFile = "CurrentTestLogs.txt"
		}
		if ( !(Test-Path "$logFolder\$logFile" ) )
		{
			if (!(Test-Path $logFolder) )
			{
				New-Item -ItemType Directory -Force -Path $logFolder | Out-Null
			}
			New-Item -path $logFolder -name $logFile -type "file" -value $finalMessage | Out-Null
		}
		else
		{
			Add-Content -Value $finalMessage -Path "$logFolder\$logFile" -Force
		}
	}
	catch
	{
		Write-Output "Unable to LogError : $now : $text"
	}
}

function LogMsg($text)
{
	Write-Log "INFO" $text
}

Function LogErr($text)
{
	Write-Log "ERROR" $text
}

Function LogError($text)
{
	Write-Log "ERROR" $text
}

Function LogWarn($text)
{
	Write-Log "WARN" $text
}

Function ValidateXmlFiles( [string]$ParentFolder )
{
	LogMsg "Validating XML Files from $ParentFolder folder recursively..."
	LogVerbose "Get-ChildItem `"$ParentFolder\*.xml`" -Recurse..."
	$allXmls = Get-ChildItem "$ParentFolder\*.xml" -Recurse
	$xmlErrorFiles = @()
	foreach ($file in $allXmls)
	{
		try
		{
			$null = [xml](Get-Content $file.FullName)
			LogVerbose -text "$($file.FullName) validation successful."
		}
		catch
		{
			LogError -text "$($file.FullName) validation failed."
			$xmlErrorFiles += $file.FullName
		}
	}
	if ( $xmlErrorFiles.Count -gt 0 )
	{
		$xmlErrorFiles | ForEach-Object -Process {LogMsg $_}
		Throw "Please fix above ($($xmlErrorFiles.Count)) XML files."
	}
}

Function ProvisionVMsForLisa($allVMData, $installPackagesOnRoleNames)
{
	$keysGenerated = $false
	foreach ( $vmData in $allVMData )
	{
		LogMsg "Configuring $($vmData.RoleName) for LISA test..."
		RemoteCopy -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files ".\Testscripts\Linux\utils.sh,.\Testscripts\Linux\enableRoot.sh,.\Testscripts\Linux\enablePasswordLessRoot.sh,.\Testscripts\Linux\provisionLinuxForLisa.sh" -username $user -password $password -upload
		$Null = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -command "chmod +x /home/$user/*.sh" -runAsSudo
		$rootPasswordSet = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort `
			-username $user -password $password -runAsSudo `
			-command ("/home/{0}/enableRoot.sh -password {1}" -f @($user, $password.Replace('"','')))
		LogMsg $rootPasswordSet
		if (( $rootPasswordSet -imatch "ROOT_PASSWRD_SET" ) -and ( $rootPasswordSet -imatch "SSHD_RESTART_SUCCESSFUL" ))
		{
			LogMsg "root user enabled for $($vmData.RoleName) and password set to $password"
		}
		else
		{
			Throw "Failed to enable root password / starting SSHD service. Please check logs. Aborting test."
		}
		$Null = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "cp -ar /home/$user/*.sh ."
		if ( $keysGenerated )
		{
			RemoteCopy -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files ".\$LogDir\sshFix.tar" -username "root" -password $password -upload
			$keyCopyOut = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "./enablePasswordLessRoot.sh"
			LogMsg $keyCopyOut
			if ( $keyCopyOut -imatch "KEY_COPIED_SUCCESSFULLY" )
			{
				$keysGenerated = $true
				LogMsg "SSH keys copied to $($vmData.RoleName)"
				$md5sumCopy = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "md5sum .ssh/id_rsa"
				if ( $md5sumGen -eq $md5sumCopy )
				{
					LogMsg "md5sum check success for .ssh/id_rsa."
				}
				else
				{
					Throw "md5sum check failed for .ssh/id_rsa. Aborting test."
				}
			}
			else
			{
				Throw "Error in copying SSH key to $($vmData.RoleName)"
			}
		}
		else
		{
			$Null = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "rm -rf /root/sshFix*"
			$keyGenOut = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "./enablePasswordLessRoot.sh"
			LogMsg $keyGenOut
			if ( $keyGenOut -imatch "KEY_GENERATED_SUCCESSFULLY" )
			{
				$keysGenerated = $true
				LogMsg "SSH keys generated in $($vmData.RoleName)"
				RemoteCopy -download -downloadFrom $vmData.PublicIP -port $vmData.SSHPort  -files "/root/sshFix.tar" -username "root" -password $password -downloadTo $LogDir
				$md5sumGen = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "md5sum .ssh/id_rsa"
			}
			else
			{
				Throw "Error in generating SSH key in $($vmData.RoleName)"
			}
		}
	}

	$packageInstallJobs = @()
	foreach ( $vmData in $allVMData )
	{
		if ( $installPackagesOnRoleNames )
		{
			if ( $installPackagesOnRoleNames -imatch $vmData.RoleName )
			{
				LogMsg "Executing $scriptName ..."
				$jobID = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "/root/$scriptName" -RunInBackground
				$packageInstallObj = New-Object PSObject
				Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name ID -Value $jobID
				Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name RoleName -Value $vmData.RoleName
				Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name PublicIP -Value $vmData.PublicIP
				Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name SSHPort -Value $vmData.SSHPort
				$packageInstallJobs += $packageInstallObj
				#endregion
			}
			else
			{
				LogMsg "$($vmData.RoleName) is set to NOT install packages. Hence skipping package installation on this VM."
			}
		}
		else
		{
			LogMsg "Executing $scriptName ..."
			$jobID = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "/root/$scriptName" -RunInBackground
			$packageInstallObj = New-Object PSObject
			Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name ID -Value $jobID
			Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name RoleName -Value $vmData.RoleName
			Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name PublicIP -Value $vmData.PublicIP
			Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name SSHPort -Value $vmData.SSHPort
			$packageInstallJobs += $packageInstallObj
			#endregion
		}
	}

	$packageInstallJobsRunning = $true
	while ($packageInstallJobsRunning)
	{
		$packageInstallJobsRunning = $false
		foreach ( $job in $packageInstallJobs )
		{
			if ( (Get-Job -Id $($job.ID)).State -eq "Running" )
			{
				$currentStatus = RunLinuxCmd -ip $job.PublicIP -port $job.SSHPort -username "root" -password $password -command "tail -n 1 /root/provisionLinux.log"
				LogMsg "Package Installation Status for $($job.RoleName) : $currentStatus"
				$packageInstallJobsRunning = $true
			}
			else
			{
				RemoteCopy -download -downloadFrom $job.PublicIP -port $job.SSHPort -files "/root/provisionLinux.log" -username "root" -password $password -downloadTo $LogDir
				Rename-Item -Path "$LogDir\provisionLinux.log" -NewName "$($job.RoleName)-provisionLinux.log" -Force | Out-Null
			}
		}
		if ( $packageInstallJobsRunning )
		{
			WaitFor -seconds 10
		}
	}
}

function InstallCustomKernel ($CustomKernel, $allVMData, [switch]$RestartAfterUpgrade)
{
	try
	{
		$currentKernelVersion = ""
		$upgradedKernelVersion = ""
		$CustomKernel = $CustomKernel.Trim()
		if( ($CustomKernel -ne "ppa") -and ($CustomKernel -ne "linuxnext") -and `
		($CustomKernel -ne "netnext") -and ($CustomKernel -ne "proposed") -and `
		($CustomKernel -ne "latest") -and !($CustomKernel.EndsWith(".deb"))  -and `
		!($CustomKernel.EndsWith(".rpm")) )
		{
			LogErr "Only linuxnext, netnext, proposed, latest are supported. E.g. -CustomKernel linuxnext/netnext/proposed. Or use -CustomKernel <link to deb file>, -CustomKernel <link to rpm file>"
		}
		else
		{
			$scriptName = "customKernelInstall.sh"
			$jobCount = 0
			$kernelSuccess = 0
			$packageInstallJobs = @()
			$CustomKernelLabel = $CustomKernel
			foreach ( $vmData in $allVMData )
			{
				RemoteCopy -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files ".\Testscripts\Linux\$scriptName,.\Testscripts\Linux\DetectLinuxDistro.sh" -username $user -password $password -upload
				if ( $CustomKernel.StartsWith("localfile:")) {
					$customKernelFilePath = $CustomKernel.Replace('localfile:','')
					$customKernelFilePath = (Resolve-Path $customKernelFilePath).Path
					if ($customKernelFilePath -and (Test-Path $customKernelFilePath)) {
						RemoteCopy -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files $customKernelFilePath `
							-username $user -password $password -upload
					} else {
						LogErr "Failed to find kernel file ${customKernelFilePath}"
						return $false
					}
					$CustomKernelLabel = "localfile:{0}" -f @((Split-Path -Leaf $CustomKernel.Replace('localfile:','')))
				}
				RemoteCopy -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files ".\Testscripts\Linux\$scriptName,.\Testscripts\Linux\DetectLinuxDistro.sh" -username $user -password $password -upload

				$Null = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -command "chmod +x *.sh" -runAsSudo
				$currentKernelVersion = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -command "uname -r"
				LogMsg "Executing $scriptName ..."
				$jobID = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user `
					-password $password -command "/home/$user/$scriptName -CustomKernel '$CustomKernelLabel' -logFolder /home/$user" `
					-RunInBackground -runAsSudo
				$packageInstallObj = New-Object PSObject
				Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name ID -Value $jobID
				Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name RoleName -Value $vmData.RoleName
				Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name PublicIP -Value $vmData.PublicIP
				Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name SSHPort -Value $vmData.SSHPort
				$packageInstallJobs += $packageInstallObj
				$jobCount += 1
				#endregion
			}
			$packageInstallJobsRunning = $true
			while ($packageInstallJobsRunning)
			{
				$packageInstallJobsRunning = $false
				foreach ( $job in $packageInstallJobs )
				{
					if ( (Get-Job -Id $($job.ID)).State -eq "Running" )
					{
						$currentStatus = RunLinuxCmd -ip $job.PublicIP -port $job.SSHPort -username $user -password $password -command "tail -n 1 build-CustomKernel.txt"
						LogMsg "Package Installation Status for $($job.RoleName) : $currentStatus"
						$packageInstallJobsRunning = $true
					}
					else
					{
						if ( !(Test-Path -Path "$LogDir\$($job.RoleName)-build-CustomKernel.txt" ) )
						{
							RemoteCopy -download -downloadFrom $job.PublicIP -port $job.SSHPort -files "build-CustomKernel.txt" -username $user -password $password -downloadTo $LogDir
							if ( ( Get-Content "$LogDir\build-CustomKernel.txt" ) -imatch "CUSTOM_KERNEL_SUCCESS" )
							{
								$kernelSuccess += 1
							}
							Rename-Item -Path "$LogDir\build-CustomKernel.txt" -NewName "$($job.RoleName)-build-CustomKernel.txt" -Force | Out-Null
						}
					}
				}
				if ( $packageInstallJobsRunning )
				{
					WaitFor -seconds 10
				}
			}
			if ( $kernelSuccess -eq $jobCount )
			{
				LogMsg "Kernel upgraded to `"$CustomKernel`" successfully in $($allVMData.Count) VM(s)."
				if ( $RestartAfterUpgrade )
				{
					LogMsg "Now restarting VMs..."
					$restartStatus = RestartAllDeployments -allVMData $allVMData
					if ( $restartStatus -eq "True")
					{
						$retryAttempts = 5
						$isKernelUpgraded = $false
						while ( !$isKernelUpgraded -and ($retryAttempts -gt 0) )
						{
							$retryAttempts -= 1
							$upgradedKernelVersion = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -command "uname -r"
							LogMsg "Old kernel: $currentKernelVersion"
							LogMsg "New kernel: $upgradedKernelVersion"
							if ($currentKernelVersion -eq $upgradedKernelVersion)
							{
								LogErr "Kernel version is same after restarting VMs."
								if ( ($CustomKernel -eq "latest") -or ($CustomKernel -eq "ppa") -or ($CustomKernel -eq "proposed") )
								{
									LogMsg "Continuing the tests as default kernel is same as $CustomKernel."
									$isKernelUpgraded = $true
								}
								else
								{
									$isKernelUpgraded = $false
								}
							}
							else
							{
								$isKernelUpgraded = $true
							}
							Add-Content -Value "Old kernel: $currentKernelVersion" -Path .\report\AdditionalInfo.html -Force
							Add-Content -Value "New kernel: $upgradedKernelVersion" -Path .\report\AdditionalInfo.html -Force
							return $isKernelUpgraded
						}
					}
					else
					{
						return $false
					}
				}
				return $true
			}
			else
			{
				LogErr "Kernel upgrade failed in $($jobCount-$kernelSuccess) VMs."
				return $false
			}
		}
	}
	catch
	{
		LogErr "Exception in InstallCustomKernel."
		return $false
	}
}

function InstallcustomLIS ($CustomLIS, $customLISBranch, $allVMData, [switch]$RestartAfterUpgrade)
{
	try
	{
		$CustomLIS = $CustomLIS.Trim()
		if( ($CustomLIS -ne "lisnext") -and !($CustomLIS.EndsWith("tar.gz")))
		{
			LogErr "Only lisnext and *.tar.gz links are supported. Use -CustomLIS lisnext -LISbranch <branch name>. Or use -CustomLIS <link to tar.gz file>"
		}
		else
		{
			ProvisionVMsForLisa -allVMData $allVMData -installPackagesOnRoleNames none
			$scriptName = "customLISInstall.sh"
			$jobCount = 0
			$lisSuccess = 0
			$packageInstallJobs = @()
			foreach ( $vmData in $allVMData )
			{
				RemoteCopy -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files ".\Testscripts\Linux\$scriptName,.\Testscripts\Linux\DetectLinuxDistro.sh" -username "root" -password $password -upload
				$Null = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "chmod +x *.sh" -runAsSudo
				$currentlisVersion = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "modinfo hv_vmbus"
				LogMsg "Executing $scriptName ..."
				$jobID = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "/root/$scriptName -CustomLIS $CustomLIS -LISbranch $customLISBranch" -RunInBackground -runAsSudo
				$packageInstallObj = New-Object PSObject
				Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name ID -Value $jobID
				Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name RoleName -Value $vmData.RoleName
				Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name PublicIP -Value $vmData.PublicIP
				Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name SSHPort -Value $vmData.SSHPort
				$packageInstallJobs += $packageInstallObj
				$jobCount += 1
				#endregion
			}

			$packageInstallJobsRunning = $true
			while ($packageInstallJobsRunning)
			{
				$packageInstallJobsRunning = $false
				foreach ( $job in $packageInstallJobs )
				{
					if ( (Get-Job -Id $($job.ID)).State -eq "Running" )
					{
						$currentStatus = RunLinuxCmd -ip $job.PublicIP -port $job.SSHPort -username "root" -password $password -command "tail -n 1 build-CustomLIS.txt"
						LogMsg "Package Installation Status for $($job.RoleName) : $currentStatus"
						$packageInstallJobsRunning = $true
					}
					else
					{
						if ( !(Test-Path -Path "$LogDir\$($job.RoleName)-build-CustomLIS.txt" ) )
						{
							RemoteCopy -download -downloadFrom $job.PublicIP -port $job.SSHPort -files "build-CustomLIS.txt" -username "root" -password $password -downloadTo $LogDir
							if ( ( Get-Content "$LogDir\build-CustomLIS.txt" ) -imatch "CUSTOM_LIS_SUCCESS" )
							{
								$lisSuccess += 1
							}
							Rename-Item -Path "$LogDir\build-CustomLIS.txt" -NewName "$($job.RoleName)-build-CustomLIS.txt" -Force | Out-Null
						}
					}
				}
				if ( $packageInstallJobsRunning )
				{
					WaitFor -seconds 10
				}
			}

			if ( $lisSuccess -eq $jobCount )
			{
				LogMsg "lis upgraded to `"$CustomLIS`" successfully in all VMs."
				if ( $RestartAfterUpgrade )
				{
					LogMsg "Now restarting VMs..."
					$restartStatus = RestartAllDeployments -allVMData $allVMData
					if ( $restartStatus -eq "True")
					{
						$upgradedlisVersion = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "modinfo hv_vmbus"
						LogMsg "Old lis: $currentlisVersion"
						LogMsg "New lis: $upgradedlisVersion"
						Add-Content -Value "Old lis: $currentlisVersion" -Path .\report\AdditionalInfo.html -Force
						Add-Content -Value "New lis: $upgradedlisVersion" -Path .\report\AdditionalInfo.html -Force
						return $true
					}
					else
					{
						return $false
					}
				}
				return $true
			}
			else
			{
				LogErr "lis upgrade failed in $($jobCount-$lisSuccess) VMs."
				return $false
			}
		}
	}
	catch
	{
		LogErr "Exception in InstallcustomLIS."
		return $false
	}
}

function VerifyMellanoxAdapter($vmData)
{
	$maxRetryAttemps = 50
	$retryAttempts = 1
	$mellanoxAdapterDetected = $false
	while ( !$mellanoxAdapterDetected -and ($retryAttempts -lt $maxRetryAttemps))
	{
		$pciDevices = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -command "lspci" -runAsSudo
		if ( $pciDevices -imatch "Mellanox")
		{
			LogMsg "[Attempt $retryAttempts/$maxRetryAttemps] Mellanox Adapter detected in $($vmData.RoleName)."
			$mellanoxAdapterDetected = $true
		}
		else
		{
			LogErr "[Attempt $retryAttempts/$maxRetryAttemps] Mellanox Adapter NOT detected in $($vmData.RoleName)."
			$retryAttempts += 1
		}
	}
	return $mellanoxAdapterDetected
}

function EnableSRIOVInAllVMs($allVMData)
{
	try
	{
		if( $EnableAcceleratedNetworking)
		{
			$scriptName = "ConfigureSRIOV.sh"
			$sriovDetectedCount = 0
			$vmCount = 0

			foreach ( $vmData in $allVMData )
			{
				$vmCount += 1
				$currentMellanoxStatus = VerifyMellanoxAdapter -vmData $vmData
				if ( $currentMellanoxStatus )
				{
					LogMsg "Mellanox Adapter detected in $($vmData.RoleName)."
					RemoteCopy -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files ".\Testscripts\Linux\$scriptName" -username $user -password $password -upload
					$Null = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -command "chmod +x *.sh" -runAsSudo
					$sriovOutput = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -command "/home/$user/$scriptName" -runAsSudo
					$sriovDetectedCount += 1
				}
				else
				{
					LogErr "Mellanox Adapter not detected in $($vmData.RoleName)."
				}
				#endregion
			}

			if ($sriovDetectedCount -gt 0)
			{
				if ($sriovOutput -imatch "SYSTEM_RESTART_REQUIRED")
				{
					LogMsg "Updated SRIOV configuration. Now restarting VMs..."
					$restartStatus = RestartAllDeployments -allVMData $allVMData
				}
				if ($sriovOutput -imatch "DATAPATH_SWITCHED_TO_VF")
				{
					$restartStatus="True"
				}
			}
			$vmCount = 0
			$bondSuccess = 0
			$bondError = 0
			if ( $restartStatus -eq "True")
			{
				foreach ( $vmData in $allVMData )
				{
					$vmCount += 1
					if ($sriovOutput -imatch "DATAPATH_SWITCHED_TO_VF")
					{
						$AfterIfConfigStatus = $null
						$AfterIfConfigStatus = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -command "dmesg" -runMaxAllowedTime 30 -runAsSudo
						if ($AfterIfConfigStatus -imatch "Data path switched to VF")
						{
							LogMsg "Data path already switched to VF in $($vmData.RoleName)"
							$bondSuccess += 1
						}
						else
						{
							LogErr "Data path not switched to VF in $($vmData.RoleName)"
							$bondError += 1
						}
					}
					else
					{
						$AfterIfConfigStatus = $null
						$AfterIfConfigStatus = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -command "/sbin/ifconfig -a" -runAsSudo
						if ($AfterIfConfigStatus -imatch "bond")
						{
							LogMsg "New bond detected in $($vmData.RoleName)"
							$bondSuccess += 1
						}
						else
						{
							LogErr "New bond not detected in $($vmData.RoleName)"
							$bondError += 1
						}
					}
				}
			}
			else
			{
				return $false
			}
			if ($vmCount -eq $bondSuccess)
			{
				return $true
			}
			else
			{
				return $false
			}
		}
		else
		{
			return $true
		}
	}
	catch
	{
		$line = $_.InvocationInfo.ScriptLineNumber
		$script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
		$ErrorMessage =  $_.Exception.Message
		LogErr "EXCEPTION : $ErrorMessage"
		LogErr "Source : Line $line in script $script_name."
		return $false
	}
}

Function DetectLinuxDistro($VIP, $SSHport, $testVMUser, $testVMPassword)
{
	if ( !$detectedDistro )
	{
		$null = RemoteCopy  -upload -uploadTo $VIP -port $SSHport -files ".\Testscripts\Linux\DetectLinuxDistro.sh" -username $testVMUser -password $testVMPassword 2>&1 | Out-Null
		$null = RunLinuxCmd -username $testVMUser -password $testVMPassword -ip $VIP -port $SSHport -command "chmod +x *.sh" -runAsSudo 2>&1 | Out-Null
		$DistroName = RunLinuxCmd -username $testVMUser -password $testVMPassword -ip $VIP -port $SSHport -command "/home/$user/DetectLinuxDistro.sh" -runAsSudo
		if(($DistroName -imatch "Unknown") -or (!$DistroName))
		{
			LogError "Linux distro detected : $DistroName"
			Throw "Calling function - $($MyInvocation.MyCommand). Unable to detect distro."
		}
		else
		{
			if ($DistroName -imatch "UBUNTU")
			{
				$CleanedDistroName = "UBUNTU"
			}
			elseif ($DistroName -imatch "DEBIAN")
			{
				$CleanedDistroName = "DEBIAN"
			}
			elseif ($DistroName -imatch "CENTOS")
			{
				$CleanedDistroName = "CENTOS"
			}
			elseif ($DistroName -imatch "SLES")
			{
				$CleanedDistroName = $DistroName
			}
			elseif ($DistroName -imatch "SUSE")
			{
				$CleanedDistroName = "SUSE"
			}
			elseif ($DistroName -imatch "ORACLELINUX")
			{
				$CleanedDistroName = "ORACLELINUX"
			}
			elseif ($DistroName -imatch "REDHAT")
			{
				$CleanedDistroName = "REDHAT"
			}
			elseif ($DistroName -imatch "FEDORA")
			{
				$CleanedDistroName = "FEDORA"
			}
			elseif ($DistroName -imatch "COREOS")
			{
				$CleanedDistroName = "COREOS"
			}
			elseif ($DistroName -imatch "CLEARLINUX")
			{
				$CleanedDistroName = "CLEARLINUX"
			}
			else
			{
				$CleanedDistroName = "UNKNOWN"
			}
			Set-Variable -Name detectedDistro -Value $CleanedDistroName -Scope Global
			SetDistroSpecificVariables -detectedDistro $detectedDistro
			LogMsg "Linux distro detected : $CleanedDistroName"
		}
	}
	else
	{
		LogMsg "Distro Already Detected as : $detectedDistro"
		$CleanedDistroName = $detectedDistro
	}
	return $CleanedDistroName
}

Function WaitFor($seconds,$minutes,$hours)
{
	if(!$hours -and !$minutes -and !$seconds)
	{
		Write-Output "At least hour, minute or second requires"
	}
	else
	{
		if(!$hours)
		{
			$hours = 0
		}
		if(!$minutes)
		{
			$minutes = 0
		}
		if(!$seconds)
		{
			$seconds = 0
		}

		$timeToSleepInSeconds = ($hours*60*60) + ($minutes*60) + $seconds
		$secondsRemaining = $timeToSleepInSeconds
		$secondsRemainingPercentage = (100 - (($secondsRemaining/$timeToSleepInSeconds)*100))
		for ($i = 1; $i -le $timeToSleepInSeconds; $i++)
		{
			write-progress -Id 27 -activity SLEEPING -Status "$($secondsRemaining) seconds remaining..." -percentcomplete $secondsRemainingPercentage
			$secondsRemaining = $timeToSleepInSeconds - $i
			$secondsRemainingPercentage = (100 - (($secondsRemaining/$timeToSleepInSeconds)*100))
			Start-Sleep -Seconds 1
		}
		write-progress -Id 27 -activity SLEEPING -Status "Wait Completed..!" -Completed
	}
}

Function GetAndCheckKernelLogs($allDeployedVMs, $status, $vmUser, $vmPassword)
{
	try
	{
		if ( !$vmUser )
		{
			$vmUser = $user
		}
		if ( !$vmPassword )
		{
			$vmPassword = $password
		}
		$retValue = $false
		foreach ($VM in $allDeployedVMs)
		{
			$BootLogDir="$Logdir\$($VM.RoleName)"
			mkdir $BootLogDir -Force | Out-Null
			LogMsg "Collecting $($VM.RoleName) VM Kernel $status Logs.."
			$InitailBootLog="$BootLogDir\InitialBootLogs.txt"
			$FinalBootLog="$BootLogDir\FinalBootLogs.txt"
			$KernelLogStatus="$BootLogDir\KernelLogStatus.txt"
			if($status -imatch "Initial")
			{
				$randomFileName = [System.IO.Path]::GetRandomFileName()
				Set-Content -Value "A Random file." -Path "$Logdir\$randomFileName"
				$Null = RemoteCopy -uploadTo $VM.PublicIP -port $VM.SSHPort  -files "$Logdir\$randomFileName" -username $vmUser -password $vmPassword -upload
				Remove-Item -Path "$Logdir\$randomFileName" -Force
				$Null = RunLinuxCmd -ip $VM.PublicIP -port $VM.SSHPort -username $vmUser -password $vmPassword -command "dmesg > /home/$vmUser/InitialBootLogs.txt" -runAsSudo
				$Null = RemoteCopy -download -downloadFrom $VM.PublicIP -port $VM.SSHPort -files "/home/$vmUser/InitialBootLogs.txt" -downloadTo $BootLogDir -username $vmUser -password $vmPassword
				LogMsg "$($VM.RoleName): $status Kernel logs collected ..SUCCESSFULLY"
				LogMsg "Checking for call traces in kernel logs.."
				$KernelLogs = Get-Content $InitailBootLog
				$callTraceFound  = $false
				foreach ( $line in $KernelLogs )
				{
					if (( $line -imatch "Call Trace" ) -and  ($line -inotmatch "initcall "))
					{
						LogError $line
						$callTraceFound = $true
					}
					if ( $callTraceFound )
					{
						if ( $line -imatch "\[<")
						{
							LogError $line
						}
					}
				}
				if ( !$callTraceFound )
				{
					LogMsg "No any call traces found."
				}
				$detectedDistro = DetectLinuxDistro -VIP $VM.PublicIP -SSHport $VM.SSHPort -testVMUser $vmUser -testVMPassword $vmPassword
				SetDistroSpecificVariables -detectedDistro $detectedDistro
				$retValue = $true
			}
			elseif($status -imatch "Final")
			{
				$Null = RunLinuxCmd -ip $VM.PublicIP -port $VM.SSHPort -username $vmUser -password $vmPassword -command "dmesg > /home/$vmUser/FinalBootLogs.txt" -runAsSudo
				$Null = RemoteCopy -download -downloadFrom $VM.PublicIP -port $VM.SSHPort -files "/home/$vmUser/FinalBootLogs.txt" -downloadTo $BootLogDir -username $vmUser -password $vmPassword
				LogMsg "Checking for call traces in kernel logs.."
				$KernelLogs = Get-Content $FinalBootLog
				$callTraceFound  = $false
				foreach ( $line in $KernelLogs )
				{
					if (( $line -imatch "Call Trace" ) -and ($line -inotmatch "initcall "))
					{
						LogError $line
						$callTraceFound = $true
					}
					if ( $callTraceFound )
					{
						if ( $line -imatch "\[<")
						{
							LogError $line
						}
					}
				}
				if ( !$callTraceFound )
				{
					LogMsg "No any call traces found."
				}
				$KernelDiff = Compare-Object -ReferenceObject (Get-Content $FinalBootLog) -DifferenceObject (Get-Content $InitailBootLog)
				#Removing final dmesg file from logs to reduce the size of logs. We can always see complete Final Logs as : Initial Kernel Logs + Difference in Kernel Logs
				Remove-Item -Path $FinalBootLog -Force | Out-Null
				if($null -eq $KernelDiff)
				{
					LogMsg "** Initial and Final Kernel Logs has same content **"
					Set-Content -Value "*** Initial and Final Kernel Logs has same content ***" -Path $KernelLogStatus
					$retValue = $true
				}
				else
				{
					$errorCount = 0
					Set-Content -Value "Following lines were added in the kernel log during execution of test." -Path $KernelLogStatus
					LogMsg "Following lines were added in the kernel log during execution of test."
					Add-Content -Value "-------------------------------START----------------------------------" -Path $KernelLogStatus
					foreach ($line in $KernelDiff)
					{
						Add-Content -Value $line.InputObject -Path $KernelLogStatus
						if ( ($line.InputObject -imatch "fail") -or ($line.InputObject -imatch "error") -or ($line.InputObject -imatch "warning"))
						{
							$errorCount += 1
							LogError $line.InputObject
						}
						else
						{
							LogMsg $line.InputObject
						}
					}
					Add-Content -Value "--------------------------------EOF-----------------------------------" -Path $KernelLogStatus
				}
				LogMsg "$($VM.RoleName): $status Kernel logs collected and Compared ..SUCCESSFULLY"
				if ($errorCount -gt 0)
				{
					LogError "Found $errorCount fail/error/warning messages in kernel logs during execution."
					$retValue = $false
				}
				if ( $callTraceFound )
				{
					if ( $UseAzureResourceManager )
					{
						LogMsg "Preserving the Resource Group(s) $($VM.ResourceGroupName)"
						Add-ResourceGroupTag -ResourceGroup $VM.ResourceGroupName -TagName $preserveKeyword -TagValue "yes"
						Add-ResourceGroupTag -ResourceGroup $VM.ResourceGroupName -TagName "calltrace" -TagValue "yes"
						LogMsg "Setting tags : calltrace = yes; testName = $testName"
						$hash = @{}
						$hash.Add("calltrace","yes")
						$hash.Add("testName","$testName")
						$Null = Set-AzureRmResourceGroup -Name $($VM.ResourceGroupName) -Tag $hash
					}
					else
					{
						LogMsg "Adding preserve tag to $($VM.ServiceName) .."
						$Null = Set-AzureService -ServiceName $($VM.ServiceName) -Description $preserveKeyword
					}
				}
			}
			else
			{
				LogMsg "pass value for status variable either final or initial"
				$retValue = $false
			}
		}
	}
	catch
	{
		$retValue = $false
	}
	return $retValue
}

Function CheckKernelLogs($allVMData, $vmUser, $vmPassword)
{
	try
	{
		$errorLines = @()
		$errorLines += "Call Trace"
		$errorLines += "rcu_sched self-detected stall on CPU"
		$errorLines += "rcu_sched detected stalls on"
		$errorLines += "BUG: soft lockup"
		$totalErrors = 0
		if ( !$vmUser )
		{
			$vmUser = $user
		}
		if ( !$vmPassword )
		{
			$vmPassword = $password
		}
		$retValue = $false
		foreach ($VM in $allVMData)
		{
			$vmErrors = 0
			$BootLogDir="$Logdir\$($VM.RoleName)"
			mkdir $BootLogDir -Force | Out-Null
			LogMsg "Collecting $($VM.RoleName) VM Kernel $status Logs.."
			$currentKernelLogFile="$BootLogDir\CurrentKernelLogs.txt"
			$Null = RunLinuxCmd -ip $VM.PublicIP -port $VM.SSHPort -username $vmUser -password $vmPassword -command "dmesg > /home/$vmUser/CurrentKernelLogs.txt" -runAsSudo
			$Null = RemoteCopy -download -downloadFrom $VM.PublicIP -port $VM.SSHPort -files "/home/$vmUser/CurrentKernelLogs.txt" -downloadTo $BootLogDir -username $vmUser -password $vmPassword
			LogMsg "$($VM.RoleName): $status Kernel logs collected ..SUCCESSFULLY"
			foreach ($errorLine in $errorLines)
			{
				LogMsg "Checking for $errorLine in kernel logs.."
				$KernelLogs = Get-Content $currentKernelLogFile
				foreach ( $line in $KernelLogs )
				{
					if ( ($line -imatch "$errorLine") -and ($line -inotmatch "initcall "))
					{
						LogError $line
						$totalErrors += 1
						$vmErrors += 1
					}
					if ( $line -imatch "\[<")
					{
						LogError $line
					}
				}
			}
			if ( $vmErrors -eq 0 )
			{
				LogMsg "$($VM.RoleName) : No issues in kernel logs."
				$retValue = $true
			}
			else
			{
				LogError "$($VM.RoleName) : $vmErrors errors found."
				$retValue = $false
			}
		}
		if ( $totalErrors -eq 0 )
		{
			$retValue = $true
		}
		else
		{
			$retValue = $false
		}
	}
	catch
	{
		$retValue = $false
	}
	return $retValue
}

Function SetDistroSpecificVariables($detectedDistro)
{
	$python_cmd = "python"
	LogMsg "Set `$python_cmd > $python_cmd"
	Set-Variable -Name python_cmd -Value $python_cmd -Scope Global
	Set-Variable -Name ifconfig_cmd -Value "ifconfig" -Scope Global
	if(($detectedDistro -eq "SLES") -or ($detectedDistro -eq "SUSE"))
	{
		Set-Variable -Name ifconfig_cmd -Value "/sbin/ifconfig" -Scope Global
		Set-Variable -Name fdisk -Value "/sbin/fdisk" -Scope Global
		LogMsg "Set `$ifconfig_cmd > $ifconfig_cmd for $detectedDistro"
		LogMsg "Set `$fdisk > /sbin/fdisk for $detectedDistro"
	}
	else
	{
		Set-Variable -Name fdisk -Value "fdisk" -Scope Global
		LogMsg "Set `$fdisk > fdisk for $detectedDistro"
	}
}

Function DeployVMs ($xmlConfig, $setupType, $Distro, $getLogsIfFailed = $false, $GetDeploymentStatistics = $false, [string]$region = "", [int]$timeOutSeconds = 600, $VMGeneration = "1")
{
	#Test Platform Azure
	if ( $TestPlatform -eq "Azure" )
	{
		$retValue = DeployResourceGroups  -xmlConfig $xmlConfig -setupType $setupType -Distro $Distro -getLogsIfFailed $getLogsIfFailed -GetDeploymentStatistics $GetDeploymentStatistics -region $region
	}
	if ( $TestPlatform -eq "HyperV" )
	{
		$retValue = DeployHyperVGroups  -xmlConfig $xmlConfig -setupType $setupType -Distro $Distro `
										-getLogsIfFailed $getLogsIfFailed -GetDeploymentStatistics $GetDeploymentStatistics `
										-VMGeneration $VMGeneration
	}
	if ( $retValue -and $CustomKernel)
	{
		LogMsg "Custom kernel: $CustomKernel will be installed on all machines..."
		$kernelUpgradeStatus = InstallCustomKernel -CustomKernel $CustomKernel -allVMData $allVMData -RestartAfterUpgrade
		if ( !$kernelUpgradeStatus )
		{
			LogError "Custom Kernel: $CustomKernel installation FAIL. Aborting tests."
			$retValue = ""
		}
	}
	if ( $retValue -and $CustomLIS)
	{
		LogMsg "Custom LIS: $CustomLIS will be installed on all machines..."
		$LISUpgradeStatus = InstallCustomLIS -CustomLIS $CustomLIS -allVMData $allVMData -customLISBranch $customLISBranch -RestartAfterUpgrade
		if ( !$LISUpgradeStatus )
		{
			LogError "Custom Kernel: $CustomKernel installation FAIL. Aborting tests."
			$retValue = ""
		}
	}
	if ( $retValue -and $EnableAcceleratedNetworking)
	{
		$SRIOVStatus = EnableSRIOVInAllVMs -allVMData $allVMData
		if ( !$SRIOVStatus)
		{
			LogError "Failed to enable Accelerated Networking. Aborting tests."
			$retValue = ""
		}
	}
	if ( $retValue -and $resizeVMsAfterDeployment)
	{
		$SRIOVStatus = EnableSRIOVInAllVMs -allVMData $allVMData
		if ( $SRIOVStatus -ne "True" )
		{
			LogError "Failed to enable Accelerated Networking. Aborting tests."
			$retValue = ""
		}
	}
	return $retValue
}

Function Test-TCP($testIP, $testport)
{
	$socket = new-object Net.Sockets.TcpClient
	$isConnected = "False"
	try
	{
		$socket.Connect($testIP, $testPort)
	}
	catch [System.Net.Sockets.SocketException]
	{
		LogWarn "TCP test failed"
	}
	if ($socket.Connected)
	{
		$isConnected = "True"
	}
	$socket.Close()
	return $isConnected
}

Function RemoteCopy($uploadTo, $downloadFrom, $downloadTo, $port, $files, $username, $password, [switch]$upload, [switch]$download, [switch]$usePrivateKey, [switch]$doNotCompress) #Removed XML config
{
	$retry=1
	$maxRetry=20
	if($upload)
	{
#LogMsg "Uploading the files"
		if ($files)
		{
			$fileCounter = 0
			$tarFileName = ($uploadTo+"@"+$port).Replace(".","-")+".tar"
			foreach ($f in $files.Split(","))
			{
				if ( !$f )
				{
					continue
				}
				else
				{
					if ( ( $f.Split(".")[$f.Split(".").count-1] -eq "sh" ) -or ( $f.Split(".")[$f.Split(".").count-1] -eq "py" ) )
					{
						$out = .\tools\dos2unix.exe $f 2>&1
						LogMsg ([string]$out)
					}
					$fileCounter ++
				}
			}
			if (($fileCounter -gt 2) -and (!($doNotCompress)))
			{
				$tarFileName = ($uploadTo+"@"+$port).Replace(".","-")+".tar"
				foreach ($f in $files.Split(","))
				{
					if ( !$f )
					{
						continue
					}
					else
					{
						LogMsg "Compressing $f and adding to $tarFileName"
						$CompressFile = .\tools\7za.exe a $tarFileName $f
						if ( $CompressFile -imatch "Everything is Ok" )
						{
							$CompressCount += 1
						}
					}
				}
				if ( $CompressCount -eq $fileCounter )
				{
					$retry=1
					$maxRetry=10
					while($retry -le $maxRetry)
					{
						if($usePrivateKey)
						{
							LogMsg "Uploading $tarFileName to $username : $uploadTo, port $port using PrivateKey authentication"
							Write-Output "yes" | .\tools\pscp -i .\ssh\$sshKey -q -P $port $tarFileName $username@${uploadTo}:
							$returnCode = $LASTEXITCODE
						}
						else
						{
							LogMsg "Uploading $tarFileName to $username : $uploadTo, port $port using Password authentication"
							$curDir = $PWD
							$uploadStatusRandomFile = ".\Temp\UploadStatusFile" + (Get-Random -Maximum 9999 -Minimum 1111) + ".txt"
							$uploadStartTime = Get-Date
							$uploadJob = Start-Job -ScriptBlock { Set-Location $args[0]; Write-Output $args; Set-Content -Value "1" -Path $args[6]; $username = $args[4]; $uploadTo = $args[5]; Write-Output "yes" | .\tools\pscp -v -pw $args[1] -q -P $args[2] $args[3] $username@${uploadTo}: ; Set-Content -Value $LASTEXITCODE -Path $args[6];} -ArgumentList $curDir,$password,$port,$tarFileName,$username,${uploadTo},$uploadStatusRandomFile
							Start-Sleep -Milliseconds 100
							$uploadJobStatus = Get-Job -Id $uploadJob.Id
							$uploadTimout = $false
							while (( $uploadJobStatus.State -eq "Running" ) -and ( !$uploadTimout ))
							{
								Write-Host "." -NoNewline
								$now = Get-Date
								if ( ($now - $uploadStartTime).TotalSeconds -gt 600 )
								{
									$uploadTimout = $true
									LogError "Upload Timout!"
								}
								Start-Sleep -Seconds 1
								$uploadJobStatus = Get-Job -Id $uploadJob.Id
							}
							$returnCode = Get-Content -Path $uploadStatusRandomFile
							Remove-Item -Force $uploadStatusRandomFile | Out-Null
							Remove-Job -Id $uploadJob.Id -Force | Out-Null
						}
						if(($returnCode -ne 0) -and ($retry -ne $maxRetry))
						{
							LogWarn "Error in upload, Attempt $retry. Retrying for upload"
							$retry=$retry+1
							WaitFor -seconds 10
						}
						elseif(($returnCode -ne 0) -and ($retry -eq $maxRetry))
						{
							Write-Output "Error in upload after $retry Attempt,Hence giving up"
							$retry=$retry+1
							Throw "Calling function - $($MyInvocation.MyCommand). Error in upload after $retry Attempt,Hence giving up"
						}
						elseif($returnCode -eq 0)
						{
							LogMsg "Upload Success after $retry Attempt"
							$retry=$maxRetry+1
						}
					}
					LogMsg "Removing compressed file : $tarFileName"
					Remove-Item -Path $tarFileName -Force 2>&1 | Out-Null
					LogMsg "Decompressing files in VM ..."
					if ( $username -eq "root" )
					{
						$out = RunLinuxCmd -username $username -password $password -ip $uploadTo -port $port -command "tar -xf $tarFileName"
					}
					else
					{
						$out = RunLinuxCmd -username $username -password $password -ip $uploadTo -port $port -command "tar -xf $tarFileName" -runAsSudo
					}
				}
				else
				{
					Throw "Calling function - $($MyInvocation.MyCommand). Failed to compress $files"
					Remove-Item -Path $tarFileName -Force 2>&1 | Out-Null
				}
			}
			else
			{
				$files = $files.split(",")
				foreach ($f in $files)
				{
					if ( !$f )
					{
						continue
					}
					$retry=1
					$maxRetry=10
					$testFile = $f.trim()
					while($retry -le $maxRetry)
					{
						if($usePrivateKey)
						{
							LogMsg "Uploading $testFile to $username : $uploadTo, port $port using PrivateKey authentication"
							Write-Output "yes" | .\tools\pscp -i .\ssh\$sshKey -q -P $port $testFile $username@${uploadTo}:
							$returnCode = $LASTEXITCODE
						}
						else
						{
							LogMsg "Uploading $testFile to $username : $uploadTo, port $port using Password authentication"
							$curDir = $PWD
							$uploadStatusRandomFile = ".\Temp\UploadStatusFile" + (Get-Random -Maximum 9999 -Minimum 1111) + ".txt"
							$uploadStartTime = Get-Date
							$uploadJob = Start-Job -ScriptBlock { Set-Location $args[0]; Write-Output $args; Set-Content -Value "1" -Path $args[6]; $username = $args[4]; $uploadTo = $args[5]; Write-Output "yes" | .\tools\pscp -v -pw $args[1] -q -P $args[2] $args[3] $username@${uploadTo}: ; Set-Content -Value $LASTEXITCODE -Path $args[6];} -ArgumentList $curDir,$password,$port,$testFile,$username,${uploadTo},$uploadStatusRandomFile
							Start-Sleep -Milliseconds 100
							$uploadJobStatus = Get-Job -Id $uploadJob.Id
							$uploadTimout = $false
							while (( $uploadJobStatus.State -eq "Running" ) -and ( !$uploadTimout ))
							{
								Write-Host "." -NoNewline
								$now = Get-Date
								if ( ($now - $uploadStartTime).TotalSeconds -gt 600 )
								{
									$uploadTimout = $true
									LogError "Upload Timout!"
								}
								Start-Sleep -Seconds 1
								$uploadJobStatus = Get-Job -Id $uploadJob.Id
							}
							$returnCode = Get-Content -Path $uploadStatusRandomFile
							Remove-Item -Force $uploadStatusRandomFile | Out-Null
							Remove-Job -Id $uploadJob.Id -Force | Out-Null
						}
						if(($returnCode -ne 0) -and ($retry -ne $maxRetry))
						{
							LogWarn "Error in upload, Attempt $retry. Retrying for upload"
							$retry=$retry+1
							WaitFor -seconds 10
						}
						elseif(($returnCode -ne 0) -and ($retry -eq $maxRetry))
						{
							Write-Output "Error in upload after $retry Attempt,Hence giving up"
							$retry=$retry+1
							Throw "Calling function - $($MyInvocation.MyCommand). Error in upload after $retry Attempt,Hence giving up"
						}
						elseif($returnCode -eq 0)
						{
							LogMsg "Upload Success after $retry Attempt"
							$retry=$maxRetry+1
						}
					}
				}
			}
		}
		else
		{
			LogMsg "No Files to upload...!"
			Throw "Calling function - $($MyInvocation.MyCommand). No Files to upload...!"
		}
	}
	elseif($download)
	{
#Downloading the files
		if ($files)
		{
			$files = $files.split(",")
			foreach ($f in $files)
			{
				$retry=1
				$maxRetry=50
				$testFile = $f.trim()
				while($retry -le $maxRetry)
				{
					if($usePrivateKey)
					{
						LogMsg "Downloading $testFile from $username : $downloadFrom,port $port to $downloadTo using PrivateKey authentication"
						$curDir = $PWD
						$downloadStatusRandomFile = ".\Temp\DownloadStatusFile" + (Get-Random -Maximum 9999 -Minimum 1111) + ".txt"
						$downloadStartTime = Get-Date
						$downloadJob = Start-Job -ScriptBlock { $curDir=$args[0];$sshKey=$args[1];$port=$args[2];$testFile=$args[3];$username=$args[4];${downloadFrom}=$args[5];$downloadTo=$args[6];$downloadStatusRandomFile=$args[7]; Set-Location $curDir; Set-Content -Value "1" -Path $args[6]; Write-Output "yes" | .\tools\pscp -i .\ssh\$sshKey -q -P $port $username@${downloadFrom}:$testFile $downloadTo; Set-Content -Value $LASTEXITCODE -Path $downloadStatusRandomFile;} -ArgumentList $curDir,$sshKey,$port,$testFile,$username,${downloadFrom},$downloadTo,$downloadStatusRandomFile
						Start-Sleep -Milliseconds 100
						$downloadJobStatus = Get-Job -Id $downloadJob.Id
						$downloadTimout = $false
						while (( $downloadJobStatus.State -eq "Running" ) -and ( !$downloadTimout ))
						{
							Write-Host "." -NoNewline
							$now = Get-Date
							if ( ($now - $downloadStartTime).TotalSeconds -gt 600 )
							{
								$downloadTimout = $true
								LogError "Download Timout!"
							}
							Start-Sleep -Seconds 1
							$downloadJobStatus = Get-Job -Id $downloadJob.Id
						}
						$returnCode = Get-Content -Path $downloadStatusRandomFile
						Remove-Item -Force $downloadStatusRandomFile | Out-Null
						Remove-Job -Id $downloadJob.Id -Force | Out-Null
					}
					else
					{
						LogMsg "Downloading $testFile from $username : $downloadFrom,port $port to $downloadTo using Password authentication"
						$curDir =  (Get-Item -Path ".\" -Verbose).FullName
						$downloadStatusRandomFile = ".\Temp\DownloadStatusFile" + (Get-Random -Maximum 9999 -Minimum 1111) + ".txt"
						Set-Content -Value "1" -Path $downloadStatusRandomFile
						$downloadStartTime = Get-Date
						$downloadJob = Start-Job -ScriptBlock {
							$curDir=$args[0];
							$password=$args[1];
							$port=$args[2];
							$testFile=$args[3];
							$username=$args[4];
							${downloadFrom}=$args[5];
							$downloadTo=$args[6];
							$downloadStatusRandomFile=$args[7];
							Set-Location $curDir;
							Write-Output "yes" | .\tools\pscp.exe  -v -2 -unsafe -pw $password -q -P $port $username@${downloadFrom}:$testFile $downloadTo 2> $downloadStatusRandomFile;
							Add-Content -Value "DownloadExtiCode_$LASTEXITCODE" -Path $downloadStatusRandomFile;
						} -ArgumentList $curDir,$password,$port,$testFile,$username,${downloadFrom},$downloadTo,$downloadStatusRandomFile
						Start-Sleep -Milliseconds 100
						$downloadJobStatus = Get-Job -Id $downloadJob.Id
						$downloadTimout = $false
						while (( $downloadJobStatus.State -eq "Running" ) -and ( !$downloadTimout ))
						{
							Write-Host "." -NoNewline
							$now = Get-Date
							if ( ($now - $downloadStartTime).TotalSeconds -gt 600 )
							{
								$downloadTimout = $true
								LogError "Download Timout!"
							}
							Start-Sleep -Seconds 1
							$downloadJobStatus = Get-Job -Id $downloadJob.Id
						}
						$downloadExitCode = (Select-String -Path $downloadStatusRandomFile -Pattern "DownloadExtiCode_").Line
						if ( $downloadExitCode )
						{
							$returnCode = $downloadExitCode.Replace("DownloadExtiCode_",'')
						}
						if ( $returnCode -eq 0)
						{
							LogMsg "Download command returned exit code 0"
						}
						else
						{
							$receivedFiles = Select-String -Path "$downloadStatusRandomFile" -Pattern "Sending file"
							if ($receivedFiles.Count -ge 1)
							{
								LogMsg "Received $($receivedFiles.Count) file(s)"
								$returnCode = 0
							}
							else
							{
								LogMsg "Download command returned exit code $returnCode"
								LogMsg "$(Get-Content -Path $downloadStatusRandomFile)"
							}
						}
						Remove-Item -Force $downloadStatusRandomFile | Out-Null
						Remove-Job -Id $downloadJob.Id -Force | Out-Null
					}
					if(($returnCode -ne 0) -and ($retry -ne $maxRetry))
					{
						LogWarn "Error in download, Attempt $retry. Retrying for download"
						$retry=$retry+1
					}
					elseif(($returnCode -ne 0) -and ($retry -eq $maxRetry))
					{
						Write-Output "Error in download after $retry Attempt,Hence giving up"
						$retry=$retry+1
						Throw "Calling function - $($MyInvocation.MyCommand). Error in download after $retry Attempt,Hence giving up."
					}
					elseif($returnCode -eq 0)
					{
						LogMsg "Download Success after $retry Attempt"
						$retry=$maxRetry+1
					}
				}
			}
		}
		else
		{
			LogMsg "No Files to download...!"
			Throw "Calling function - $($MyInvocation.MyCommand). No Files to download...!"
		}
	}
	else
	{
		LogMsg "Error: Upload/Download switch is not used!"
	}
}

Function WrapperCommandsToFile([string] $username,[string] $password,[string] $ip,[string] $command, [int] $port)
{
	if ( ( $lastLinuxCmd -eq $command) -and ($lastIP -eq $ip) -and ($lastPort -eq $port) `
		-and ($lastUser -eq $username) -and ($TestPlatform -ne "HyperV"))
	{
		#Skip upload if current command is same as last command.
	}
	else
	{
		Set-Variable -Name lastLinuxCmd -Value $command -Scope Global
		Set-Variable -Name lastIP -Value $ip -Scope Global
		Set-Variable -Name lastPort -Value $port -Scope Global
		Set-Variable -Name lastUser -Value $username -Scope Global
		$command | out-file -encoding ASCII -filepath "$LogDir\runtest.sh"
		RemoteCopy -upload -uploadTo $ip -username $username -port $port -password $password -files ".\$LogDir\runtest.sh"
		Remove-Item "$LogDir\runtest.sh"
	}
}

Function RunLinuxCmd([string] $username,[string] $password,[string] $ip,[string] $command, [int] $port, [switch]$runAsSudo, [Boolean]$WriteHostOnly, [Boolean]$NoLogsPlease, [switch]$ignoreLinuxExitCode, [int]$runMaxAllowedTime = 300, [switch]$RunInBackGround, [int]$maxRetryCount = 20)
{
	if ($detectedDistro -ne "COREOS" )
	{
		WrapperCommandsToFile $username $password $ip $command $port
	}
	$randomFileName = [System.IO.Path]::GetRandomFileName()
	if ( $maxRetryCount -eq 0)
	{
		$maxRetryCount = 1
	}
	$currentDir = $PWD.Path
	$RunStartTime = Get-Date

	if($runAsSudo)
	{
		$plainTextPassword = $password.Replace('"','');
		if ( $detectedDistro -eq "COREOS" )
		{
			$linuxCommand = "`"export PATH=/usr/share/oem/python/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/share/oem/bin:/opt/bin && echo $plainTextPassword | sudo -S env `"PATH=`$PATH`" $command && echo AZURE-LINUX-EXIT-CODE-`$? || echo AZURE-LINUX-EXIT-CODE-`$?`""
			$logCommand = "`"export PATH=/usr/share/oem/python/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/share/oem/bin:/opt/bin && echo $plainTextPassword | sudo -S env `"PATH=`$PATH`" $command`""
		}
		else
		{
			$linuxCommand = "`"echo $plainTextPassword | sudo -S bash -c `'bash runtest.sh ; echo AZURE-LINUX-EXIT-CODE-`$?`' `""
			$logCommand = "`"echo $plainTextPassword | sudo -S $command`""
		}
	}
	else
	{
		if ( $detectedDistro -eq "COREOS" )
		{
			$linuxCommand = "`"export PATH=/usr/share/oem/python/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/share/oem/bin:/opt/bin && $command && echo AZURE-LINUX-EXIT-CODE-`$? || echo AZURE-LINUX-EXIT-CODE-`$?`""
			$logCommand = "`"export PATH=/usr/share/oem/python/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/share/oem/bin:/opt/bin && $command`""
		}
		else
		{
			$linuxCommand = "`"bash -c `'bash runtest.sh ; echo AZURE-LINUX-EXIT-CODE-`$?`' `""
			$logCommand = "`"$command`""
		}
	}
	LogMsg ".\tools\plink.exe -t -pw $password -P $port $username@$ip $logCommand"
	$returnCode = 1
	$attemptswt = 0
	$attemptswot = 0
	$notExceededTimeLimit = $true
	$isBackGroundProcessStarted = $false

	while ( ($returnCode -ne 0) -and ($attemptswt -lt $maxRetryCount -or $attemptswot -lt $maxRetryCount) -and $notExceededTimeLimit)
	{
		if ($runwithoutt -or $attemptswt -eq $maxRetryCount)
		{
			Set-Variable -Name runwithoutt -Value true -Scope Global
			$attemptswot +=1
			$runLinuxCmdJob = Start-Job -ScriptBlock `
			{ `
				$username = $args[1]; $password = $args[2]; $ip = $args[3]; $port = $args[4]; $jcommand = $args[5]; `
				Set-Location $args[0]; `
				.\tools\plink.exe -C -v -pw $password -P $port $username@$ip $jcommand;`
			} `
			-ArgumentList $currentDir, $username, $password, $ip, $port, $linuxCommand
		}
		else
		{
			$attemptswt += 1
			$runLinuxCmdJob = Start-Job -ScriptBlock `
			{ `
				$username = $args[1]; $password = $args[2]; $ip = $args[3]; $port = $args[4]; $jcommand = $args[5]; `
				Set-Location $args[0]; `
				.\tools\plink.exe -t -C -v -pw $password -P $port $username@$ip $jcommand;`
			} `
			-ArgumentList $currentDir, $username, $password, $ip, $port, $linuxCommand
		}
		$RunLinuxCmdOutput = ""
		$debugOutput = ""
		$LinuxExitCode = ""
		if ( $RunInBackGround )
		{
			While(($runLinuxCmdJob.State -eq "Running") -and ($isBackGroundProcessStarted -eq $false ) -and $notExceededTimeLimit)
			{
				$SSHOut = Receive-Job $runLinuxCmdJob 2> $LogDir\$randomFileName
				$jobOut = Get-Content $LogDir\$randomFileName
				if($jobOut)
				{
					foreach($outLine in $jobOut)
					{
						if($outLine -imatch "Started a shell")
						{
							$LinuxExitCode = $outLine
							$isBackGroundProcessStarted = $true
							$returnCode = 0
						}
						else
						{
							$RunLinuxCmdOutput += "$outLine`n"
						}
					}
				}
				$debugLines = Get-Content $LogDir\$randomFileName
				if($debugLines)
				{
					$debugString = ""
					foreach ($line in $debugLines)
					{
						$debugString += $line
					}
					$debugOutput += "$debugString`n"
				}
				Write-Progress -Activity "Attempt : $attemptswot+$attemptswt : Initiating command in Background Mode : $logCommand on $ip : $port" -Status "Timeout in $($RunMaxAllowedTime - $RunElaplsedTime) seconds.." -Id 87678 -PercentComplete (($RunElaplsedTime/$RunMaxAllowedTime)*100) -CurrentOperation "SSH ACTIVITY : $debugString"
				$RunCurrentTime = Get-Date
				$RunDiffTime = $RunCurrentTime - $RunStartTime
				$RunElaplsedTime =  $RunDiffTime.TotalSeconds
				if($RunElaplsedTime -le $RunMaxAllowedTime)
				{
					$notExceededTimeLimit = $true
				}
				else
				{
					$notExceededTimeLimit = $false
					Stop-Job $runLinuxCmdJob
					$timeOut = $true
				}
			}
			WaitFor -seconds 2
			$SSHOut = Receive-Job $runLinuxCmdJob 2> $LogDir\$randomFileName
			if($SSHOut )
			{
				foreach ($outLine in $SSHOut)
				{
					if($outLine -imatch "AZURE-LINUX-EXIT-CODE-")
					{
						$LinuxExitCode = $outLine
						$isBackGroundProcessTerminated = $true
					}
					else
					{
						$RunLinuxCmdOutput += "$outLine`n"
					}
				}
			}

			$debugLines = Get-Content $LogDir\$randomFileName
			if($debugLines)
			{
				$debugString = ""
				foreach ($line in $debugLines)
				{
					$debugString += $line
				}
				$debugOutput += "$debugString`n"
			}
			Write-Progress -Activity "Attempt : $attemptswot+$attemptswt : Executing $logCommand on $ip : $port" -Status $runLinuxCmdJob.State -Id 87678 -SecondsRemaining ($RunMaxAllowedTime - $RunElaplsedTime) -Completed
			if ( $isBackGroundProcessStarted -and !$isBackGroundProcessTerminated )
			{
				LogMsg "$command is running in background with ID $($runLinuxCmdJob.Id) ..."
				Add-Content -Path $LogDir\CurrentTestBackgroundJobs.txt -Value $runLinuxCmdJob.Id
				$retValue = $runLinuxCmdJob.Id
			}
			else
			{
				Remove-Job $runLinuxCmdJob
				if (!$isBackGroundProcessStarted)
				{
					LogError "Failed to start process in background.."
				}
				if ( $isBackGroundProcessTerminated )
				{
					LogError "Background Process terminated from Linux side with error code :  $($LinuxExitCode.Split("-")[4])"
					$returnCode = $($LinuxExitCode.Split("-")[4])
					LogError $SSHOut
				}
				if($debugOutput -imatch "Unable to authenticate")
				{
					LogMsg "Unable to authenticate. Not retrying!"
					Throw "Calling function - $($MyInvocation.MyCommand). Unable to authenticate"

				}
				if($timeOut)
				{
					$retValue = ""
					Throw "Calling function - $($MyInvocation.MyCommand). Tmeout while executing command : $command"
				}
				LogError "Linux machine returned exit code : $($LinuxExitCode.Split("-")[4])"
				if ($attempts -eq $maxRetryCount)
				{
					Throw "Calling function - $($MyInvocation.MyCommand). Failed to execute : $command."
				}
				else
				{
					if ($notExceededTimeLimit)
					{
						LogMsg "Failed to execute : $command. Retrying..."
					}
				}
			}
			Remove-Item $LogDir\$randomFileName -Force | Out-Null
		}
		else
		{
			While($notExceededTimeLimit -and ($runLinuxCmdJob.State -eq "Running"))
			{
				$jobOut = Receive-Job $runLinuxCmdJob 2> $LogDir\$randomFileName
				if($jobOut)
				{
					$jobOut = $jobOut.Replace("[sudo] password for $username`: ","")
					foreach ($outLine in $jobOut)
					{
						if($outLine -imatch "AZURE-LINUX-EXIT-CODE-")
						{
							$LinuxExitCode = $outLine
						}
						else
						{
							$RunLinuxCmdOutput += "$outLine`n"
						}
					}
				}
				$debugLines = Get-Content $LogDir\$randomFileName
				if($debugLines)
				{
					$debugString = ""
					foreach ($line in $debugLines)
					{
						$debugString += $line
					}
					$debugOutput += "$debugString`n"
				}
				Write-Progress -Activity "Attempt : $attemptswot+$attemptswt : Executing $logCommand on $ip : $port" -Status "Timeout in $($RunMaxAllowedTime - $RunElaplsedTime) seconds.." -Id 87678 -PercentComplete (($RunElaplsedTime/$RunMaxAllowedTime)*100) -CurrentOperation "SSH ACTIVITY : $debugString"
				$RunCurrentTime = Get-Date
				$RunDiffTime = $RunCurrentTime - $RunStartTime
				$RunElaplsedTime =  $RunDiffTime.TotalSeconds
				if($RunElaplsedTime -le $RunMaxAllowedTime)
				{
					$notExceededTimeLimit = $true
				}
				else
				{
					$notExceededTimeLimit = $false
					Stop-Job $runLinuxCmdJob
					$timeOut = $true
				}
			}
			$jobOut = Receive-Job $runLinuxCmdJob 2> $LogDir\$randomFileName
			if($jobOut)
			{
				$jobOut = $jobOut.Replace("[sudo] password for $username`: ","")
				foreach ($outLine in $jobOut)
				{
					if($outLine -imatch "AZURE-LINUX-EXIT-CODE-")
					{
						$LinuxExitCode = $outLine
					}
					else
					{
						$RunLinuxCmdOutput += "$outLine`n"
					}
				}
			}
			$debugLines = Get-Content $LogDir\$randomFileName
			if($debugLines)
			{
				$debugString = ""
				foreach ($line in $debugLines)
				{
					$debugString += $line
				}
				$debugOutput += "$debugString`n"
			}
			Write-Progress -Activity "Attempt : $attemptswot+$attemptswt : Executing $logCommand on $ip : $port" -Status $runLinuxCmdJob.State -Id 87678 -SecondsRemaining ($RunMaxAllowedTime - $RunElaplsedTime) -Completed
			Remove-Job $runLinuxCmdJob
			Remove-Item $LogDir\$randomFileName -Force | Out-Null
			if ($LinuxExitCode -imatch "AZURE-LINUX-EXIT-CODE-0")
			{
				$returnCode = 0
				LogMsg "$command executed successfully in $([math]::Round($RunElaplsedTime,2)) seconds." -WriteHostOnly $WriteHostOnly -NoLogsPlease $NoLogsPlease
				$retValue = $RunLinuxCmdOutput.Trim()
			}
			else
			{
				if (!$ignoreLinuxExitCode)
				{
					$debugOutput = ($debugOutput.Split("`n")).Trim()
					foreach ($line in $debugOutput)
					{
						if($line)
						{
							LogError $line
						}
					}
				}
				if($debugOutput -imatch "Unable to authenticate")
					{
						LogMsg "Unable to authenticate. Not retrying!"
						Throw "Calling function - $($MyInvocation.MyCommand). Unable to authenticate"

					}
				if(!$ignoreLinuxExitCode)
				{
					if($timeOut)
					{
						$retValue = ""
						LogError "Tmeout while executing command : $command"
					}
					LogError "Linux machine returned exit code : $($LinuxExitCode.Split("-")[4])"
					if ($attemptswt -eq $maxRetryCount -and $attemptswot -eq $maxRetryCount)
					{
						Throw "Calling function - $($MyInvocation.MyCommand). Failed to execute : $command."
					}
					else
					{
						if ($notExceededTimeLimit)
						{
							LogError "Failed to execute : $command. Retrying..."
						}
					}
				}
				else
				{
					LogMsg "Command execution returned return code $($LinuxExitCode.Split("-")[4]) Ignoring.."
					$retValue = $RunLinuxCmdOutput.Trim()
					break
				}
			}
		}
	}
	return $retValue
}
#endregion

#region Test Case Logging
Function DoTestCleanUp($CurrentTestResult, $testName, $DeployedServices, $ResourceGroups, [switch]$keepUserDirectory, [switch]$SkipVerifyKernelLogs)
{
	try
	{
		$result = $CurrentTestResult.TestResult

		if($ResourceGroups)
		{
			if(!$IsWindows){
				try
				{
					if ($allVMData.Count -gt 1)
					{
						$vmData = $allVMData[0]
					}
					else
					{
						$vmData = $allVMData
					}
					$FilesToDownload = "$($vmData.RoleName)-*.txt"
					$Null = RemoteCopy -upload -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files .\Testscripts\Linux\CollectLogFile.sh -username $user -password $password
					$Null = RunLinuxCmd -username $user -password $password -ip $vmData.PublicIP -port $vmData.SSHPort -command "bash CollectLogFile.sh" -ignoreLinuxExitCode -runAsSudo
					$Null = RemoteCopy -downloadFrom $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -files "$FilesToDownload" -downloadTo "$LogDir" -download
					$KernelVersion = Get-Content "$LogDir\$($vmData.RoleName)-kernelVersion.txt"
					$GuestDistro = Get-Content "$LogDir\$($vmData.RoleName)-distroVersion.txt"
					$LISMatch = (Select-String -Path "$LogDir\$($vmData.RoleName)-lis.txt" -Pattern "^version:").Line
					if ($LISMatch)
					{
						$LISVersion = $LISMatch.Split(":").Trim()[1]
					}
					else
					{
						$LISVersion = "NA"
					}
					#region Host Version checking
					$FoundLineNumber = (Select-String -Path "$LogDir\$($vmData.RoleName)-dmesg.txt" -Pattern "Hyper-V Host Build").LineNumber
					$ActualLineNumber = $FoundLineNumber - 1
					$FinalLine = (Get-Content -Path "$LogDir\$($vmData.RoleName)-dmesg.txt")[$ActualLineNumber]
					$FinalLine = $FinalLine.Replace('; Vmbus version:4.0','')
					$FinalLine = $FinalLine.Replace('; Vmbus version:3.0','')
					$HostVersion = ($FinalLine.Split(":")[$FinalLine.Split(":").Count -1 ]).Trim().TrimEnd(";")
					#endregion

					if($EnableAcceleratedNetworking -or ($currentTestData.AdditionalHWConfig.Networking -imatch "SRIOV"))
					{
						$Networking = "SRIOV"
					}
					else
					{
						$Networking = "Synthetic"
					}
					if ($TestPlatform -eq "Azure")
					{
						$VMSize = $vmData.InstanceSize
					}
					if ( $TestPlatform -eq "HyperV")
					{
						$VMSize = $HyperVInstanceSize
					}
					#endregion
					$SQLQuery = Get-SQLQueryOfTelemetryData -TestPlatform $TestPlatform -TestLocation $TestLocation -TestCategory $TestCategory `
					-TestArea $TestArea -TestName $CurrentTestData.TestName -CurrentTestResult $CurrentTestResult `
					-ExecutionTag $ResultDBTestTag -GuestDistro $GuestDistro -KernelVersion $KernelVersion `
					-LISVersion $LISVersion -HostVersion $HostVersion -VMSize $VMSize -Networking $Networking `
					-ARMImage $ARMImage -OsVHD $OsVHD -BuildURL $env:BUILD_URL
					if($SQLQuery)
					{
						UploadTestResultToDatabase -SQLQuery $SQLQuery
					}
				}
				catch
				{
					$line = $_.InvocationInfo.ScriptLineNumber
					$script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
					$ErrorMessage =  $_.Exception.Message
					LogError "EXCEPTION : $ErrorMessage"
					LogError "Source : Line $line in script $script_name."
					LogError "Ignorable error in collecting final data from VMs."
				}
			}
			$currentTestBackgroundJobs = Get-Content $LogDir\CurrentTestBackgroundJobs.txt -ErrorAction SilentlyContinue
			if ( $currentTestBackgroundJobs )
			{
				$currentTestBackgroundJobs = $currentTestBackgroundJobs.Split()
			}
			foreach ( $taskID in $currentTestBackgroundJobs )
			{
				#Removal of background
				LogMsg "Removing Background Job ID : $taskID..."
				Remove-Job -Id $taskID -Force
				Remove-Item $LogDir\CurrentTestBackgroundJobs.txt -ErrorAction SilentlyContinue
			}
			$user=$xmlConfig.config.$TestPlatform.Deployment.Data.UserName
			if ( !$SkipVerifyKernelLogs )
			{
				try
				{
					$Null=GetAndCheckKernelLogs -allDeployedVMs $allVMData -status "Final"
				}
				catch
				{
					$ErrorMessage =  $_.Exception.Message
					LogMsg "EXCEPTION in GetAndCheckKernelLogs(): $ErrorMessage"
				}
			}
			$isCleaned = @()
			$ResourceGroups = $ResourceGroups.Split("^")
			if(!$IsWindows){
				$isVMLogsCollected = $false
			} else {
				$isVMLogsCollected = $true
			}
			foreach ($group in $ResourceGroups)
			{
				if ($ForceDeleteResources)
				{
					LogMsg "-ForceDeleteResources is Set. Deleting $group."
					if ($TestPlatform -eq "Azure")
					{
						$isCleaned = DeleteResourceGroup -RGName $group

					}
					elseif ($TestPlatform -eq "HyperV")
					{
						foreach($vmData in $allVMData)
						{
							if($group -eq $vmData.HyperVGroupName)
							{
								$isCleaned = DeleteHyperVGroup -HyperVGroupName $group -HyperVHost $vmData.HyperVHost
								if (Get-Variable 'DependencyVmHost' -Scope 'Global' -EA 'Ig') {
									if ($DependencyVmHost -ne $vmData.HyperVHost) {
										DeleteHyperVGroup -HyperVGroupName $group -HyperVHost $DependencyVmHost
									}
								}
							}
						}
					}
					if (!$isCleaned)
					{
						LogMsg "CleanUP unsuccessful for $group.. Please delete the services manually."
					}
					else
					{
						LogMsg "CleanUP Successful for $group.."
					}
				}
				else
				{
					if($result -eq "PASS")
					{
						if($EconomyMode -and (-not $IsLastCaseInCycle))
						{
							LogMsg "Skipping cleanup of Resource Group : $group."
							if(!$keepUserDirectory)
							{
								RemoveAllFilesFromHomeDirectory -allDeployedVMs $allVMData
							}
						}
						else
						{
							try
							{
								$RGdetails = Get-AzureRmResourceGroup -Name $group -ErrorAction SilentlyContinue
							}
							catch
							{
								LogMsg "Resource group '$group' not found."
							}
							if ( $RGdetails.Tags )
							{
								if ( (  $RGdetails.Tags[0].Name -eq $preserveKeyword ) -and (  $RGdetails.Tags[0].Value -eq "yes" ))
								{
									LogMsg "Skipping Cleanup of preserved resource group."
									LogMsg "Collecting VM logs.."
									if ( !$isVMLogsCollected)
									{
										GetVMLogs -allVMData $allVMData
									}
									$isVMLogsCollected = $true
								}
							}
							else
							{
								if ( $DoNotDeleteVMs )
								{
									LogMsg "Skipping cleanup due to 'DoNotDeleteVMs' flag is set."
								}
								else
								{
									LogMsg "Cleaning up deployed test virtual machines."
									if ($TestPlatform -eq "Azure")
									{
										$isCleaned = DeleteResourceGroup -RGName $group

									}
									elseif ($TestPlatform -eq "HyperV")
									{
										foreach($vmData in $allVMData)
										{
											if($group -eq $vmData.HyperVGroupName)
											{
												$isCleaned = DeleteHyperVGroup -HyperVGroupName $group -HyperVHost $vmData.HyperVHost
												if (Get-Variable 'DependencyVmHost' -Scope 'Global' -EA 'Ig') {
													if ($DependencyVmHost -ne $vmData.HyperVHost) {
														DeleteHyperVGroup -HyperVGroupName $group -HyperVHost $DependencyVmHost
													}
												}
											}
										}
									}
									if (!$isCleaned)
									{
										LogMsg "CleanUP unsuccessful for $group.. Please delete the services manually."
									}
									else
									{
										LogMsg "CleanUP Successful for $group.."
									}
								}
							}
						}
					}
					else
					{
						LogMsg "Preserving the Resource Group(s) $group"
						if ($TestPlatform -eq "Azure")
						{
							Add-ResourceGroupTag -ResourceGroup $group -TagName $preserveKeyword -TagValue "yes"
						}
						LogMsg "Collecting VM logs.."
						if ( !$isVMLogsCollected)
						{
							GetVMLogs -allVMData $allVMData
						}
						$isVMLogsCollected = $true
						if(!$keepUserDirectory -and !$DoNotDeleteVMs -and $EconomyMode)
						{
							RemoveAllFilesFromHomeDirectory -allDeployedVMs $allVMData
						}
						if($DoNotDeleteVMs)
						{
							$xmlConfig.config.$TestPlatform.Deployment.$setupType.isDeployed = "NO"
						}
					}
				}
			}
		}
		else
		{
			$SQLQuery = Get-SQLQueryOfTelemetryData -TestPlatform $TestPlatform -TestLocation $TestLocation -TestCategory $TestCategory `
			-TestArea $TestArea -TestName $CurrentTestData.TestName -CurrentTestResult $CurrentTestResult `
			-ExecutionTag $ResultDBTestTag -GuestDistro $GuestDistro -KernelVersion $KernelVersion `
			-LISVersion $LISVersion -HostVersion $HostVersion -VMSize $VMSize -Networking $Networking `
			-ARMImage $ARMImage -OsVHD $OsVHD -BuildURL $env:BUILD_URL
			if($SQLQuery)
			{
				UploadTestResultToDatabase -SQLQuery $SQLQuery
			}
			LogMsg "Skipping cleanup, as No services / resource groups / HyperV Groups deployed for cleanup!"
		}
	}
	catch
	{
		$ErrorMessage =  $_.Exception.Message
		Write-Output "EXCEPTION in DoTestCleanUp : $ErrorMessage"
	}
}

Function GetFinalizedResult($resultArr, $checkValues, $subtestValues, $currentTestData)
{
	$result = "", ""
	if (($resultArr -contains "FAIL") -or ($resultArr -contains "Aborted")) {
		$result[0] = "FAIL"
	}
	else{
		$result[0] = "PASS"
	}
	$i = 0
	$subtestLen = $SubtestValues.Length
	while ($i -lt $subtestLen)
	{
		$currentTestValue = $SubtestValues[$i]
		$currentTestResult = $resultArr[$i]
		$currentTestName = $currentTestData.testName
		if ($checkValues -imatch $currentTestResult)
		{
			$result[1] += "			$currentTestName : $currentTestValue : $currentTestResult <br />"
		}
		$i = $i + 1
	}
	return $result
}

Function CreateResultSummary($testResult, $checkValues, $testName, $metaData)
{
	if ( $metaData )
	{
		$resultString = "	$metaData : $testResult <br />"
	}
	else
	{
		$resultString = "	$testResult <br />"
	}
	return $resultString
}

Function GetFinalResultHeader($resultArr){
	if(($resultArr -imatch "FAIL" ) -or ($resultArr -imatch "Aborted"))
	{
		$result = "FAIL"
		if($resultArr -imatch "Aborted")
		{
			$result = "Aborted"
		}
	}
	else
	{
		$result = "PASS"
	}
	return $result
}

Function SetStopWatch($str)
{
	$sw = [system.diagnostics.stopwatch]::startNew()
	return $sw
}

Function GetStopWatchElapasedTime([System.Diagnostics.Stopwatch]$sw, [string] $format)
{
	if ($format -eq "ss")
	{
		$num=$sw.Elapsed.TotalSeconds
	}
	elseif ($format -eq "hh")
	{
		$num=$sw.Elapsed.TotalHours
	}
	elseif ($format -eq "mm")
	{
		$num=$sw.Elapsed.TotalMinutes
	}
	return [System.Math]::Round($Num, 2)

}

Function GetVMLogs($allVMData)
{
	foreach ($testVM in $allVMData)
	{
		$testIP = $testVM.PublicIP
		$testPort = $testVM.SSHPort
		$LisLogFile = "LIS-Logs" + ".tgz"
		try
		{
			LogMsg "Collecting logs from IP : $testIP PORT : $testPort"
			RemoteCopy -upload -uploadTo $testIP -username $user -port $testPort -password $password -files '.\Testscripts\Linux\CORE-LogCollector.sh'
			RunLinuxCmd -username $user -password $password -ip $testIP -port $testPort -command 'chmod +x CORE-LogCollector.sh'
			$out = RunLinuxCmd -username $user -password $password -ip $testIP -port $testPort -command './CORE-LogCollector.sh -v' -runAsSudo
			LogMsg $out
			RemoteCopy -download -downloadFrom $testIP -username $user -password $password -port $testPort -downloadTo $LogDir -files $LisLogFile
			LogMsg "Logs collected successfully from IP : $testIP PORT : $testPort"
			if ($TestPlatform -eq "Azure")
			{
				Rename-Item -Path "$LogDir\$LisLogFile" -NewName ("LIS-Logs-" + $testVM.RoleName + ".tgz") -Force
			}
		}
		catch
		{
			$ErrorMessage =  $_.Exception.Message
			LogError "EXCEPTION : $ErrorMessage"
			LogError "Unable to collect logs from IP : $testIP PORT : $testPort"
		}
	}
}

Function RemoveAllFilesFromHomeDirectory($allDeployedVMs)
{
	foreach ($DeployedVM in $allDeployedVMs)
	{
		$testIP = $DeployedVM.PublicIP
		$testPort = $DeployedVM.SSHPort
		try
		{
			LogMsg "Removing all files logs from IP : $testIP PORT : $testPort"
			$Null = RunLinuxCmd -username $user -password $password -ip $testIP -port $testPort -command 'rm -rf *' -runAsSudo
			LogMsg "All files removed from /home/$user successfully. VM IP : $testIP PORT : $testPort"
		}
		catch
		{
			$ErrorMessage =  $_.Exception.Message
			Write-Output "EXCEPTION : $ErrorMessage"
			Write-Output "Unable to remove files from IP : $testIP PORT : $testPort"
		}
	}
}

Function GetAllDeployementData($ResourceGroups)
{
	$allDeployedVMs = @()
	function CreateQuickVMNode()
	{
		$objNode = New-Object -TypeName PSObject
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name ServiceName -Value $ServiceName -Force
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name ResourceGroupName -Value $ResourceGroupName -Force
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name Location -Value $ResourceGroupName -Force
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name RoleName -Value $RoleName -Force
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name PublicIP -Value $PublicIP -Force
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name PublicIPv6 -Value $PublicIP -Force
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name InternalIP -Value $InternalIP -Force
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name SecondInternalIP -Value $SecondInternalIP -Force
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name URL -Value $URL -Force
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name URLv6 -Value $URL -Force
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name Status -Value $Status -Force
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name InstanceSize -Value $InstanceSize -Force
		return $objNode
	}

	foreach ($ResourceGroup in $ResourceGroups.Split("^"))
	{
		LogMsg "Collecting $ResourceGroup data.."

		LogMsg "	Microsoft.Network/publicIPAddresses data collection in progress.."
		$RGIPdata = Get-AzureRmResource -ResourceGroupName $ResourceGroup -ResourceType "Microsoft.Network/publicIPAddresses" -Verbose -ExpandProperties
		LogMsg "	Microsoft.Compute/virtualMachines data collection in progress.."
		$RGVMs = Get-AzureRmResource -ResourceGroupName $ResourceGroup -ResourceType "Microsoft.Compute/virtualMachines" -Verbose -ExpandProperties
		LogMsg "	Microsoft.Network/networkInterfaces data collection in progress.."
		$NICdata = Get-AzureRmResource -ResourceGroupName $ResourceGroup -ResourceType "Microsoft.Network/networkInterfaces" -Verbose -ExpandProperties
		$currentRGLocation = (Get-AzureRmResourceGroup -ResourceGroupName $ResourceGroup).Location
		LogMsg "	Microsoft.Network/loadBalancers data collection in progress.."
		$LBdata = Get-AzureRmResource -ResourceGroupName $ResourceGroup -ResourceType "Microsoft.Network/loadBalancers" -ExpandProperties -Verbose
		foreach ($testVM in $RGVMs)
		{
			$QuickVMNode = CreateQuickVMNode
			$InboundNatRules = $LBdata.Properties.InboundNatRules
			foreach ($endPoint in $InboundNatRules)
			{
				if ( $endPoint.Name -imatch $testVM.ResourceName)
				{
					$endPointName = "$($endPoint.Name)".Replace("$($testVM.ResourceName)-","")
					Add-Member -InputObject $QuickVMNode -MemberType NoteProperty -Name "$($endPointName)Port" -Value $endPoint.Properties.FrontendPort -Force
				}
			}
			$LoadBalancingRules = $LBdata.Properties.LoadBalancingRules
			foreach ( $LBrule in $LoadBalancingRules )
			{
				if ( $LBrule.Name -imatch "$ResourceGroup-LB-" )
				{
					$endPointName = "$($LBrule.Name)".Replace("$ResourceGroup-LB-","")
					Add-Member -InputObject $QuickVMNode -MemberType NoteProperty -Name "$($endPointName)Port" -Value $LBrule.Properties.FrontendPort -Force
				}
			}
			$Probes = $LBdata.Properties.Probes
			foreach ( $Probe in $Probes )
			{
				if ( $Probe.Name -imatch "$ResourceGroup-LB-" )
				{
					$probeName = "$($Probe.Name)".Replace("$ResourceGroup-LB-","").Replace("-probe","")
					Add-Member -InputObject $QuickVMNode -MemberType NoteProperty -Name "$($probeName)ProbePort" -Value $Probe.Properties.Port -Force
				}
			}

			foreach ( $nic in $NICdata )
			{
				if (( $nic.Name -imatch $testVM.ResourceName) -and ( $nic.Name -imatch "PrimaryNIC"))
				{
					$QuickVMNode.InternalIP = "$($nic.Properties.IpConfigurations[0].Properties.PrivateIPAddress)"
				}
				if (( $nic.Name -imatch $testVM.ResourceName) -and ( $nic.Name -imatch "ExtraNetworkCard-1"))
				{
					$QuickVMNode.SecondInternalIP = "$($nic.Properties.IpConfigurations[0].Properties.PrivateIPAddress)"
				}
			}
			$QuickVMNode.ResourceGroupName = $ResourceGroup

			$QuickVMNode.PublicIP = ($RGIPData | Where-Object { $_.Properties.publicIPAddressVersion -eq "IPv4" }).Properties.ipAddress
			$QuickVMNode.PublicIPv6 = ($RGIPData | Where-Object { $_.Properties.publicIPAddressVersion -eq "IPv6" }).Properties.ipAddress
			$QuickVMNode.URL = ($RGIPData | Where-Object { $_.Properties.publicIPAddressVersion -eq "IPv4" }).Properties.dnsSettings.fqdn
			$QuickVMNode.URLv6 = ($RGIPData | Where-Object { $_.Properties.publicIPAddressVersion -eq "IPv6" }).Properties.dnsSettings.fqdn
			$QuickVMNode.RoleName = $testVM.ResourceName
			$QuickVMNode.Status = $testVM.Properties.ProvisioningState
			$QuickVMNode.InstanceSize = $testVM.Properties.hardwareProfile.vmSize
			$QuickVMNode.Location = $currentRGLocation
			$allDeployedVMs += $QuickVMNode
		}
		LogMsg "Collected $ResourceGroup data!"
	}
	Set-Variable -Name AllVMData -Value $allDeployedVMs -Scope Global
	return $allDeployedVMs
}

Function RestartAllDeployments($allVMData)
{
	if ($TestPlatform -eq "Azure")
	{
		$RestartStatus = RestartAllAzureDeployments -allVMData $allVMData
	}
	elseif ($TestPlatform -eq "HyperV")
	{
		$RestartStatus = RestartAllHyperVDeployments -allVMData $allVMData
	}
	else
	{
		LogErr "Function RestartAllDeployments does not support '$TestPlatform' Test platform."
		$RestartStatus = "False"
	}
	return $RestartStatus
}

Function GetTotalPhysicalDisks($FdiskOutput)
{
	$physicalDiskNames = ("sda","sdb","sdc","sdd","sde","sdf","sdg","sdh","sdi","sdj","sdk","sdl","sdm","sdn",
			"sdo","sdp","sdq","sdr","sds","sdt","sdu","sdv","sdw","sdx","sdy","sdz", "sdaa", "sdab", "sdac", "sdad","sdae", "sdaf", "sdag", "sdah", "sdai")
	$diskCount = 0
	foreach ($physicalDiskName in $physicalDiskNames)
	{
		if ($FdiskOutput -imatch "Disk /dev/$physicalDiskName")
		{
			$diskCount += 1
		}
	}
	return $diskCount
}

Function GetNewPhysicalDiskNames($FdiskOutputBeforeAddingDisk, $FdiskOutputAfterAddingDisk)
{
	$availableDisksBeforeAddingDisk = ""
	$availableDisksAfterAddingDisk = ""
	$physicalDiskNames = ("sda","sdb","sdc","sdd","sde","sdf","sdg","sdh","sdi","sdj","sdk","sdl","sdm","sdn",
			"sdo","sdp","sdq","sdr","sds","sdt","sdu","sdv","sdw","sdx","sdy","sdz", "sdaa", "sdab", "sdac", "sdad","sdae", "sdaf", "sdag", "sdah", "sdai")
	foreach ($physicalDiskName in $physicalDiskNames)
	{
		if ($FdiskOutputBeforeAddingDisk -imatch "Disk /dev/$physicalDiskName")
		{
			if ( $availableDisksBeforeAddingDisk -eq "" )
			{
				$availableDisksBeforeAddingDisk = "/dev/$physicalDiskName"
			}
			else
			{
				$availableDisksBeforeAddingDisk = $availableDisksBeforeAddingDisk + "^" + "/dev/$physicalDiskName"
			}
		}
	}
	foreach ($physicalDiskName in $physicalDiskNames)
	{
		if ($FdiskOutputAfterAddingDisk -imatch "Disk /dev/$physicalDiskName")
		{
			if ( $availableDisksAfterAddingDisk -eq "" )
			{
				$availableDisksAfterAddingDisk = "/dev/$physicalDiskName"
			}
			else
			{
				$availableDisksAfterAddingDisk = $availableDisksAfterAddingDisk + "^" + "/dev/$physicalDiskName"
			}
		}
	}
	$newDisks = ""
	foreach ($afterDisk in $availableDisksAfterAddingDisk.Split("^"))
	{
		if($availableDisksBeforeAddingDisk -imatch $afterDisk)
		{

		}
		else
		{
			if($newDisks -eq "")
			{
				$newDisks = $afterDisk
			}
			else
			{
				$newDisks = $newDisks + "^" + $afterDisk
			}
		}
	}
	return $newDisks
}

Function PerformIOTestOnDisk($testVMObject, [string]$attachedDisk, [string]$diskFileSystem)
{
	$retValue = "Aborted"
	$testVMSSHport = $testVMObject.sshPort
	$testVMVIP = $testVMObject.ip
	$testVMUsername = $testVMObject.user
	$testVMPassword = $testVMObject.password
	if ( $diskFileSystem -imatch "xfs" )
	{
		$diskFileSystem = "xfs -f"
	}
	$isVMAlive = Test-TCP -testIP $testVMVIP -testport $testVMSSHport
	if ($isVMAlive -eq "True")
	{
		$retValue = "FAIL"
		$mountPoint = "/mnt/datadisk"
		LogMsg "Performing I/O operations on $attachedDisk.."
		$LogPath = "$LogDir\VerifyIO$($attachedDisk.Replace('/','-')).txt"
		$dmesgBefore = RunLinuxCmd -username $testVMUsername -password $testVMPassword -ip $testVMVIP -port $testVMSSHport -command "dmesg" -runMaxAllowedTime 30 -runAsSudo
		#CREATE A MOUNT DIRECTORY
		$Null = RunLinuxCmd -username $testVMUsername -password $testVMPassword -ip $testVMVIP -port $testVMSSHport -command "mkdir -p $mountPoint" -runAsSudo
		$partitionNumber=1
		$Null = RunLinuxCmd -username $testVMUsername -password $testVMPassword -ip $testVMVIP -port $testVMSSHport -command "./ManagePartitionOnDisk.sh -diskName $attachedDisk -create yes -forRaid no" -runAsSudo
		$FormatDiskOut = RunLinuxCmd -username $testVMUsername -password $testVMPassword -ip $testVMVIP -port $testVMSSHport -command "time mkfs.$diskFileSystem $attachedDisk$partitionNumber" -runAsSudo -runMaxAllowedTime 2400
		$Null = RunLinuxCmd -username $testVMUsername -password $testVMPassword -ip $testVMVIP -port $testVMSSHport -command "mount -o nobarrier $attachedDisk$partitionNumber $mountPoint" -runAsSudo
		Add-Content -Value $formatDiskOut -Path $LogPath -Force
		$ddOut = RunLinuxCmd -username $testVMUsername -password $testVMPassword -ip $testVMVIP -port $testVMSSHport -command "dd if=/dev/zero bs=1024 count=1000000 of=$mountPoint/file_1GB" -runAsSudo -runMaxAllowedTime 1200
		WaitFor -seconds 10
		Add-Content -Value $ddOut -Path $LogPath
		try
		{
			$Null = RunLinuxCmd -username $testVMUsername -password $testVMPassword -ip $testVMVIP -port $testVMSSHport -command "umount $mountPoint" -runAsSudo
		}
		catch
		{
			LogMsg "umount failed. Trying umount -l"
			$Null = RunLinuxCmd -username $testVMUsername -password $testVMPassword -ip $testVMVIP -port $testVMSSHport -command "umount -l $mountPoint" -runAsSudo
		}
		$dmesgAfter = RunLinuxCmd -username $testVMUsername -password $testVMPassword -ip $testVMVIP -port $testVMSSHport -command "dmesg" -runMaxAllowedTime 30 -runAsSudo
		$addedLines = $dmesgAfter.Replace($dmesgBefore,$null)
		LogMsg "Kernel Logs : $($addedLines.Replace('[32m','').Replace('[0m[33m','').Replace('[0m',''))" -LinuxConsoleOuput
		$retValue = "PASS"
	}
	else
	{
		LogError "VM is not Alive."
		LogError "Aborting Test."
		$retValue = "Aborted"
	}
	return $retValue
}

Function RetryOperation($operation, $description, $expectResult=$null, $maxRetryCount=10, $retryInterval=10, [switch]$NoLogsPlease, [switch]$ThrowExceptionOnFailure)
{
	$retryCount = 1

	do
	{
		LogMsg "Attempt : $retryCount/$maxRetryCount : $description" -NoLogsPlease $NoLogsPlease
		$ret = $null
		$oldErrorActionValue = $ErrorActionPreference
		$ErrorActionPreference = "Stop"

		try
		{
			$ret = Invoke-Command -ScriptBlock $operation
			if ($null -ne $expectResult)
			{
				if ($ret -match $expectResult)
				{
					return $ret
				}
				else
				{
					$ErrorActionPreference = $oldErrorActionValue
					$retryCount ++
					WaitFor -seconds $retryInterval
				}
			}
			else
			{
				return $ret
			}
		}
		catch
		{
			$retryCount ++
			WaitFor -seconds $retryInterval
			if ( $retryCount -le $maxRetryCount )
			{
				continue
			}
		}
		finally
		{
			$ErrorActionPreference = $oldErrorActionValue
		}
		if ($retryCount -ge $maxRetryCount)
		{
			LogError "Command '$operation' Failed."
			break;
		}
	} while ($True)

	if ($ThrowExceptionOnFailure)
	{
		ThrowException -Exception "Command '$operation' Failed."
	}
	else
	{
		return $null
	}
}

Function GetFilePathsFromLinuxFolder ([string]$folderToSearch, $IpAddress, $SSHPort, $username, $password, $maxRetryCount=20, [string]$expectedFiles)
{
	$parentFolder = $folderToSearch.Replace("/" + $folderToSearch.Split("/")[($folderToSearch.Trim().Split("/").Count)-1],"")
	$LogFilesPaths = ""
	$LogFiles = ""
	$retryCount = 1
	while (($LogFilesPaths -eq "") -and ($retryCount -le $maxRetryCount ))
	{
		LogMsg "Attempt $retryCount/$maxRetryCount : Getting all file paths inside $folderToSearch"
		$lsOut = RunLinuxCmd -username $username -password $password -ip $IpAddress -port $SSHPort -command "ls -lR $parentFolder > /home/$user/listDir.txt" -runAsSudo -ignoreLinuxExitCode
		RemoteCopy -downloadFrom $IpAddress -port $SSHPort -files "/home/$user/listDir.txt" -username $username -password $password -downloadTo $LogDir -download
		$lsOut = Get-Content -Path "$LogDir\listDir.txt" -Force
		Remove-Item "$LogDir\listDir.txt"  -Force | Out-Null
		foreach ($line in $lsOut.Split("`n") )
		{
			$line = $line.Trim()
			if ($line -imatch $parentFolder)
			{
				$currentFolder = $line.Replace(":","")
			}
			if ( ( ($line.Split(" ")[0][0])  -eq "-" ) -and ($currentFolder -imatch $folderToSearch) )
			{
				while ($line -imatch "  ")
				{
					$line = $line.Replace("  "," ")
				}
				$currentLogFile = $line.Split(" ")[8]
				if ( $expectedFiles )
				{
					if ( $expectedFiles.Split(",") -contains $currentLogFile )
					{
						if ($LogFilesPaths)
						{
							$LogFilesPaths += "," + $currentFolder + "/" + $currentLogFile
							$LogFiles += "," + $currentLogFile
						}
						else
						{
							$LogFilesPaths = $currentFolder + "/" + $currentLogFile
							$LogFiles += $currentLogFile
						}
						LogMsg "Found Expected File $currentFolder/$currentLogFile"
					}
					else
					{
						LogMsg "Ignoring File $currentFolder/$currentLogFile"
					}
				}
				else
				{
					if ($LogFilesPaths)
					{
						$LogFilesPaths += "," + $currentFolder + "/" + $currentLogFile
						$LogFiles += "," + $currentLogFile
					}
					else
					{
						$LogFilesPaths = $currentFolder + "/" + $currentLogFile
						$LogFiles += $currentLogFile
					}
				}
			}
		}
		if ($LogFilesPaths -eq "")
		{
			WaitFor -seconds 10
		}
		$retryCount += 1
	}
	if ( !$LogFilesPaths )
	{
		LogMsg "No files found in $folderToSearch"
	}
	return $LogFilesPaths, $LogFiles
}

function ZipFiles( $zipfilename, $sourcedir )
{
	LogMsg "Creating '$zipfilename' from '$sourcedir'"
	$currentDir = (Get-Location).Path
	$7z = (Get-ChildItem .\Tools\7za.exe).FullName
	$sourcedir = $sourcedir.Trim('\')
	Set-Location $sourcedir
	$out = Invoke-Expression "$7z a -mx5 $currentDir\$zipfilename * -r"
	Set-Location $currentDir
	if ($out -match "Everything is Ok")
	{
		LogMsg "$currentDir\$zipfilename created successfully."
	}
}

Function GetStorageAccountFromRegion($Region,$StorageAccount)
{
#region Select Storage Account Type
	$RegionName = $Region.Replace(" ","").Replace('"',"").ToLower()
	$regionStorageMapping = [xml](Get-Content .\XML\RegionAndStorageAccounts.xml)
	if ($StorageAccount)
	{
		if ( $StorageAccount -imatch "ExistingStorage_Standard" )
		{
			$StorageAccountName = $regionStorageMapping.AllRegions.$RegionName.StandardStorage
		}
		elseif ( $StorageAccount -imatch "ExistingStorage_Premium" )
		{
			$StorageAccountName = $regionStorageMapping.AllRegions.$RegionName.PremiumStorage
		}
		elseif ( $StorageAccount -imatch "NewStorage_Standard" )
		{
			$StorageAccountName = "NewStorage_Standard_LRS"
		}
		elseif ( $StorageAccount -imatch "NewStorage_Premium" )
		{
			$StorageAccountName = "NewStorage_Premium_LRS"
		}
		elseif ($StorageAccount -eq "")
		{
			$StorageAccountName = $regionStorageMapping.AllRegions.$RegionName.StandardStorage
		}
	}
	else
	{
		$StorageAccountName = $regionStorageMapping.AllRegions.$RegionName.StandardStorage
	}
	LogMsg "Selected : $StorageAccountName"
	return $StorageAccountName
}

function CreateTestResultObject()
{
	$objNode = New-Object -TypeName PSObject
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name TestResult -Value $null -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name TestSummary -Value $null -Force
	return $objNode
}

function Get-HostBuildNumber {
	<#
	.Synopsis
		Get host BuildNumber.

	.Description
		Get host BuildNumber.
		14393: 2016 host
		9600: 2012R2 host
		9200: 2012 host
		0: error

	.Parameter hvServer
		Name of the server hosting the VM

	.ReturnValue
		Host BuildNumber.

	.Example
		Get-HostBuildNumber
	#>
	param (
		[String] $HvServer
	)

	[System.Int32]$buildNR = (Get-WmiObject -class Win32_OperatingSystem -ComputerName $HvServer).BuildNumber

	if ( $buildNR -gt 0 ) {
		return $buildNR
	} else {
		LogMsg "Get host build number failed"
		return 0
	}
}

function Convert-KvpToDict($RawData) {
	<#
	.Synopsis
		Convert the KVP data to a PowerShell dictionary.

	.Description
		Convert the KVP xml data into a PowerShell dictionary.
		All keys are added to the dictionary, even if their
		values are null.

	.Parameter RawData
		The raw xml KVP data.

	.Example
		Convert-KvpToDict $myKvpData
	#>

	$dict = @{}

	foreach ($dataItem in $RawData) {
		$key = ""
		$value = ""
		$xmlData = [Xml] $dataItem

		foreach ($p in $xmlData.INSTANCE.PROPERTY) {
			if ($p.Name -eq "Name") {
				$key = $p.Value
			}
			if ($p.Name -eq "Data") {
				$value = $p.Value
			}
		}
		$dict[$key] = $value
	}
	return $dict
}

function Check-Systemd {
	param (
		[String] $Ipv4,
		[String] $SSHPort,
		[String] $Username,
		[String] $Password
	)

	$check1 = $true
	$check2 = $true

	Write-Output "yes" | .\Tools\plink.exe -C -pw $Password -P $SSHPort $Username@$Ipv4 "ls -l /sbin/init | grep systemd"
	if ($LASTEXITCODE -ne "True") {
	LogMsg "Systemd not found on VM"
	$check1 = $false
	}
	Write-Output "yes" | .\Tools\plink.exe -C -pw $Password -P $SSHPort $Username@$Ipv4 "systemd-analyze --help"
	if ($LASTEXITCODE -ne "True") {
		LogMsg "Systemd-analyze not present on VM."
		$check2 = $false
	}

	return ($check1 -and $check2)
}

function Get-VMFeatureSupportStatus {
	<#
	.Synopsis
		Check if VM supports a feature or not.
	.Description
		Check if VM supports one feature or not based on comparison
			of curent kernel version with feature supported kernel version.
		If the current version is lower than feature supported version,
			return false, otherwise return true.
	.Parameter Ipv4
		IPv4 address of the Linux VM.
	.Parameter SSHPort
		SSH port used to connect to VM.
	.Parameter Username
		Username used to connect to the Linux VM.
	.Parameter Password
		Password used to connect to the Linux VM.
	.Parameter Supportkernel
		The kernel version number starts to support this feature, e.g. supportkernel = "3.10.0.383"
	.Example
		Get-VMFeatureSupportStatus $ipv4 $SSHPort $Username $Password $Supportkernel
	#>

	param (
		[String] $Ipv4,
		[String] $SSHPort,
		[String] $Username,
		[String] $Password,
		[String] $SupportKernel
	)

	Write-Output "yes" | .\Tools\plink.exe -C -pw $Password -P $SSHPort $Username@$Ipv4 'exit 0'
	$currentKernel = Write-Output "yes" | .\Tools\plink.exe -C -pw $Password -P $SSHPort $Username@$Ipv4  "uname -r"
	if( $LASTEXITCODE -eq $false){
		LogMsg "Warning: Could not get kernel version".
	}
	$sKernel = $SupportKernel.split(".-")
	$cKernel = $currentKernel.split(".-")

	for ($i=0; $i -le 3; $i++) {
		if ($cKernel[$i] -lt $sKernel[$i] ) {
			$cmpResult = $false
			break;
		}
		if ($cKernel[$i] -gt $sKernel[$i] ) {
			$cmpResult = $true
			break
		}
		if ($i -eq 3) { $cmpResult = $True }
	}
	return $cmpResult
}

function Get-SelinuxAVCLog() {
	<#
	.Synopsis
		Check selinux audit.log in Linux VM for avc denied log.
	.Description
		Check audit.log in Linux VM for avc denied log.
		If get avc denied log for hyperv daemons, return $true, else return $false.
	#>

	param (
		[String] $Ipv4,
		[String] $SSHPort,
		[String] $Username,
		[String] $Password
	)

	$FILE_NAME = ".\audit.log"
	$TEXT_HV = "hyperv"
	$TEXT_AVC = "type=avc"

	Write-Output "yes" | .\Tools\plink.exe -C -pw $Password -P $SSHPort $Username@$Ipv4 "ls /var/log/audit/audit.log > /dev/null 2>&1"
	if (-not $LASTEXITCODE) {
		LogErr "Warning: Unable to find audit.log from the VM, ignore audit log check"
		return $True
	}
	Write-Output "yes" | .\Tools\pscp -C -pw $Password -P $SSHPort $Username@${Ipv4}:/var/log/audit/audit.log $filename
	if (-not $LASTEXITCODE) {
		LogErr "ERROR: Unable to copy audit.log from the VM"
		return $False
	}

	$file = Get-Content $FILE_NAME
	Remove-Item $FILE_NAME
	foreach ($line in $file) {
		if ($line -match $TEXT_HV -and $line -match $TEXT_AVC){
			LogErr "ERROR: get the avc denied log: $line"
			return $True
		}
	}
	LogErr "Info: no avc denied log in audit log as expected"
	return $False
}

function Get-VMFeatureSupportStatus {
	param (
		[String] $VmIp,
		[String] $VmPort,
		[String] $UserName,
		[String] $Password,
		[String] $SupportKernel
	)

	$currentKernel = Write-Output "yes" | .\Tools\plink.exe -C -pw $Password -P $VmPort $UserName@$VmIp "uname -r"
	if ($LASTEXITCODE -eq $False) {
		Write-Output "Warning: Could not get kernel version".
	}
	$sKernel = $supportKernel.split(".-")
	$cKernel = $currentKernel.split(".-")

	for ($i=0; $i -le 3; $i++) {
		if ($cKernel[$i] -lt $sKernel[$i] ) {
			$cmpResult = $false
			break;
		}
		if ($cKernel[$i] -gt $sKernel[$i] ) {
			$cmpResult = $true
			break
		}
		if ($i -eq 3) {
			$cmpResult = $True
		}
	}
	return $cmpResult
}

function Get-UnixVMTime {
	param (
		[String] $Ipv4,
		[String] $Port,
		[String] $Username,
		[String] $Password
	)

	$unixTimeStr = $null

	$unixTimeStr = Get-TimeFromVM -Ipv4 $Ipv4 -Port $Port `
		-Username $Username -Password $Password
	if (-not $unixTimeStr -and $unixTimeStr.Length -lt 10) {
		return $null
	}

	return $unixTimeStr
}

function Get-TimeSync {
	param (
		[String] $Ipv4,
		[String] $Port,
		[String] $Username,
		[String] $Password
	)

	# Get a time string from the VM, then convert the Unix time string into a .NET DateTime object
	$unixTimeStr = RunLinuxCmd -ip $Ipv4 -port $Port -username $Username -password $Password `
		-command 'date "+%m/%d/%Y/%T" -u'
	if (-not $unixTimeStr) {
		LogErr "Error: Unable to get date/time string from VM"
		return $False
	}

	$pattern = 'MM/dd/yyyy/HH:mm:ss'
	$unixTime = [DateTime]::ParseExact($unixTimeStr, $pattern, $null)

	# Get our time
	$windowsTime = [DateTime]::Now.ToUniversalTime()

	# Compute the timespan, then convert it to the absolute value of the total difference in seconds
	$diffInSeconds = $null
	$timeSpan = $windowsTime - $unixTime
	if (-not $timeSpan) {
		LogErr "Error: Unable to compute timespan"
		return $False
	} else {
		$diffInSeconds = [Math]::Abs($timeSpan.TotalSeconds)
	}

	# Display the data
	LogMsg "Windows time: $($windowsTime.ToString())"
	LogMsg "Unix time: $($unixTime.ToString())"
	LogMsg "Difference: $diffInSeconds"
	LogMsg "Time difference = ${diffInSeconds}"
	return $diffInSeconds
}

function Optimize-TimeSync {
    param (
        [String] $Ipv4,
        [String] $Port,
        [String] $Username,
        [String] $Password
    )
    $testScript = "timesync_config.sh"
    $null = RunLinuxCmd -ip $Ipv4 -port $Port -username $Username `
        -password $Password -command `
        "echo '${Password}' | sudo -S -s eval `"export HOME=``pwd``;bash ${testScript} > ${testScript}.log`""
    if (-not $?) {
        LogMsg "Error: Failed to configure time sync. Check logs for details."
        return $False
    }
    return $True
}

function CheckVMState {
	param (
		[String] $VMName,
		[String] $HvServer
	)
	$vm = Get-Vm -VMName $VMName -ComputerName $HvServer
	$vmStatus = $vm.state

	return $vmStatus
}
function Check-FileInLinuxGuest{
	param (
		[String] $vmPassword,
		[String] $vmPort,
		[string] $vmUserName,
		[string] $ipv4,
		[string] $fileName,
		[boolean] $checkSize = $False ,
		[boolean] $checkContent = $False
	)
<#
	.Synopsis
		Checks if test file is present or not
	.Description
		Checks if test file is present or not, if set $checkSize as $True, return file size,
		if set checkContent as $True, will return file content.
#>
	if ($checkSize) {

		Write-Output "yes" | .\Tools\plink.exe -C -pw $vmPassword -P $vmPort $vmUserName@$ipv4 "wc -c < $fileName"
	}
	else {
		Write-Output "yes" | .\Tools\plink.exe -C -pw $vmPassword -P $vmPort $vmUserName@$ipv4 "stat ${fileName} >/dev/null"
	}

	if (-not $?) {
		return $False
	}
	if ($checkContent) {

		Write-Output "yes" | .\Tools\plink.exe -C -pw $vmPassword -P $vmPort $vmUserName@$ipv4 "cat ${fileName}"
		if (-not $?) {
			return $False
		}
	}
	return  $True
}

function Send-CommandToVM {
	param  (
		[string] $vmPassword,
		[string] $vmPort,
		[string] $ipv4,
		[string] $command
	)

	<#
	.Synopsis
		Send a command to a Linux VM using SSH.
	.Description
		Send a command to a Linux VM using SSH.

	#>

	$retVal = $False

	if (-not $ipv4)
	{
		LogErr "ipv4 is null"
		return $False
	}

	if (-not $vmPassword)
	{
		LogErr "vmPassword is null"
		return $False
	}

	if (-not $command)
	{
		LogErr "command is null"
		return $False
	}

	# get around plink questions
	Write-Output "yes" | .\Tools\plink.exe -C -pw ${vmPassword} -P ${vmPort} root@$ipv4 'exit 0'
	$process = Start-Process .\Tools\plink.exe -ArgumentList "-C -pw ${vmPassword} -P ${vmPort} root@$ipv4 ${command}" -PassThru -NoNewWindow -Wait
	if ($process.ExitCode -eq 0)
	{
		$retVal = $True
	}
	else
	{
		LogErr "Unable to send command to ${ipv4}. Command = '${command}'"
	}
	return $retVal
}

function Check-FcopyDaemon{
	param (
		[string] $vmPassword,
		[string] $vmPort,
		[string] $vmUserName,
		[string] $ipv4
	)
<#
	.Synopsis
	Verifies that the fcopy_daemon
	.Description
	Verifies that the fcopy_daemon on VM and attempts to copy a file

	#>

	$filename = ".\fcopy_present"

	Write-Output "yes" | .\Tools\plink.exe -C -pw $vmPassword -P $vmPort $vmUserName@$ipv4 "ps -ef | grep '[h]v_fcopy_daemon\|[h]ypervfcopyd' > /tmp/fcopy_present"
	if (-not $?) {
		LogErr  "Unable to verify if the fcopy daemon is running"
		return $False
	}

	Write-Output "yes" | .\tools\pscp.exe  -v -2 -unsafe -pw $vmPassword -q -P ${vmPort} $vmUserName@${ipv4}:/tmp/fcopy_present .
	if (-not $?) {
		LogErr "Unable to copy the confirmation file from the VM"
		return $False
	}

	# When using grep on the process in file, it will return 1 line if the daemon is running
	if ((Get-Content $filename  | Measure-Object -Line).Lines -eq  "1" ) {
		LogMsg "hv_fcopy_daemon process is running."
		$retValue = $True
	}

	Remove-Item $filename
	return $retValue
}

function Mount-Disk{
	param(
		[string] $vmPassword,
		[string] $vmPort,
		[string] $ipv4
	)
<#
	.Synopsis
	Mounts  and formates to ext4 a disk on vm
	.Description
	Mounts  and formates to ext4 a disk on vm

	#>

	$driveName = "/dev/sdc"

	$sts = Send-CommandToVM -vmPassword $vmPassword -vmPort $vmPort -ipv4 $ipv4 "(echo d;echo;echo w)|fdisk ${driveName}"
	if (-not $sts) {
		LogErr "Failed to format the disk in the VM $vmName."
		return $False
	}

	$sts = Send-CommandToVM -vmPassword $vmPassword -vmPort $vmPort -ipv4 $ipv4  "(echo n;echo p;echo 1;echo;echo;echo w)|fdisk ${driveName}"
	if (-not $sts) {
		LogErr "Failed to format the disk in the VM $vmName."
		return $False
	}

	$sts = Send-CommandToVM -vmPassword $vmPassword -vmPort $vmPort -ipv4 $ipv4  "mkfs.ext4 ${driveName}1"
	if (-not $sts) {
		LogErr "Failed to make file system in the VM $vmName."
		return $False
	}

	$sts = Send-CommandToVM -vmPassword $vmPassword -vmPort $vmPort -ipv4 $ipv4  "mount ${driveName}1 /mnt"
	if (-not $sts) {
		LogErr "Failed to mount the disk in the VM $vmName."
		return $False
	}

	LogMsg "$driveName has been mounted to /mnt in the VM $vmName."
	return $True
}

function Copy-FileVM{
	param(
		[string] $vmName,
		[string] $hvServer,
		[String] $filePath
	)
<#
	.Synopsis
	Copy the file to the Linux guest VM
	.Description
	Copy the file to the Linux guest VM

	#>

	$Error.Clear()
	Copy-VMFile -vmName $vmName -ComputerName $hvServer -SourcePath $filePath -DestinationPath "/mnt/" -FileSource host -ErrorAction SilentlyContinue
	if ($Error.Count -ne 0) {
		return $false
	}
	return $true
}

function Remove-TestFile{
	param(
		[String] $pathToFile,
		[String] $testfile
	)
<#
	.Synopsis
	Delete temporary test file
	.Description
	Delete temporary test file

	#>

	Remove-Item -Path $pathToFile -Force
	if ($? -ne "True") {
		LogErr "cannot remove the test file '${testfile}'!"
		return $False
	}
}

function Copy-CheckFileInLinuxGuest{
	param(
		[String] $vmName,
		[String] $hvServer,
		[String] $vmUserName,
		[String] $vmPassword,
		[String] $vmPort,
		[String] $ipv4,
		[String] $testfile,
		[Boolean] $overwrite,
		[Int] $contentlength,
		[String]$filePath,
		[String]$vhd_path_formatted
	)

	# Write the file
	$filecontent = Generate-RandomString -length $contentlength

	$filecontent | Out-File $testfile
	if (-not $?) {
		LogErr "Cannot create file $testfile'."
		return $False
	}

	$filesize = (Get-Item $testfile).Length
	if (-not $filesize){
		LogErr "Cannot get the size of file $testfile'."
		return $False
	}

	# Copy file to vhd folder
	Copy-Item -Path .\$testfile -Destination \\$hvServer\$vhd_path_formatted

	# Copy the file and check copied file
	$Error.Clear()
	if ($overwrite) {
		Copy-VMFile -vmName $vmName -ComputerName $hvServer -SourcePath $filePath -DestinationPath "/tmp/" -FileSource host -ErrorAction SilentlyContinue -Force
	}
	else {
		Copy-VMFile -vmName $vmName -ComputerName $hvServer -SourcePath $filePath -DestinationPath "/tmp/" -FileSource host -ErrorAction SilentlyContinue
	}
	if ($Error.Count -eq 0) {
		$sts = Check-FileInLinuxGuest -vmUserName $vmUserName -vmPassword $vmPassword -vmPort $vmPort -ipv4 $ipv4 -fileName "/tmp/$testfile" -checkSize $True -checkContent  $True
		if (-not $sts[-1]) {
			LogErr "File is not present on the guest VM '${vmName}'!"
			return $False
		}
		elseif ($sts[0] -ne $filesize) {
			LogErr "The copied file doesn't match the $filesize size."
			return $False
		}
		elseif ($sts[1] -ne $filecontent) {
			LogErr "The copied file doesn't match the content '$filecontent'."
			return $False
		}
		else {
			LogMsg "The copied file matches the $filesize size and content '$filecontent'."
		}
	}
	else {
		LogErr "An error has occurred while copying the file to guest VM '${vmName}'."
		$error[0]
		return $False
	}
	return $True
}

function Generate-RandomString{
	param(
		[Int] $length
	)

	$set = "abcdefghijklmnopqrstuvwxyz0123456789".ToCharArray()
	$result = ""
	for ($x = 0; $x -lt $length; $x++)
	{
		$result += $set | Get-Random
	}
	return $result
}

function Get-RemoteFileInfo{
	param (
		[String] $filename,
		[String] $server
	)

	$fileInfo = $null

	if (-not $filename)
	{
		return $null
	}

	if (-not $server)
	{
		return $null
	}

	$remoteFilename = $filename.Replace("\", "\\")
	$fileInfo = Get-WmiObject -query "SELECT * FROM CIM_DataFile WHERE Name='${remoteFilename}'" -computer $server

	return $fileInfo
}

function Convert-StringToUInt64{
	param (
		[string] $str
	)

	$uint64Size = $null
	#
	# Make sure we received a string to convert
	#
	if (-not $str)
	{
		LogErr "ConvertStringToUInt64() - input string is null"
		return $null
	}

	if ($str.EndsWith("MB"))
	{
		$num = $str.Replace("MB","")
		$uint64Size = ([Convert]::ToUInt64($num)) * 1MB
	}
	elseif ($str.EndsWith("GB"))
	{
		$num = $str.Replace("GB","")
		$uint64Size = ([Convert]::ToUInt64($num)) * 1GB
	}
	elseif ($str.EndsWith("TB"))
	{
		$num = $str.Replace("TB","")
		$uint64Size = ([Convert]::ToUInt64($num)) * 1TB
	}
	else
	{
		LogErr "Invalid newSize parameter: ${str}"
		return $null
	}

	return $uint64Size
}

function Check-Result{
	param(
		[String] $vmPassword,
		[String] $vmPort,
		[String] $ipv4
	)

	$retVal = $False
	$stateFile     = "state.txt"
	$localStateFile= "${vmName}_state.txt"
	$TestCompleted = "TestCompleted"
	$TestAborted   = "TestAborted"
	$timeout       = 6000

	while ($timeout -ne 0 )
	{
		Write-Output "yes" | .\tools\pscp.exe  -v -2 -unsafe -pw $vmPassword -q -P ${vmPort} root@${ipv4}:${stateFile} ${localStateFile} #| out-null
		$sts = $?
		if ($sts)
		{
			if (test-path $localStateFile)
			{
				$contents = Get-Content -Path $localStateFile
				if ($null -ne $contents)
				{
						if ($contents -eq $TestCompleted)
						{
							$retVal = $True
							break

						}

						if ($contents -eq $TestAborted)
						{
							LogMsg  "State file contains TestAborted failed. "
							break
						}

						$timeout--

						if ($timeout -eq 0)
						{
							LogErr "Timed out on Test Running , Exiting test execution."
							break
						}

				}
				else
				{
					LogMsg "state file is empty"
					break
				}

			}
			else
			{
				LogMsg "ssh reported success, but state file was not copied"
				break
			}
		}
		else
		{
			LogErr "pscp exit status = $sts"
			LogErr "unable to pull state.txt from VM."
			break
		}
	}
	Remove-Item $localStateFile
	return $retVal
}

function Get-VMGeneration {
	# Get VM generation type from host, generation 1 or generation 2
	param (
		[String] $vmName,
		[String] $hvServer
	)

	# Hyper-V Server 2012 (no R2) only supports generation 1 VM
	$vmInfo = Get-VM -Name $vmName -ComputerName $hvServer
	if (!$vmInfo.Generation) {
		$vmGeneration = 1
	} else {
		$vmGeneration = $vmInfo.Generation
	}

	return $vmGeneration
}

function Convert-StringToDecimal {
	Param (
		[string] $Str
	)
	$uint64Size = $null

	# Make sure we received a string to convert
	if (-not $Str) {
		LogErr "ConvertStringToDecimal() - input string is null"
		return $null
	}

	if ($Str.EndsWith("MB")) {
		$num = $Str.Replace("MB","")
		$uint64Size = ([Convert]::ToDecimal($num)) * 1MB
	} elseif ($Str.EndsWith("GB")) {
		$num = $Str.Replace("GB","")
		$uint64Size = ([Convert]::ToDecimal($num)) * 1GB
	} elseif ($Str.EndsWith("TB")) {
		$num = $Str.Replace("TB","")
		$uint64Size = ([Convert]::ToDecimal($num)) * 1TB
	} else {
		LogErr "Invalid newSize parameter: ${Str}"
		return $null
	}

	return $uint64Size
}

function Create-Controller{
	param (
		[string] $vmName,
		[string] $server,
		[string] $controllerID
	)

	#
	# Initially, we will limit this to 4 SCSI controllers...
	#
	if ($ControllerID -lt 0 -or $controllerID -gt 3)
	{
		LogErr "Bad SCSI controller ID: $controllerID"
		return $False
	}

	#
	# Check if the controller already exists.
	#
	$scsiCtrl = Get-VMScsiController -VMName $vmName -ComputerName $server
	if ($scsiCtrl.Length -1 -ge $controllerID)
	{
	LogMsg "SCSI controller already exists"
	}
	else
	{
		$error.Clear()
		Add-VMScsiController -VMName $vmName -ComputerName $server
		if ($error.Count -gt 0)
		{
		LogErr "Add-VMScsiController failed to add 'SCSI Controller $ControllerID'"
			$error[0].Exception
			return $False
		}
		LogMsg "Controller successfully added"
	}
	return $True
}

function Stop-FcopyDaemon{
	param(
		[String] $vmPassword,
		[String] $vmPort,
		[String] $vmUserName,
		[String] $ipv4
	)
	$sts = check_fcopy_daemon  -vmPassword $vmPassword -vmPort $vmPort -vmUserName $vmUserName -ipv4 $ipv4
	if ($sts[-1] -eq $True ){
		Write-Output "yes" | .\Tools\plink.exe -C -pw ${vmPassword} -P ${vmPort} ${vmUserName}@${ipv4} "pkill -f 'fcopy'"
		if (-not $?) {
			LogErr "Unable to kill hypervfcopy daemon"
			return $False
		}
	}
	return $true
}

function Check-VMState{
	param(
		[String] $vmName,
		[String] $hvServer
	)

	$vm = Get-Vm -VMName $vmName -ComputerName $hvServer
	$vmStatus = $vm.state

	return $vmStatus
}

function Get-HostBuildNumber {
	# Get host BuildNumber.
	# 14393: 2016 host --- 9600: 2012R2 host --- 9200: 2012 host -- 0: error
	param (
		[String] $hvServer
	)

	[System.Int32]$buildNR = (Get-WmiObject -class Win32_OperatingSystem -ComputerName $hvServer).BuildNumber

	if ( $buildNR -gt 0 ) {
		return $buildNR
	} else {
		LogErr "Get host build number failed"
		return 0
	}
}

function Convert-KvpToDict($RawData) {
	<#
	.Synopsis
		Convert the KVP data to a PowerShell dictionary.

	.Description
		Convert the KVP xml data into a PowerShell dictionary.
		All keys are added to the dictionary, even if their
		values are null.

	.Parameter RawData
		The raw xml KVP data.

	.Example
		Convert-KvpToDict $myKvpData
	#>

	$dict = @{}

	foreach ($dataItem in $RawData) {
		$key = ""
		$value = ""
		$xmlData = [Xml] $dataItem

		foreach ($p in $xmlData.INSTANCE.PROPERTY) {
			if ($p.Name -eq "Name") {
				$key = $p.Value
			}
			if ($p.Name -eq "Data") {
				$value = $p.Value
			}
		}
		$dict[$key] = $value
	}

	return $dict
}

function Check-Systemd {
	param (
		[String] $Ipv4,
		[String] $SSHPort,
		[String] $Username,
		[String] $Password
	)

	$check1 = $true
	$check2 = $true

	Write-Output "yes" | .\Tools\plink.exe -C -pw $Password -P $SSHPort $Username@$Ipv4 "ls -l /sbin/init | grep systemd"
	if ($LASTEXITCODE -gt "0") {
	LogMsg "Systemd not found on VM"
	$check1 = $false
	}
	Write-Output "yes" | .\Tools\plink.exe -C -pw $Password -P $SSHPort $Username@$Ipv4 "systemd-analyze --help"
	if ($LASTEXITCODE -gt "0") {
		LogMsg "Systemd-analyze not present on VM."
		$check2 = $false
	}

	return ($check1 -and $check2)
}

function Get-IPv4ViaKVP {
	# Try to determine a VMs IPv4 address with KVP Intrinsic data.
	param (
		[String] $VmName,
		[String] $HvServer
	)

	$vmObj = Get-WmiObject -Namespace root\virtualization\v2 -Query "Select * From Msvm_ComputerSystem Where ElementName=`'$VmName`'" -ComputerName $HvServer
	if (-not $vmObj) {
		LogWarn "Get-IPv4ViaKVP: Unable to create Msvm_ComputerSystem object"
		return $null
	}

	$kvp = Get-WmiObject -Namespace root\virtualization\v2 -Query "Associators of {$vmObj} Where AssocClass=Msvm_SystemDevice ResultClass=Msvm_KvpExchangeComponent" -ComputerName $HvServer
	if (-not $kvp) {
		LogWarn "Get-IPv4ViaKVP: Unable to create KVP exchange component"
		return $null
	}

	$rawData = $Kvp.GuestIntrinsicExchangeItems
	if (-not $rawData) {
		LogWarn "Get-IPv4ViaKVP: No KVP Intrinsic data returned"
		return $null
	}

	$addresses = $null

	foreach ($dataItem in $rawData) {
		$found = 0
		$xmlData = [Xml] $dataItem
		foreach ($p in $xmlData.INSTANCE.PROPERTY) {
			if ($p.Name -eq "Name" -and $p.Value -eq "NetworkAddressIPv4") {
				$found += 1
			}

			if ($p.Name -eq "Data") {
				$addresses = $p.Value
				$found += 1
			}

			if ($found -eq 2) {
				$addrs = $addresses.Split(";")
				foreach ($addr in $addrs) {
					if ($addr.StartsWith("127.")) {
						Continue
					}
					return $addr
				}
			}
		}
	}

	LogWarn "Get-IPv4ViaKVP: No IPv4 address found for VM ${VmName}"
	return $null
}

function Get-IPv4AndWaitForSSHStart {
	# Wait for KVP start and
	# Get ipv4 via kvp
	# Wait for ssh start, test ssh.
	# Returns [String]ipv4 address if succeeded or $False if failed
	param (
		[String] $VmName,
		[String] $HvServer,
		[String] $VmPort,
		[String] $User,
		[String] $Password,
		[int] $StepTimeout
	)

	# Wait for KVP to start and able to get ipv4 addr
	if (-not (Wait-ForVMToStartKVP $VmName $HvServer $StepTimeout)) {
		LogErr "GetIPv4AndWaitForSSHStart: Unable to get ipv4 from VM ${vmName} via KVP within timeout period ($StepTimeout)"
		return $False
	}

	# Get new ipv4 in case an new ip is allocated to vm after reboot
	$new_ip = Get-IPv4ViaKVP $vmName $hvServer
	if (-not ($new_ip)){
		LogErr "GetIPv4AndWaitForSSHStart: Unable to get ipv4 from VM ${vmName} via KVP"
		return $False
	}

	# Wait for port 22 open
	if (-not (Wait-ForVMToStartSSH $new_ip $stepTimeout)) {
		LogErr "GetIPv4AndWaitForSSHStart: Failed to connect $new_ip port 22 within timeout period ($StepTimeout)"
		return $False
	}

	# Cache fingerprint, Check ssh is functional after reboot
	Write-Output "yes" | .\Tools\plink.exe -C -pw $Password -P $VmPort $User@$new_ip 'exit 0'
	$TestConnection = .\Tools\plink.exe -C -pw $Password -P $VmPort $User@$new_ip "echo Connected"
	if ($TestConnection -ne "Connected") {
		LogErr "GetIPv4AndWaitForSSHStart: SSH is not working correctly after boot up"
		return $False
	}

	return $new_ip
}

function Wait-ForVMToStartSSH {
	#  Wait for a Linux VM to start SSH. This is done by testing
	# if the target machine is listening on port 22.
	param (
		[String] $Ipv4addr,
		[int] $StepTimeout
	)
	$retVal = $False

	$waitTimeOut = $StepTimeout
	while ($waitTimeOut -gt 0) {
		$sts = Test-Port -ipv4addr $Ipv4addr -timeout 5
		if ($sts) {
			return $True
		}

		$waitTimeOut -= 15  # Note - Test Port will sleep for 5 seconds
		Start-Sleep -s 10
	}

	if (-not $retVal) {
		LogErr "Wait-ForVMToStartSSH: VM did not start SSH within timeout period ($StepTimeout)"
	}

	return $retVal
}

function Wait-ForVMToStartKVP {
	# Wait for a Linux VM with the LIS installed to start the KVP daemon
	param (
		[String] $VmName,
		[String] $HvServer,
		[int] $StepTimeout
	)
	$ipv4 = $null
	$retVal = $False

	$waitTimeOut = $StepTimeout
	while ($waitTimeOut -gt 0) {
		$ipv4 = Get-IPv4ViaKVP $VmName $HvServer
		if ($ipv4) {
			return $True
		}

		$waitTimeOut -= 10
		Start-Sleep -s 10
	}

	LogErr "Wait-ForVMToStartKVP: VM ${VmName} did not start KVP within timeout period ($StepTimeout)"
	return $retVal
}

function Wait-ForVMToStop {
	# Wait for a VM to enter the Hyper-V Off state.
	param (
		[String] $VmName,
		[String] $HvServer,
		[int] $Timeout
	)

	[System.Reflection.Assembly]::LoadWithPartialName("Microsoft.HyperV.PowerShell")
	$tmo = $Timeout
	while ($tmo -gt 0) {
		Start-Sleep -s 1
		$tmo -= 5

		$vm = Get-VM -Name $VmName -ComputerName $HvServer
		if (-not $vm) {
			return $False
		}

		if ($vm.State -eq [Microsoft.HyperV.PowerShell.VMState]::off) {
			return $True
		}
	}

	LogErr "StopVM: VM did not stop within timeout period"
	return $False
}

function Test-Port {
	# Test if a remote host is listening on a spceific TCP port
	# Wait only timeout seconds.
	param (
		[String] $Ipv4addr,
		[String] $PortNumber=22,
		[int] $Timeout=5
	)

	$retVal = $False
	$to = $Timeout * 1000

	# Try an async connect to the specified machine/port
	$tcpClient = new-Object system.Net.Sockets.TcpClient
	$iar = $tcpclient.BeginConnect($Ipv4addr,$PortNumber,$null,$null)

	# Wait for the connect to complete. Also set a timeout
	# so we don't wait all day
	$connected = $iar.AsyncWaitHandle.WaitOne($to,$false)

	# Check to see if the connection is done
	if ($connected) {
		# Close our connection
		try {
			$Null = $tcpclient.EndConnect($iar)
			$retVal = $true
		} catch {
			LogMsg $_.Exception.Message
		}
	}
	$tcpclient.Close()

	return $retVal
}

function Get-ParentVHD {
	# To Get Parent VHD from VM
	param (
		[String] $vmName,
		[String] $hvServer
	)

	$ParentVHD = $null

	$VmInfo = Get-VM -Name $vmName -ComputerName $hvServer
	if (-not $VmInfo) {
	LogErr "Unable to collect VM settings for ${vmName}"
	return $False
	}

	$vmGen = Get-VMGeneration $vmName $hvServer
	if ($vmGen -eq 1 ) {
		$Disks = $VmInfo.HardDrives
		foreach ($VHD in $Disks) {
			if (($VHD.ControllerLocation -eq 0) -and ($VHD.ControllerType -eq "IDE")) {
				$Path = Get-VHD $VHD.Path -ComputerName $hvServer
				if ([string]::IsNullOrEmpty($Path.ParentPath)) {
					$ParentVHD = $VHD.Path
				} else {
					$ParentVHD =  $Path.ParentPath
				}

				LogMsg "Parent VHD Found: $ParentVHD "
			}
		}
	}
	if ( $vmGen -eq 2 ) {
		$Disks = $VmInfo.HardDrives
		foreach ($VHD in $Disks) {
			if (($VHD.ControllerLocation -eq 0 ) -and ($VHD.ControllerType -eq "SCSI")) {
				$Path = Get-VHD $VHD.Path -ComputerName $hvServer
				if ([string]::IsNullOrEmpty($Path.ParentPath)) {
					$ParentVHD = $VHD.Path
				} else {
					$ParentVHD =  $Path.ParentPath
				}
				LogMsg "Parent VHD Found: $ParentVHD "
			}
		}
	}

	if (-not ($ParentVHD.EndsWith(".vhd") -xor $ParentVHD.EndsWith(".vhdx"))) {
		LogErr "Parent VHD is Not correct please check VHD, Parent VHD is: $ParentVHD"
		return $False
	}

	return $ParentVHD
}

function Create-ChildVHD {
	param (
		[String] $ParentVHD,
		[String] $defaultpath,
		[String] $hvServer
	)

	$ChildVHD  = $null
	$hostInfo = Get-VMHost -ComputerName $hvServer
	if (-not $hostInfo) {
		LogErr "Unable to collect Hyper-V settings for $hvServer"
		return $False
	}

	# Create Child VHD
	if ($ParentVHD.EndsWith("x")) {
		$ChildVHD = $defaultpath + ".vhdx"
	} else {
		$ChildVHD = $defaultpath + ".vhd"
	}

	if (Test-Path $ChildVHD) {
		LogMsg "Remove-Itemeting existing VHD $ChildVHD"
		Remove-Item $ChildVHD
	}

	# Copy Child VHD
	Copy-Item "$ParentVHD" "$ChildVHD"
	if (-not $?) {
		LogErr  "Unable to create child VHD"
		return $False
	}

	return $ChildVHD
}

function Convert-ToMemSize {
	param (
		[String] $memString,
		[String] $hvServer
	)
	$memSize = [Int64] 0

	if ($memString.EndsWith("MB")) {
		$num = $memString.Replace("MB","")
		$memSize = ([Convert]::ToInt64($num)) * 1MB
	} elseif ($memString.EndsWith("GB")) {
		$num = $memString.Replace("GB","")
		$memSize = ([Convert]::ToInt64($num)) * 1GB
	} elseif ($memString.EndsWith("%")) {
		$osInfo = Get-WMIObject Win32_OperatingSystem -ComputerName $hvServer
		if (-not $osInfo) {
			LogErr "Unable to retrieve Win32_OperatingSystem object for server ${hvServer}"
			return $False
		}

		$hostMemCapacity = $osInfo.FreePhysicalMemory * 1KB
		$memPercent = [Convert]::ToDouble("0." + $memString.Replace("%",""))
		$num = [Int64] ($memPercent * $hostMemCapacity)

		# Align on a 4k boundry
		$memSize = [Int64](([Int64] ($num / 2MB)) * 2MB)
	} else {
		$memSize = ([Convert]::ToInt64($memString))
	}

	return $memSize
}

function Get-NumaSupportStatus {
	param (
		[string] $kernel
	)
	# Get whether NUMA is supported or not based on kernel verison.
	# Generally, from RHEL 6.6 with kernel version 2.6.32-504,
	# NUMA is supported well.

	if ( $kernel.Contains("i686") -or $kernel.Contains("i386")) {
		return $false
	}

	if ($kernel.StartsWith("2.6")) {
		$numaSupport = "2.6.32.504"
		$kernelSupport = $numaSupport.split(".")
		$kernelCurrent = $kernel.replace("-",".").split(".")

		for ($i=0; $i -le 3; $i++) {
			if ($kernelCurrent[$i] -lt $kernelSupport[$i]) {
				return $false
			}
		}
	}

	# We skip the check if kernel is not 2.6
	# Anything newer will have support for it
	return $true
}

Function Test-SRIOVInLinuxGuest {
	param (
		#Required
		[string]$username,
		[string]$password,
		[string]$IpAddress,
		[int]$SSHPort,

		#Optional
		[int]$ExpectedSriovNics
	)

	$MaximumAttempts = 10
	$Attempts = 1
	$VerificationCommand = "lspci | grep Mellanox | wc -l"
	$retValue = $false
	while ($retValue -eq $false -and $Attempts -le $MaximumAttempts) {
		LogMsg "[Attempt $Attempts/$MaximumAttempts] Detecting Mellanox NICs..."
		$DetectedSRIOVNics = RunLinuxCmd -username $username -password $password -ip $IpAddress -port $SSHPort -command $VerificationCommand
		$DetectedSRIOVNics = [int]$DetectedSRIOVNics
		if ($ExpectedSriovNics -ge 0) {
			if ($DetectedSRIOVNics -eq $ExpectedSriovNics) {
				$retValue = $true
				LogMsg "$DetectedSRIOVNics Mellanox NIC(s) deteted in VM. Expected: $ExpectedSriovNics."
			} else {
				$retValue = $false
				LogErr "$DetectedSRIOVNics Mellanox NIC(s) deteted in VM. Expected: $ExpectedSriovNics."
				Start-Sleep -Seconds 20
			}
		} else {
			if ($DetectedSRIOVNics -gt 0) {
				$retValue = $true
				LogMsg "$DetectedSRIOVNics Mellanox NIC(s) deteted in VM."
			} else {
				$retValue = $false
				LogErr "$DetectedSRIOVNics Mellanox NIC(s) deteted in VM."
				Start-Sleep -Seconds 20
			}
		}
		$Attempts += 1
	}
	return $retValue
}

Function Set-SRIOVInVMs {
    param (
        $VirtualMachinesGroupName,
        $VMNames,
        [switch]$Enable,
        [switch]$Disable
    )
	
    if ( $TestPlatform -eq "Azure") {
        LogMsg "Set-SRIOVInVMs running in 'Azure' mode."
        if ($Enable) {
            if ($VMNames) {
                $retValue = Set-SRIOVinAzureVMs -ResourceGroup $VirtualMachinesGroupName -VMNames $VMNames -Enable
            }
            else {
                $retValue = Set-SRIOVinAzureVMs -ResourceGroup $VirtualMachinesGroupName -Enable
            }
        }
        elseif ($Disable) {
            if ($VMNames) {
                $retValue = Set-SRIOVinAzureVMs -ResourceGroup $VirtualMachinesGroupName -VMNames $VMNames -Disable
            }
            else {
                $retValue = Set-SRIOVinAzureVMs -ResourceGroup $VirtualMachinesGroupName -Disable
            }
        }
    }
    elseif ($TestPlatform -eq "HyperV") {
        <#
        ####################################################################
        # Note: Function Set-SRIOVinHypervVMs needs to be implemented in HyperV.psm1.
        # It should allow the same parameters as implemented for Azure.
        #   -HyperVGroup [string]
        #   -VMNames [string] ... comma separated VM names. [Optional]
        #        If no VMNames is provided, it should pick all the VMs from HyperVGroup
        #   -Enable
        #   -Disable
        ####################################################################
        LogMsg "Set-SRIOVInVMs running in 'HyperV' mode."
        if ($Enable) {
            if ($VMNames) {
                $retValue = Set-SRIOVinHypervVMs -HyperVGroup $VirtualMachinesGroupName -VMNames $VMNames -Enable
            }
            else {
                $retValue = Set-SRIOVinHypervVMs -HyperVGroup $VirtualMachinesGroupName -Enable
            }
        }
        elseif ($Disable) {
            if ($VMNames) {
                $retValue = Set-SRIOVinHypervVMs -HyperVGroup $VirtualMachinesGroupName -VMNames $VMNames -Disable
            }
            else {
                $retValue = Set-SRIOVinHypervVMs -HyperVGroup $VirtualMachinesGroupName -Disable
            }
        }
        #>
        $retValue = $false
    }
    return $retValue
}

# Checks if MAC is valid. Delimiter can be : - or nothing
function Is-ValidMAC {
    param (
        [String]$macAddr
    )

    $retVal = $macAddr -match '^([0-9a-fA-F]{2}[:-]{0,1}){5}[0-9a-fA-F]{2}$'
    return $retVal
}

# Returns an unused random MAC capable
# The address will be outside of the dynamic MAC pool
# Note that the Manufacturer bytes (first 3 bytes) are also randomly generated 
function Get-RandUnusedMAC {
    param (
        [String] $HvServer,
        [Char] $Delim
    )
    # First get the dynamic pool range
    $dynMACStart = (Get-VMHost -ComputerName $HvServer).MacAddressMinimum
    $validMac = Is-ValidMAC $dynMACStart
    if (-not $validMac) {
        return $false
    }

    $dynMACEnd = (Get-VMHost -ComputerName $HvServer).MacAddressMaximum
    $validMac = Is-ValidMAC $dynMACEnd
    if (-not $validMac) {
        return $false
    }

    [uint64]$lowerDyn = "0x$dynMACStart"
    [uint64]$upperDyn = "0x$dynMACEnd"
    if ($lowerDyn -gt $upperDyn) {
        return $false
    }

    # leave out the broadcast address
    [uint64]$maxMac = 281474976710655 #FF:FF:FF:FF:FF:FE

    # now random from the address space that has more macs
    [uint64]$belowPool = $lowerDyn - [uint64]1
    [uint64]$abovePool = $maxMac - $upperDyn

    if ($belowPool -gt $abovePool) {
        [uint64]$randStart = [uint64]1
        [uint64]$randStop = [uint64]$lowerDyn - [uint64]1
    } else {
        [uint64]$randStart = $upperDyn + [uint64]1
        [uint64]$randStop = $maxMac
    }

    # before getting the random number, check all VMs for static MACs
    $staticMacs = (get-VM -computerName $hvServer | Get-VMNetworkAdapter | where { $_.DynamicMacAddressEnabled -like "False" }).MacAddress
    do {
        # now get random number
        [uint64]$randDecAddr = Get-Random -minimum $randStart -maximum $randStop
        [String]$randAddr = "{0:X12}" -f $randDecAddr

        # Now set the unicast/multicast flag bit.
        [Byte] $firstbyte = "0x" + $randAddr.substring(0,2)
        # Set low-order bit to 0: unicast
        $firstbyte = [Byte] $firstbyte -band [Byte] 254 #254 == 11111110

        $randAddr = ("{0:X}" -f $firstbyte).padleft(2,"0") + $randAddr.substring(2)

    } while ($staticMacs -contains $randAddr) # check that we didn't random an already assigned MAC Address

    # randAddr now contains the new random MAC Address
    # add delim if specified
    if ($Delim) {
        for ($i = 2 ; $i -le 14 ; $i += 3) {
            $randAddr = $randAddr.insert($i,$Delim)
        }
    }

    $validMac = Is-ValidMAC $randAddr
    if (-not $validMac) {
        return $false
    }

    return $randAddr
}

function Start-VMandGetIP {
    param (
        $VMName,
        $HvServer,
        $VMPort,
        $VMUserName,
        $VMPassword   
    )
    $newIpv4 = $null

    Start-VM -Name $VMName -ComputerName $HvServer
    if (-not $?) {
        LogErr "Error: Failed to start VM $VMName on $HvServer"
        return $False
    } else {
        LogMsg "$VMName started on $HvServe"
    }

    # Wait for VM to boot
    $newIpv4 = Get-Ipv4AndWaitForSSHStart $VMName $HvServer $VMPort $VMUserName `
                $VMPassword 300
    if ($null -ne $newIpv4) {
        LogMsg "$VMName IP address: $newIpv4"
        return $newIpv4
    } else {
        LogErr "Error: Failed to get IP of $VMName on $HvServer"
        return $False
    }
}

# Generates an unused IP address based on an old IP address.
function Generate-IPv4{
    param (
        $TempIpv4, 
        $OldIpv4
    )
    [int]$check = $null

    if ($OldIpv4 -eq $null){
        [int]$octet = 102
    } else {
        $oldIpPart = $OldIpv4.Split(".")
        [int]$octet  = $oldIpPart[3]
    }

    $ipPart = $TempIpv4.Split(".")
    $newAddress = ($ipPart[0]+"."+$ipPart[1]+"."+$ipPart[2])

    while ($check -ne 1 -and $octet -lt 255) {
        $octet = 1 + $octet
        if (!(Test-Connection "$newAddress.$octet" -Count 1 -Quiet)) {
            $splitIp = $newAddress + "." + $octet
            $check = 1
        }
    }

    return $splitIp.ToString()
}

# CIDR to netmask
function Convert-CIDRtoNetmask{
    param (
        [int]$CIDR
    )
    $mask = ""

    for ($i=0; $i -lt 32; $i+=1) {
        if($i -lt $CIDR){
            $ip+="1"
        }else{
            $ip+= "0"
        }
    }
    for ($byte=0; $byte -lt $ip.Length/8; $byte+=1) {
        $decimal = 0
        for ($bit=0;$bit -lt 8; $bit+=1) {
            $poz = $byte * 8 + $bit
            if ($ip[$poz] -eq "1") {
                $decimal += [math]::Pow(2, 8 - $bit -1)
            }
        }
        $mask +=[convert]::ToString($decimal)
        if ($byte -ne $ip.Length /8 -1) {
             $mask += "."
        }
    }
    return $mask
}

function Set-GuestInterface {
    param (
        $VMUser,
        $VMIpv4,
        $VMPort,
        $VMPassword,
        $InterfaceMAC,
        $VMStaticIP,
        $Bootproto,
        $Netmask,
        $VMName,
        $VlanID
    )

    RemoteCopy -upload -uploadTo $VMIpv4 -Port $VMPort `
        -files ".\Testscripts\Linux\utils.sh" -Username $VMUser -password $VMPassword
    if (-not $?) {
        LogErr "Failed to send utils.sh to VM!"
        return $False
    }

    # Configure NIC on the guest
    LogMsg "Configuring test interface ($InterfaceMAC) on $VMName ($VMIpv4)"
    # Get the interface name that coresponds to the MAC address
    $cmdToSend = "testInterface=`$(grep -il ${InterfaceMAC} /sys/class/net/*/address) ; basename `"`$(dirname `$testInterface)`""
    $testInterfaceName = RunLinuxCmd -username $VMUser -password $VMPassword -ip $VMIpv4 -port $VMPort `
        -command $cmdToSend 
    if (-not $testInterfaceName) {
        LogErr "Failed to get the interface name that has $InterfaceMAC MAC address"
        return $False
    } else {
        LogMsg "The interface that will be configured on $VMName is $testInterfaceName"
    }
    $configFunction = "CreateIfupConfigFile"
    if ($VlanID) {
        $configFunction = "CreateVlanConfig"  
    }
    
    # Configure the interface
    $cmdToSend = ". utils.sh; $configFunction $testInterfaceName $Bootproto $VMStaticIP $Netmask $VlanID"
    RunLinuxCmd -username $VMUser -password $VMPassword -ip $VMIpv4 -port $VMPort -command $cmdToSend
    if (-not $?) {
        LogErr "Failed to configure $testInterfaceName NIC on vm $VMName"
        return $False
    }
    LogMsg "Sucessfuly configured $testInterfaceName on $VMName"
    return $True
}

function Test-GuestInterface {
    param (
        $VMUser,
        $AddressToPing,
        $VMIpv4,
        $VMPort,
        $VMPassword,
        $InterfaceMAC,
        $PingVersion,
        $PacketNumber,
        $Vlan
    )

    $nicPath = "/sys/class/net/*/address"
    if ($Vlan -eq "yes") {
        $nicPath = "/sys/class/net/*.*/address"
    }
    $cmdToSend = "testInterface=`$(grep -il ${InterfaceMAC} ${nicPath}) ; basename `"`$(dirname `$testInterface)`""
    $testInterfaceName = RunLinuxCmd -username $VMUser -password $VMPassword -ip $VMIpv4 -port $VMPort `
        -command $cmdToSend

    $cmdToSend = "$PingVersion -I $testInterfaceName $AddressToPing -c $PacketNumber -p `"cafed00d00766c616e0074616700`""
    $pingResult = RunLinuxCmd -username $VMUser -password $VMPassword -ip $VMIpv4 -port $VMPort `
        -command $cmdToSend -ignoreLinuxExitCode:$true

    if ($pingResult -notMatch "$PacketNumber received") {
        return $False
    }
    return $True
}

# This function removes all the invalid characters from given filename.
# Do not pass file paths (relative or full) to this function.
# Only file name is supported.
Function Remove-InvalidCharactersFromFileName 
{
    param (
        [String]$FileName
	)
    $WindowsInvalidCharacters = [IO.Path]::GetInvalidFileNameChars() -join ''
    $Regex = "[{0}]" -f [RegEx]::Escape($WindowsInvalidCharacters)
    return ($FileName -replace $Regex)
}

Function Check-VSSDemon {
    param (
        [String] $VMName,
        [String] $HvServer,
        [String] $VMIpv4,
        [String] $VMPort
    )
    $remoteScript="STOR_VSS_Check_VSS_Daemon.sh"
    $retval = Invoke-RemoteScriptAndCheckStateFile $remoteScript $user $password $VMIpv4 $VMPort
    if ($retval -eq $False) {
        LogErr "Running $remoteScript script failed on VM!"
        return $False
    }
    LogMsg "VSS Daemon is running"
    return $True
}

Function New-BackupSetup {
    param (
        [String] $VMName,
        [String] $HvServer
    )
    LogMsg "Removing old backups"
    try {
        Remove-WBBackupSet -MachineName $HvServer -Force -WarningAction SilentlyContinue
        if (-not $?) {
            LogErr "Not able to remove existing BackupSet"
            return $False
        }
    }
    catch {
        LogMsg "No existing backup's to remove"
    }
    # Check if the VM VHD in not on the same drive as the backup destination
    $vm = Get-VM -Name $VMName -ComputerName $HvServer
    # Get drive letter
    $sts = Get-DriveLetter $VMName $HvServer
    $driveletter = $global:driveletter
    if (-not $sts[-1]) {
        LogErr "Cannot get the drive letter"
        return $False
    }
    foreach ($drive in $vm.HardDrives) {
        if ( $drive.Path.StartsWith("$driveletter")) {
            LogErr "Backup partition $driveletter is same as partition hosting the VMs disk $($drive.Path)"
            return $False
        }
    }
    return $True
}

Function New-Backup {
    param (
        [String] $VMName,
        [String] $DriveLetter,
        [String] $HvServer,
        [String] $VMIpv4,
        [String] $VMPort
    )
    # Remove Existing Backup Policy
    try {
        Remove-WBPolicy -all -force
    }
    Catch {
        LogMsg "No existing backup policy to remove"
    }
    # Set up a new Backup Policy
    $policy = New-WBPolicy
    # Set the backup location
    $backupLocation = New-WBBackupTarget -VolumePath $DriveLetter
    # Define VSS WBBackup type
    Set-WBVssBackupOption -Policy $policy -VssCopyBackup
    # Add the Virtual machines to the list
    $VM = Get-WBVirtualMachine | Where-Object VMName -like $VMName
    Add-WBVirtualMachine -Policy $policy -VirtualMachine $VM
    Add-WBBackupTarget -Policy $policy -Target $backupLocation
    # Start the backup
    LogMsg "Backing to $DriveLetter"
    Start-WBBackup -Policy $policy
    # Review the results
    $BackupTime = (New-Timespan -Start (Get-WBJob -Previous 1).StartTime -End (Get-WBJob -Previous 1).EndTime).Minutes
    LogMsg "Backup duration: $BackupTime minutes"
    $sts=Get-WBJob -Previous 1
    if ($sts.JobState -ne "Completed" -or $sts.HResult -ne 0) {
        LogErr "VSS Backup failed"
        return $False
    }
    LogMsg "Backup successful!"
    # Let's wait a few Seconds
    Start-Sleep -Seconds 5
    # Delete file on the VM
    $vmState = $(Get-VM -name $VMName -ComputerName $HvServer).state
    if (-not $vmState) {
        RunLinuxCmd -username $user -password $password -ip $VMIpv4 -port $VMPort -command "rm /home/$user/1" -runAsSudo
        if (-not $?) {
            LogErr "Cannot delete test file!"
            return $False
        }
        LogMsg "File deleted on VM: $VMName"
    }
    return $backupLocation
}

Function Restore-Backup {
    param (
        $BackupLocation,
        $HypervGroupName,
        $VMName
    )
    # Start the Restore
    LogMsg "Now let's restore the VM from backup."
    # Get BackupSet
    $BackupSet = Get-WBBackupSet -BackupTarget $BackupLocation
    # Start restore
    Start-WBHyperVRecovery -BackupSet $BackupSet -VMInBackup $BackupSet.Application[0].Component[0] -Force -WarningAction SilentlyContinue
    $sts=Get-WBJob -Previous 1
    if ($sts.JobState -ne "Completed" -or $sts.HResult -ne 0) {
        LogErr "VSS Restore failed"
        return $False
    }
    # Add VM to VMGroup
    Add-VMGroupMember -Name $HypervGroupName -VM $(Get-VM -name $VMName)
    return $True
}

Function Check-VMStateAndFileStatus {
    param (
        [String] $VMName,
        [String] $HvServer,
        [String] $VMIpv4,
        [String] $VMPort
    )

    # Review the results
    $RestoreTime = (New-Timespan -Start (Get-WBJob -Previous 1).StartTime -End (Get-WBJob -Previous 1).EndTime).Minutes
    LogMsg "Restore duration: $RestoreTime minutes"
    # Make sure VM exists after VSS backup/restore operation
    $vm = Get-VM -Name $VMName -ComputerName $HvServer
    if (-not $vm) {
        LogErr "VM ${VMName} does not exist after restore"
        return $False
    }
    LogMsg "Restore success!"
    $vmState = (Get-VM -name $VMName -ComputerName $HvServer).state
    LogMsg "VM state is $vmState"
    $ip_address = Get-IPv4ViaKVP $VMName $HvServer
    $timeout = 300
    if ($vmState -eq "Running") {
        if ($null -eq $ip_address) {
            LogMsg "Restarting VM ${VMName} to bring up network"
            Restart-VM -vmName $VMName -ComputerName $HvServer
            Wait-ForVMToStartKVP $VMName $HvServer $timeout
            $ip_address = Get-IPv4ViaKVP $VMName $HvServer
        }
    }
    elseif ($vmState -eq "Off" -or $vmState -eq "saved" ) {
        LogMsg "Starting VM : ${VMName}"
        Start-VM -vmName $VMName -ComputerName $HvServer
        if (-not (Wait-ForVMToStartKVP $VMName $HvServer $timeout )) {
            LogErr "${VMName} failed to start"
            return $False
        }
        else {
            $ip_address = Get-IPv4ViaKVP $VMName $HvServer
        }
    }
    elseif ($vmState -eq "Paused") {
        LogMsg "Resuming VM : ${VMName}"
        Resume-VM -vmName $VMName -ComputerName $HvServer
        if (-not (Wait-ForVMToStartKVP $VMName $HvServer $timeout )) {
            LogErr "${VMName} failed to resume"
            return $False
        }
        else {
            $ip_address = Get-IPv4ViaKVP $VMName $HvServer
        }
    }
    LogMsg "${VMName} IP is $ip_address"
    # check selinux denied log after ip injection
    $sts=Get-SelinuxAVCLog -ipv4 $VMIpv4 -SSHPort $VMPort -Username "root" -Password $password
    if (-not $sts) {
        return $False
    }
    # only check restore file when ip available
    $stsipv4 = Test-NetConnection $VMIpv4 -Port 22 -WarningAction SilentlyContinue
    if ($stsipv4.TcpTestSucceeded) {
        $sts=Check-FileInLinuxGuest -VMPassword $password -VMPort $VMPort -VMUserName $user -Ipv4 $VMIpv4 -fileName "/home/$user/1"
        if (-not $sts) {
            LogErr "No /home/$user/1 file after restore"
            return $False
        }
        else {
            LogMsg "there is /home/$user/1 file after restore"
        }
    }
    else {
        LogMsg "Ignore checking file /home/$user/1 when no network"
    }
    return $True
}

Function Remove-Backup {
    param (
        [String] $BackupLocation
    )
    # Remove Created Backup
    LogMsg "Removing old backups from $BackupLocation"
    try {
        Remove-WBBackupSet -BackupTarget $BackupLocation -Force -WarningAction SilentlyContinue
    }
    Catch {
        LogMsg "No existing backups to remove"
    }
}

Function Get-BackupType() {
    # check the latest successful job backup type, "online" or "offline"
    $backupType = $null
    $sts = Get-WBJob -Previous 1
    if ($sts.JobState -ne "Completed" -or $sts.HResult -ne 0) {
        LogErr "Error: VSS Backup failed "
        return $backupType
    }
    $contents = get-content $sts.SuccessLogPath
    foreach ($line in $contents ) {
        if ( $line -match "Caption" -and $line -match "online") {
            LogMsg "VSS Backup type is online"
            $backupType = "online"
        }
        elseif ($line -match "Caption" -and $line -match "offline") {
            LogMsg "VSS Backup type is offline"
            $backupType = "offline"
        }
    }
    return $backupType
}

Function Get-DriveLetter {
    param (
        [string] $VMName,
        [string] $HvServer
    )
    if ($null -eq $VMName) {
        LogErr "VM ${VMName} name was not specified."
        return $False
    }
    # Get the letter of the mounted backup drive
    $tempFile = (Get-VMHost -ComputerName $HvServer).VirtualHardDiskPath + "\" + $VMName + "_DRIVE_LETTER.txt"
    if(Test-Path ($tempFile)) {
        $global:driveletter = Get-Content -Path $tempFile
        # To avoid PSUseDeclaredVarsMoreThanAssignments warning when run PS Analyzer
        LogMsg "global parameter driveletter is set to $global:driveletter"
        return $True
    }
    else {
        return $False
    }
}

#Check if stress-ng is installed
Function Is-StressNgInstalled {
    param (
        [String] $VMIpv4,
        [String] $VMSSHPort
    )

    $cmdToVM = @"
#!/bin/bash
        command -v stress-ng
        sts=`$?
        exit `$sts
"@
    #"pingVMs: sending command to vm: $cmdToVM"
    $FILE_NAME  = "CheckStress-ng.sh"
    Set-Content $FILE_NAME "$cmdToVM"
    # send file
    RemoteCopy -uploadTo $VMIpv4 -port $VMSSHPort -files $FILE_NAME -username $user -password $password -upload
    # execute command
    $retVal = RunLinuxCmd -username $user -password $password -ip $VMIpv4 -port $VMSSHPort `
        -command "echo $password | sudo -S cd /root && chmod u+x ${FILE_NAME} && sed -i 's/\r//g' ${FILE_NAME} && ./${FILE_NAME}"
    return $retVal
}

# function for starting stress-ng
Function Start-StressNg {
    param (
        [String] $VMIpv4,
        [String] $VMSSHPort
    )
    LogMsg "IP is $VMIpv4"
    LogMsg "port is $VMSSHPort"
      $cmdToVM = @"
#!/bin/bash
        __freeMem=`$(cat /proc/meminfo | grep -i MemFree | awk '{ print `$2 }')
        __freeMem=`$((__freeMem/1024))
        echo ConsumeMemory: Free Memory found `$__freeMem MB >> /root/HotAdd.log 2>&1
        __threads=32
        __chunks=`$((`$__freeMem / `$__threads))
        echo "Going to start `$__threads instance(s) of stress-ng every 2 seconds, each consuming 128MB memory" >> /root/HotAdd.log 2>&1
        stress-ng -m `$__threads --vm-bytes `${__chunks}M -t 120 --backoff 1500000
        echo "Waiting for jobs to finish" >> /root/HotAdd.log 2>&1
        wait
        exit 0
"@
    #"pingVMs: sendig command to vm: $cmdToVM"
    $FILE_NAME = "ConsumeMem.sh"
    Set-Content $FILE_NAME "$cmdToVM"
    # send file
    RemoteCopy -uploadTo $VMIpv4 -port $VMSSHPort -files $FILE_NAME `
        -username $user -password $password -upload
    # execute command as job
    $retVal = RunLinuxCmd -username $user -password $password -ip $VMIpv4 -port $VMSSHPort `
        -command "echo $password | sudo -S cd /root && chmod u+x ${FILE_NAME} && sed -i 's/\r//g' ${FILE_NAME} && ./${FILE_NAME}"
    return $retVal
}
# This function runs the remote script on VM.
# It checks the state of execution of remote script
Function Invoke-RemoteScriptAndCheckStateFile
{
    param (
        $remoteScript,
        $VMUser,
        $VMPassword,
        $VMIpv4,
        $VMPort
        )
    $stateFile = "${remoteScript}.state.txt"
    $Hypervcheck = "echo '${VMPassword}' | sudo -S -s eval `"export HOME=``pwd``;bash ${remoteScript} > ${remoteScript}.log`""
    RunLinuxCmd -username $VMUser -password $VMPassword -ip $VMIpv4 -port $VMPort $Hypervcheck -runAsSudo
    RemoteCopy -download -downloadFrom $VMIpv4 -files "/home/${user}/state.txt" `
        -downloadTo $LogDir -port $VMPort -username $VMUser -password $password
    RemoteCopy -download -downloadFrom $VMIpv4 -files "/home/${user}/${remoteScript}.log" `
        -downloadTo $LogDir -port $VMPort -username $VMUser -password $VMPassword
    rename-item -path "${LogDir}\state.txt" -newname $stateFile
    $contents = Get-Content -Path $LogDir\$stateFile
    if (($contents -eq "TestAborted") -or ($contents -eq "TestFailed")) {
        return $False
    }
    return $True
}

function Get-KVPItem {
    param (
        $VMName,
        $server,
        $keyName,
        $Intrinsic
    )

    $vm = Get-WmiObject -ComputerName $server -Namespace root\virtualization\v2 -Query "Select * From Msvm_ComputerSystem Where ElementName=`'$VMName`'"
    if (-not $vm)
    {
        return $Null
    }

    $kvpEc = Get-WmiObject -ComputerName $server  -Namespace root\virtualization\v2 -Query "Associators of {$vm} Where AssocClass=Msvm_SystemDevice ResultClass=Msvm_KvpExchangeComponent"
    if (-not $kvpEc)
    {
        return $Null
    }

    $kvpData = $Null

    if ($Intrinsic)
    {
        $kvpData = $KvpEc.GuestIntrinsicExchangeItems
    }else{
        $kvpData = $KvpEc.GuestExchangeItems
    }

    if ($kvpData -eq $Null)
    {
        return $Null
    }

    foreach ($dataItem in $kvpData)
    {
        $key = $null
        $value = $null
        $xmlData = [Xml] $dataItem

        foreach ($p in $xmlData.INSTANCE.PROPERTY)
        {
            if ($p.Name -eq "Name")
            {
                $key = $p.Value
            }

            if ($p.Name -eq "Data")
            {
                $value = $p.Value
            }
        }
        if ($key -eq $keyName)
        {
            return $value
        }
    }

    return $Null
}

#This function does hot add/remove of Max NICs
function Test-MaxNIC {
    param(
    $vmName,
    $hvServer,
    $switchName,
    $actionType,
    [int] $nicsAmount
    )
    for ($i=1; $i -le $nicsAmount; $i++)
    {
    $nicName = "External" + $i

    if ($actionType -eq "add")
    {
        LogMsg "Ensure the VM does not have a Synthetic NIC with the name '${nicName}'"
        $null = Get-VMNetworkAdapter -vmName $vmName -Name "${nicName}" -ComputerName $hvServer -ErrorAction SilentlyContinue
        if ($?)
        {
        LogErr "VM '${vmName}' already has a NIC named '${nicName}'"
        }
    }

    LogMsg "Hot '${actionType}' a synthetic NIC with name of '${nicName}' using switch '${switchName}'"
    LogMsg "Hot '${actionType}' '${switchName}' to '${vmName}'"
    if ($actionType -eq "add")
    {
        Add-VMNetworkAdapter -VMName $vmName -SwitchName $switchName -ComputerName $hvServer -Name ${nicName} #-ErrorAction SilentlyContinue
    }
    else
    {
        Remove-VMNetworkAdapter -VMName $vmName -Name "${nicName}" -ComputerName $hvServer -ErrorAction SilentlyContinue
    }
    if (-not $?)
    {
        LogErr "Unable to Hot '${actionType}' NIC to VM '${vmName}' on server '${hvServer}'"
        }
    }
}

# This function is used for generating load using Stress NG tool
function Get-MemoryStressNG([String]$VMIpv4, [String]$VMSSHPort, [int]$timeoutStress, [int64]$memMB, [int]$duration, [int64]$chunk)
{
    LogMsg "Get-MemoryStressNG started to generate memory load"
    $cmdToVM = @"
#!/bin/bash
        if [ ! -e /proc/meminfo ]; then
          echo "ConsumeMemory: no meminfo found. Make sure /proc is mounted" >> /root/HotAdd.log 2>&1
          exit 100
        fi

        rm ~/HotAddErrors.log -f
        __totalMem=`$(cat /proc/meminfo | grep -i MemTotal | awk '{ print `$2 }')
        __totalMem=`$((__totalMem/1024))
        echo "ConsumeMemory: Total Memory found `$__totalMem MB" >> /root/HotAdd.log 2>&1
        declare -i __chunks
        declare -i __threads
        declare -i duration
        declare -i timeout
        if [ $chunk -le 0 ]; then
            __chunks=128
        else
            __chunks=512
        fi
        __threads=`$(($memMB/__chunks))
        if [ $timeoutStress -eq 0 ]; then
            timeout=10000000
            duration=`$((10*__threads))
        elif [ $timeoutStress -eq 1 ]; then
            timeout=5000000
            duration=`$((5*__threads))
        elif [ $timeoutStress -eq 2 ]; then
            timeout=1000000
            duration=`$__threads
        else
            timeout=1
            duration=30
            __threads=4
            __chunks=2048
        fi

        if [ $duration -ne 0 ]; then
            duration=$duration
        fi
        echo "Stress-ng info: `$__threads threads :: `$__chunks MB chunk size :: `$((`$timeout/1000000)) seconds between chunks :: `$duration seconds total stress time" >> /root/HotAdd.log 2>&1
        stress-ng -m `$__threads --vm-bytes `${__chunks}M -t `$duration --backoff `$timeout
        echo "Waiting for jobs to finish" >> /root/HotAdd.log 2>&1
        wait
        exit 0
"@

    $FILE_NAME = "ConsumeMem.sh"
    Set-Content $FILE_NAME "$cmdToVM"
    # send file
    RemoteCopy -uploadTo $VMIpv4 -port $VMSSHPort -files $FILE_NAME -username $user -password $password -upload
    LogMsg "remotecopy done"
    # execute command
    $sendCommand = "echo $password | sudo -S cd /root && chmod u+x ${FILE_NAME} && sed -i 's/\r//g' ${FILE_NAME} && ./${FILE_NAME}"
    $retVal = RunLinuxCmd -username $user -password $password -ip $VMIpv4 -port $VMSSHPort -command $sendCommand  -runAsSudo
    return $retVal
}

# This function installs Stress NG/Stress APP
Function Publish-App([string]$appName, [string]$customIP, [string]$appGitURL, [string]$appGitTag,[String] $VMSSHPort)
{
    # check whether app is already installed
    if ($null -eq $appGitURL) {
        LogMsg "ERROR: $appGitURL is not set"
        return $False
    }
    $retVal = RunLinuxCmd -username $user -password $password -ip $customIP -port $VMSSHPort `
        -command "echo $password | sudo -S cd /root; git clone $appGitURL $appName > /dev/null 2>&1"
    if ($appGitTag) {
        $retVal = RunLinuxCmd -username $user -password $password -ip $customIP -port $VMSSHPort `
        -command "cd $appName; git checkout tags/$appGitTag > /dev/null 2>&1"
    }
    if ($appName -eq "stress-ng") {
        $appInstall = "cd $appName; echo '${password}' | sudo -S make install"
        $retVal = RunLinuxCmd -username $user -password $password -ip $customIP -port $VMSSHPort `
             -command $appInstall
    }
    else {
    $appInstall = "cd $appName;./configure;make;echo '${password}' | sudo -S make install"
    $retVal = RunLinuxCmd -username $user -password $password -ip $customIP -port $VMSSHPort `
        -command $appInstall
    }
    LogMsg "App $appName Installation is completed"
    return $retVal
}
# Set the Integration Service status based on service name and expected service status.
function Set-IntegrationService {
    param (
        [string] $VMName,
        [string] $HvServer,
        [string] $ServiceName,
        [boolean] $ServiceStatus
    )
    if (@("Guest Service Interface", "Time Synchronization", "Heartbeat", "Key-Value Pair Exchange", "Shutdown","VSS") -notcontains $ServiceName) {
        LogErr "Unknown service type: $ServiceName"
        return $false
    }
    if ($ServiceStatus -eq $false) {
        Disable-VMIntegrationService -ComputerName $HvServer -VMName $VMName -Name $ServiceName
    }
    else {
        Enable-VMIntegrationService -ComputerName $HvServer -VMName $VMName -Name $ServiceName
    }
    $status = Get-VMIntegrationService -ComputerName $HvServer -VMName $VMName -Name $ServiceName
    if ($status.Enabled -ne $ServiceStatus) {
        LogErr "The $ServiceName service could not be set as $ServiceStatus"
        return $False
    }
    return $True
}
#######################################################################
# Fix snapshots. If there are more than one remove all except latest.
#######################################################################
function Restore-LatestVMSnapshot($vmName, $hvServer)
{
    # Get all the snapshots
    $vmsnapshots = Get-VMSnapshot -VMName $vmName -ComputerName $hvServer
    $snapnumber = ${vmsnapshots}.count
    # Get latest snapshot
    $latestsnapshot = Get-VMSnapshot -VMName $vmName -ComputerName $hvServer | Sort-Object CreationTime | Select-Object -Last 1
    $LastestSnapName = $latestsnapshot.name
    # Delete all snapshots except the latest
    if (1 -gt $snapnumber) {
        LogMsg "$vmName has $snapnumber snapshots. Removing all except $LastestSnapName"
        foreach ($snap in $vmsnapshots) {
            if ($snap.id -ne $latestsnapshot.id) {
                $snapName = ${snap}.Name
                $sts = Remove-VMSnapshot -Name $snap.Name -VMName $vmName -ComputerName $hvServer
                if (-not $?) {
                    LogErr "Unable to remove snapshot $snapName of ${vmName}: `n${sts}"
                    return $False
                }
                LogMsg "Removed snapshot $snapName"
            }
        }
    }
    # If there are no snapshots, create one.
    ElseIf (0 -eq $snapnumber) {
        LogMsg "There are no snapshots for $vmName. Creating one ..."
        $sts = Checkpoint-VM -VMName $vmName -ComputerName $hvServer
        if (-not $?) {
           LogErr "Unable to create snapshot of ${vmName}: `n${sts}"
           return $False
        }
    }
    return $True
}
