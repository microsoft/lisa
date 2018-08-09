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
        Write-Host "Unable to LogError : $now : $text"
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
            $TempXml = [xml](Get-Content $file.FullName)
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
		RemoteCopy -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files ".\Testscripts\Linux\enableRoot.sh,.\Testscripts\Linux\enablePasswordLessRoot.sh,.\Testscripts\Linux\provisionLinuxForLisa.sh" -username $user -password $password -upload
		$out = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -command "chmod +x /home/$user/*.sh" -runAsSudo			
		$rootPasswordSet = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -command "/home/$user/enableRoot.sh -password $($password.Replace('"',''))" -runAsSudo
		LogMsg $rootPasswordSet
		if (( $rootPasswordSet -imatch "ROOT_PASSWRD_SET" ) -and ( $rootPasswordSet -imatch "SSHD_RESTART_SUCCESSFUL" ))
		{
			LogMsg "root user enabled for $($vmData.RoleName) and password set to $password"
		}
		else
		{
			Throw "Failed to enable root password / starting SSHD service. Please check logs. Aborting test."
		}
		$out = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "cp -ar /home/$user/*.sh ."
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
            $out = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "rm -rf /root/sshFix*" 
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
	        foreach ( $vmData in $allVMData )
	        {
                RemoteCopy -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files ".\Testscripts\Linux\$scriptName,.\Testscripts\Linux\DetectLinuxDistro.sh" -username $user -password $password -upload
                if ( $CustomKernel.StartsWith("localfile:"))
                {
                    $customKernelFilePath = $CustomKernel.Replace('localfile:','')
                    RemoteCopy -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files ".\$customKernelFilePath" -username $user -password $password -upload                    
                }
                RemoteCopy -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files ".\Testscripts\Linux\$scriptName,.\Testscripts\Linux\DetectLinuxDistro.sh" -username $user -password $password -upload

                $out = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -command "chmod +x *.sh" -runAsSudo
                $currentKernelVersion = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -command "uname -r"
		        LogMsg "Executing $scriptName ..."
		        $jobID = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -command "/home/$user/$scriptName -CustomKernel $CustomKernel -logFolder /home/$user" -RunInBackground -runAsSudo
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
                $out = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "chmod +x *.sh" -runAsSudo
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
            $jobCount = 0
            $kernelSuccess = 0
	        $packageInstallJobs = @()
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
                    $out = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -command "chmod +x *.sh" -runAsSudo                    
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
		$tempout = RemoteCopy  -upload -uploadTo $VIP -port $SSHport -files ".\Testscripts\Linux\DetectLinuxDistro.sh" -username $testVMUser -password $testVMPassword 2>&1 | Out-Null
		$tempout = RunLinuxCmd -username $testVMUser -password $testVMPassword -ip $VIP -port $SSHport -command "chmod +x *.sh" -runAsSudo 2>&1 | Out-Null
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
		Write-Host "Come on.. Mention at least one second bro ;-)"
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
			sleep -Seconds 1
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
				$out = RemoteCopy -uploadTo $VM.PublicIP -port $VM.SSHPort  -files "$Logdir\$randomFileName" -username $vmUser -password $vmPassword -upload
				Remove-Item -Path "$Logdir\$randomFileName" -Force
				$out = RunLinuxCmd -ip $VM.PublicIP -port $VM.SSHPort -username $vmUser -password $vmPassword -command "dmesg > /home/$vmUser/InitialBootLogs.txt" -runAsSudo
				$out = RemoteCopy -download -downloadFrom $VM.PublicIP -port $VM.SSHPort -files "/home/$vmUser/InitialBootLogs.txt" -downloadTo $BootLogDir -username $vmUser -password $vmPassword
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
				$out = RunLinuxCmd -ip $VM.PublicIP -port $VM.SSHPort -username $vmUser -password $vmPassword -command "dmesg > /home/$vmUser/FinalBootLogs.txt" -runAsSudo
				$out = RemoteCopy -download -downloadFrom $VM.PublicIP -port $VM.SSHPort -files "/home/$vmUser/FinalBootLogs.txt" -downloadTo $BootLogDir -username $vmUser -password $vmPassword
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
				if($KernelDiff -eq $null)
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
						LogMsg "Setting tags : $preserveKeyword = yes; testName = $testName"
						$hash = @{}
						$hash.Add($preserveKeyword,"yes")
						$hash.Add("testName","$testName")
						$out = Set-AzureRmResourceGroup -Name $($VM.ResourceGroupName) -Tag $hash
						LogMsg "Setting tags : calltrace = yes; testName = $testName"
						$hash = @{}
						$hash.Add("calltrace","yes")
						$hash.Add("testName","$testName")
						$out = Set-AzureRmResourceGroup -Name $($VM.ResourceGroupName) -Tag $hash
					}
					else
					{
						LogMsg "Adding preserve tag to $($VM.ServiceName) .."
						$out = Set-AzureService -ServiceName $($VM.ServiceName) -Description $preserveKeyword
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
			$out = RunLinuxCmd -ip $VM.PublicIP -port $VM.SSHPort -username $vmUser -password $vmPassword -command "dmesg > /home/$vmUser/CurrentKernelLogs.txt" -runAsSudo
			$out = RemoteCopy -download -downloadFrom $VM.PublicIP -port $VM.SSHPort -files "/home/$vmUser/CurrentKernelLogs.txt" -downloadTo $BootLogDir -username $vmUser -password $vmPassword
			LogMsg "$($VM.RoleName): $status Kernel logs collected ..SUCCESSFULLY"
			foreach ($errorLine in $errorLines)
			{
				LogMsg "Checking for $errorLine in kernel logs.."
				$KernelLogs = Get-Content $currentKernelLogFile 
				$callTraceFound  = $false
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

Function DeployVMs ($xmlConfig, $setupType, $Distro, $getLogsIfFailed = $false, $GetDeploymentStatistics = $false, [string]$region = "", [int]$timeOutSeconds = 600)
{
    $AzureSetup = $xmlConfig.config.$TestPlatform.General
	
	#Test Platform Azure
	if ( $TestPlatform -eq "Azure" )
	{
		$retValue = DeployResourceGroups  -xmlConfig $xmlConfig -setupType $setupType -Distro $Distro -getLogsIfFailed $getLogsIfFailed -GetDeploymentStatistics $GetDeploymentStatistics -region $region
	}
	if ( $TestPlatform -eq "HyperV" )
	{
		$retValue = DeployHyperVGroups  -xmlConfig $xmlConfig -setupType $setupType -Distro $Distro -getLogsIfFailed $getLogsIfFailed -GetDeploymentStatistics $GetDeploymentStatistics
		
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
							echo y | .\tools\pscp -i .\ssh\$sshKey -q -P $port $tarFileName $username@${uploadTo}:
							$returnCode = $LASTEXITCODE
						}
						else
						{
							LogMsg "Uploading $tarFileName to $username : $uploadTo, port $port using Password authentication"
							$curDir = $PWD
							$uploadStatusRandomFile = ".\Temp\UploadStatusFile" + (Get-Random -Maximum 9999 -Minimum 1111) + ".txt"
							$uploadStartTime = Get-Date
							$uploadJob = Start-Job -ScriptBlock { cd $args[0]; Write-Host $args; Set-Content -Value "1" -Path $args[6]; $username = $args[4]; $uploadTo = $args[5]; echo y | .\tools\pscp -v -pw $args[1] -q -P $args[2] $args[3] $username@${uploadTo}: ; Set-Content -Value $LASTEXITCODE -Path $args[6];} -ArgumentList $curDir,$password,$port,$tarFileName,$username,${uploadTo},$uploadStatusRandomFile
							sleep -Milliseconds 100
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
								sleep -Seconds 1
								$uploadJobStatus = Get-Job -Id $uploadJob.Id
							}
							Write-Host ""
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
							Write-Host "Error in upload after $retry Attempt,Hence giving up"
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
					$recurse = ""
					while($retry -le $maxRetry)
					{
						if($usePrivateKey)
						{
							LogMsg "Uploading $testFile to $username : $uploadTo, port $port using PrivateKey authentication"
							echo y | .\tools\pscp -i .\ssh\$sshKey -q -P $port $testFile $username@${uploadTo}:
							$returnCode = $LASTEXITCODE
						}
						else
						{
							LogMsg "Uploading $testFile to $username : $uploadTo, port $port using Password authentication"
							$curDir = $PWD
							$uploadStatusRandomFile = ".\Temp\UploadStatusFile" + (Get-Random -Maximum 9999 -Minimum 1111) + ".txt"
							$uploadStartTime = Get-Date
							$uploadJob = Start-Job -ScriptBlock { cd $args[0]; Write-Host $args; Set-Content -Value "1" -Path $args[6]; $username = $args[4]; $uploadTo = $args[5]; echo y | .\tools\pscp -v -pw $args[1] -q -P $args[2] $args[3] $username@${uploadTo}: ; Set-Content -Value $LASTEXITCODE -Path $args[6];} -ArgumentList $curDir,$password,$port,$testFile,$username,${uploadTo},$uploadStatusRandomFile
							sleep -Milliseconds 100
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
								sleep -Seconds 1
								$uploadJobStatus = Get-Job -Id $uploadJob.Id
							}
							Write-Host ""
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
							Write-Host "Error in upload after $retry Attempt,Hence giving up"
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
				$recurse = ""
				while($retry -le $maxRetry)
				{
					if($usePrivateKey)
					{
						LogMsg "Downloading $testFile from $username : $downloadFrom,port $port to $downloadTo using PrivateKey authentication"
						$curDir = $PWD
						$downloadStatusRandomFile = ".\Temp\DownloadStatusFile" + (Get-Random -Maximum 9999 -Minimum 1111) + ".txt"
						$downloadStartTime = Get-Date
						$downloadJob = Start-Job -ScriptBlock { $curDir=$args[0];$sshKey=$args[1];$port=$args[2];$testFile=$args[3];$username=$args[4];${downloadFrom}=$args[5];$downloadTo=$args[6];$downloadStatusRandomFile=$args[7]; cd $curDir; Set-Content -Value "1" -Path $args[6]; echo y | .\tools\pscp -i .\ssh\$sshKey -q -P $port $username@${downloadFrom}:$testFile $downloadTo; Set-Content -Value $LASTEXITCODE -Path $downloadStatusRandomFile;} -ArgumentList $curDir,$sshKey,$port,$testFile,$username,${downloadFrom},$downloadTo,$downloadStatusRandomFile
						sleep -Milliseconds 100
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
							sleep -Seconds 1
							$downloadJobStatus = Get-Job -Id $downloadJob.Id
						}
						Write-Host ""
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
							cd $curDir; 
							echo y | .\tools\pscp.exe  -v -2 -unsafe -pw $password -q -P $port $username@${downloadFrom}:$testFile $downloadTo 2> $downloadStatusRandomFile; 
							Add-Content -Value "DownloadExtiCode_$LASTEXITCODE" -Path $downloadStatusRandomFile;
						} -ArgumentList $curDir,$password,$port,$testFile,$username,${downloadFrom},$downloadTo,$downloadStatusRandomFile
						sleep -Milliseconds 100
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
							sleep -Seconds 1
							$downloadJobStatus = Get-Job -Id $downloadJob.Id
						}
						Write-Host ""
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
						Write-Host "Error in download after $retry Attempt,Hence giving up"
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
    if ( ( $lastLinuxCmd -eq $command) -and ($lastIP -eq $ip) -and ($lastPort -eq $port) -and ($lastUser -eq $username) )
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
	    del "$LogDir\runtest.sh"
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
				cd $args[0]; `
				#Write-Host ".\tools\plink.exe -t -C -v -pw $password -P $port $username@$ip $jcommand";`
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
				cd $args[0]; `
				#Write-Host ".\tools\plink.exe -t -C -v -pw $password -P $port $username@$ip $jcommand";`
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
				$JobOut = Get-Content $LogDir\$randomFileName
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
                #Write-Host "Attempt : $attemptswot+$attemptswt : Initiating command in Background Mode : $logCommand on $ip : $port"
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
                #Write-Host "Attempt : $attemptswot+$attemptswt : Executing $logCommand on $ip : $port" 
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
			#Write-Host "Attempt : $attemptswot+$attemptswt : Executing $logCommand on $ip : $port"
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
				$TestName = $CurrentTestData.TestName
				$FilesToDownload = "$($vmData.RoleName)-*.txt"
				$out = RemoteCopy -upload -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files .\Testscripts\Linux\CollectLogFile.sh -username $user -password $password
				$out = RunLinuxCmd -username $user -password $password -ip $vmData.PublicIP -port $vmData.SSHPort -command "bash CollectLogFile.sh" -ignoreLinuxExitCode -runAsSudo
				$out = RemoteCopy -downloadFrom $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -files "$FilesToDownload" -downloadTo "$LogDir" -download
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
				#Write-Host $finalLine
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
				UploadTestResultToDatabase -TestPlatform $TestPlatform -TestLocation $TestLocation -TestCategory $TestCategory `
				-TestArea $TestArea -TestName $CurrentTestData.TestName -CurrentTestResult $CurrentTestResult `
				-ExecutionTag $ResultDBTestTag -GuestDistro $GuestDistro -KernelVersion $KernelVersion `
				-LISVersion $LISVersion -HostVersion $HostVersion -VMSize $VMSize -Networking $Networking `
				-ARMImage $ARMImage -OsVHD $OsVHD -BuildURL $env:BUILD_URL
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
					$KernelLogOutput=GetAndCheckKernelLogs -allDeployedVMs $allVMData -status "Final"
				}
				catch 
				{
					$ErrorMessage =  $_.Exception.Message
					LogMsg "EXCEPTION in GetAndCheckKernelLogs(): $ErrorMessage"	
				}
			}			
			$isClened = @()
			$ResourceGroups = $ResourceGroups.Split("^")
			$isVMLogsCollected = $false
			foreach ($group in $ResourceGroups)
			{
				if ($ForceDeleteResources)
				{
					LogMsg "-ForceDeleteResources is Set. Deleting $group."
					if ($TestPlatform -eq "Azure")
					{
						$isClened = DeleteResourceGroup -RGName $group

					}
					elseif ($TestPlatform -eq "HyperV")
					{
						$isClened = DeleteHyperVGroup -HyperVGroupName $group										
					}
					if (!$isClened)
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
										$isClened = DeleteResourceGroup -RGName $group

									}
									elseif ($TestPlatform -eq "HyperV")
									{
										$isClened = DeleteHyperVGroup -HyperVGroupName $group										
									}
									if (!$isClened)
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
							LogMsg "Setting tags : preserve = yes; testName = $testName"
							$hash = @{}
							$hash.Add($preserveKeyword,"yes")
							$hash.Add("testName","$testName")
							$out = Set-AzureRmResourceGroup -Name $group -Tag $hash
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
			UploadTestResultToDatabase -TestPlatform $TestPlatform -TestLocation $TestLocation -TestCategory $TestCategory -TestArea $TestArea -TestName $CurrentTestData.TestName -CurrentTestResult $CurrentTestResult -ExecutionTag $ResultDBTestTag -GuestDistro $GuestDistro -KernelVersion $KernelVersion -LISVersion $LISVersion -HostVersion $HostVersion -VMSize $VMSize -Networking $Networking -ARMImage $ARMImage -OsVHD $OsVHD -BuildURL $env:BUILD_URL
			LogMsg "Skipping cleanup, as No services / resource groups / HyperV Groups deployed for cleanup!"
		}
	}
	catch
	{
		$ErrorMessage =  $_.Exception.Message
		Write-Host "EXCEPTION in DoTestCleanUp : $ErrorMessage"  
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
			$result[1] += "		  $currentTestName : $currentTestValue : $currentTestResult <br />"
		}
		$i = $i + 1
	}

	return $result
}

Function CreateResultSummary($testResult, $checkValues, $testName, $metaData)
{
	if ( $metaData )
	{
		$resultString = "		  $metaData : $testResult <br />"
	}
	else
	{
		$resultString = "		  $testResult <br />"
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
			RemoteCopy -upload -uploadTo $testIP -username $user -port $testPort -password $password -files '.\Testscripts\Linux\LIS-LogCollector.sh'
			RunLinuxCmd -username $user -password $password -ip $testIP -port $testPort -command 'chmod +x LIS-LogCollector.sh'
			$out = RunLinuxCmd -username $user -password $password -ip $testIP -port $testPort -command './LIS-LogCollector.sh -v' -runAsSudo
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
			$out = RunLinuxCmd -username $user -password $password -ip $testIP -port $testPort -command 'rm -rf *' -runAsSudo
			LogMsg "All files removed from /home/$user successfully. VM IP : $testIP PORT : $testPort"  
		}
		catch
		{
			$ErrorMessage =  $_.Exception.Message
			Write-Host "EXCEPTION : $ErrorMessage"
			Write-Host "Unable to remove files from IP : $testIP PORT : $testPort"  		
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
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name URL -Value $URL -Force
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name URLv6 -Value $URL -Force
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name Status -Value $Status -Force
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name InstanceSize -Value $InstanceSize -Force
		return $objNode
	}

	foreach ($ResourceGroup in $ResourceGroups.Split("^"))
	{
		LogMsg "Collecting $ResourceGroup data.."

		LogMsg "    Microsoft.Network/publicIPAddresses data collection in progress.."
		$RGIPdata = Get-AzureRmResource -ResourceGroupName $ResourceGroup -ResourceType "Microsoft.Network/publicIPAddresses" -Verbose -ExpandProperties
		LogMsg "    Microsoft.Compute/virtualMachines data collection in progress.."
		$RGVMs = Get-AzureRmResource -ResourceGroupName $ResourceGroup -ResourceType "Microsoft.Compute/virtualMachines" -Verbose -ExpandProperties
		LogMsg "    Microsoft.Network/networkInterfaces data collection in progress.."
		$NICdata = Get-AzureRmResource -ResourceGroupName $ResourceGroup -ResourceType "Microsoft.Network/networkInterfaces" -Verbose -ExpandProperties
		$currentRGLocation = (Get-AzureRmResourceGroup -ResourceGroupName $ResourceGroup).Location
		LogMsg "    Microsoft.Network/loadBalancers data collection in progress.."
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
			}
			$QuickVMNode.ResourceGroupName = $ResourceGroup
			
			$QuickVMNode.PublicIP = ($RGIPData | where { $_.Properties.publicIPAddressVersion -eq "IPv4" }).Properties.ipAddress
			$QuickVMNode.PublicIPv6 = ($RGIPData | where { $_.Properties.publicIPAddressVersion -eq "IPv6" }).Properties.ipAddress
			$QuickVMNode.URL = ($RGIPData | where { $_.Properties.publicIPAddressVersion -eq "IPv4" }).Properties.dnsSettings.fqdn
			$QuickVMNode.URLv6 = ($RGIPData | where { $_.Properties.publicIPAddressVersion -eq "IPv6" }).Properties.dnsSettings.fqdn
			$QuickVMNode.RoleName = $testVM.ResourceName
			$QuickVMNode.Status = $testVM.Properties.ProvisioningState
			$QuickVMNode.InstanceSize = $testVM.Properties.hardwareProfile.vmSize
			$QuickVMNode.Location = $currentRGLocation
			$allDeployedVMs += $QuickVMNode
		}
		LogMsg "Collected $ResourceGroup data!"		
	}
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
		$out = RunLinuxCmd -username $testVMUsername -password $testVMPassword -ip $testVMVIP -port $testVMSSHport -command "mkdir -p $mountPoint" -runAsSudo 
		$partitionNumber=1
		$PartitionDiskOut = RunLinuxCmd -username $testVMUsername -password $testVMPassword -ip $testVMVIP -port $testVMSSHport -command "./ManagePartitionOnDisk.sh -diskName $attachedDisk -create yes -forRaid no" -runAsSudo 
		$FormatDiskOut = RunLinuxCmd -username $testVMUsername -password $testVMPassword -ip $testVMVIP -port $testVMSSHport -command "time mkfs.$diskFileSystem $attachedDisk$partitionNumber" -runAsSudo -runMaxAllowedTime 2400 
		$out = RunLinuxCmd -username $testVMUsername -password $testVMPassword -ip $testVMVIP -port $testVMSSHport -command "mount -o nobarrier $attachedDisk$partitionNumber $mountPoint" -runAsSudo 
		Add-Content -Value $formatDiskOut -Path $LogPath -Force
		$ddOut = RunLinuxCmd -username $testVMUsername -password $testVMPassword -ip $testVMVIP -port $testVMSSHport -command "dd if=/dev/zero bs=1024 count=1000000 of=$mountPoint/file_1GB" -runAsSudo -runMaxAllowedTime 1200
		WaitFor -seconds 10
		Add-Content -Value $ddOut -Path $LogPath
		try
		{
			$out = RunLinuxCmd -username $testVMUsername -password $testVMPassword -ip $testVMVIP -port $testVMSSHport -command "umount $mountPoint" -runAsSudo 
		}
		catch
		{
			LogMsg "umount failed. Trying umount -l"
			$out = RunLinuxCmd -username $testVMUsername -password $testVMPassword -ip $testVMVIP -port $testVMSSHport -command "umount -l $mountPoint" -runAsSudo 
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
			if ($expectResult -ne $null)
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
    cd $sourcedir
    $out = Invoke-Expression "$7z a -mx5 $currentDir\$zipfilename * -r"
    cd $currentDir
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