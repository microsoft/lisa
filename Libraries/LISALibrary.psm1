#
# This function enables the root password and ssh key based authentication across all VMs in same service / resource group.
# $allVMData : PSObject which contains all the VM data in same service / resource group.
# $installPackagesOnRoleName : [string] if you want to install packages on specific role only then use this parameter. Eg. ProvisionVMsForLisa -allVMData $VMData -installPackagesOnRoleName "master"
#    Multiple Rolenames can be given as "master,client"
#
Function ProvisionVMsForLisa($allVMData, $installPackagesOnRoleNames)
{
	$scriptUrl = "https://raw.githubusercontent.com/iamshital/lis-test/master/WS2012R2/lisa/remote-scripts/ica/provisionLinuxForLisa.sh"
	$sshPrivateKeyPath = ".\ssh\myPrivateKey.key"
	$sshPrivateKey = "myPrivateKey.key"
	LogMsg "Downloading $scriptUrl ..."
	$scriptName =  $scriptUrl.Split("/")[$scriptUrl.Split("/").Count-1]
	$start_time = Get-Date
	$out = Invoke-WebRequest -Uri $scriptUrl -OutFile "$LogDir\$scriptName"
	LogMsg "Time taken: $((Get-Date).Subtract($start_time).Seconds) second(s)"

    $keysGenerated = $false
	foreach ( $vmData in $allVMData )
	{
		LogMsg "Configuring $($vmData.RoleName) for LISA test..."
		RemoteCopy -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files ".\remote-scripts\enableRoot.sh,.\remote-scripts\enablePasswordLessRoot.sh,.\$LogDir\provisionLinuxForLisa.sh" -username $user -password $password -upload
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

function InstallCustomKernel ($customKernel, $allVMData, [switch]$RestartAfterUpgrade)
{
    try
    {
        $currentKernelVersion = ""
        $upgradedKernelVersion = ""
        $customKernel = $customKernel.Trim()
        if( ($customKernel -ne "linuxnext") -and ($customKernel -ne "netnext") -and ($customKernel -ne "proposed") -and ($customKernel -ne "latest") -and !($customKernel.EndsWith(".deb"))  -and !($customKernel.EndsWith(".rpm")) )
        {
            LogErr "Only linuxnext, netnext, proposed, latest are supported. E.g. -customKernel linuxnext/netnext/proposed. Or use -customKernel <link to deb file>, -customKernel <link to rpm file>"
        }
        else
        {
            $scriptName = "customKernelInstall.sh"
            $jobCount = 0
            $kernelSuccess = 0
	        $packageInstallJobs = @()
	        foreach ( $vmData in $allVMData )
	        {
                RemoteCopy -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files ".\remote-scripts\$scriptName,.\SetupScripts\DetectLinuxDistro.sh" -username $user -password $password -upload
                if ( $customKernel.StartsWith("localfile:"))
                {
                    $customKernelFilePath = $customKernel.Replace('localfile:','')
                    RemoteCopy -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files ".\$customKernelFilePath" -username $user -password $password -upload                    
                }
                RemoteCopy -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files ".\remote-scripts\$scriptName,.\SetupScripts\DetectLinuxDistro.sh" -username $user -password $password -upload

                $out = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -command "chmod +x *.sh" -runAsSudo
                $currentKernelVersion = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -command "uname -r"
		        LogMsg "Executing $scriptName ..."
		        $jobID = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -command "/home/$user/$scriptName -customKernel $customKernel -logFolder /home/$user" -RunInBackground -runAsSudo
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
				        $currentStatus = RunLinuxCmd -ip $job.PublicIP -port $job.SSHPort -username $user -password $password -command "tail -n 1 build-customKernel.txt"
				        LogMsg "Package Installation Status for $($job.RoleName) : $currentStatus"
				        $packageInstallJobsRunning = $true
			        }
			        else
			        {
                        if ( !(Test-Path -Path "$LogDir\$($job.RoleName)-build-customKernel.txt" ) )
                        {
				            RemoteCopy -download -downloadFrom $job.PublicIP -port $job.SSHPort -files "build-customKernel.txt" -username $user -password $password -downloadTo $LogDir
                            if ( ( Get-Content "$LogDir\build-customKernel.txt" ) -imatch "CUSTOM_KERNEL_SUCCESS" )
                            {
                                $kernelSuccess += 1
                            }
				            Rename-Item -Path "$LogDir\build-customKernel.txt" -NewName "$($job.RoleName)-build-customKernel.txt" -Force | Out-Null
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
                LogMsg "Kernel upgraded to `"$customKernel`" successfully in $($allVMData.Count) VM(s)."
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
                                if ($customKernel -eq "latest")
                                {
                                    LogMsg "Continuing the tests as default kernel is latest."
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

function InstallcustomLIS ($customLIS, $customLISBranch, $allVMData, [switch]$RestartAfterUpgrade)
{
    try
    {
        $customLIS = $customLIS.Trim()
        if( ($customLIS -ne "lisnext") -and !($customLIS.EndsWith("tar.gz")))
        {
            LogErr "Only lisnext and *.tar.gz links are supported. Use -customLIS lisnext -LISbranch <branch name>. Or use -customLIS <link to tar.gz file>"
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
                RemoteCopy -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files ".\remote-scripts\$scriptName,.\SetupScripts\DetectLinuxDistro.sh" -username "root" -password $password -upload
                $out = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "chmod +x *.sh" -runAsSudo
                $currentlisVersion = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "modinfo hv_vmbus"
		        LogMsg "Executing $scriptName ..."
		        $jobID = RunLinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "/root/$scriptName -customLIS $customLIS -LISbranch $customLISBranch" -RunInBackground -runAsSudo
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
				        $currentStatus = RunLinuxCmd -ip $job.PublicIP -port $job.SSHPort -username "root" -password $password -command "tail -n 1 build-customLIS.txt"
				        LogMsg "Package Installation Status for $($job.RoleName) : $currentStatus"
				        $packageInstallJobsRunning = $true
			        }
			        else
			        {
                        if ( !(Test-Path -Path "$LogDir\$($job.RoleName)-build-customLIS.txt" ) )
                        {
				            RemoteCopy -download -downloadFrom $job.PublicIP -port $job.SSHPort -files "build-customLIS.txt" -username "root" -password $password -downloadTo $LogDir
                            if ( ( Get-Content "$LogDir\build-customLIS.txt" ) -imatch "CUSTOM_LIS_SUCCESS" )
                            {
                                $lisSuccess += 1
                            }
				            Rename-Item -Path "$LogDir\build-customLIS.txt" -NewName "$($job.RoleName)-build-customLIS.txt" -Force | Out-Null
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
                LogMsg "lis upgraded to `"$customLIS`" successfully in all VMs."
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
                    RemoteCopy -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files ".\remote-scripts\$scriptName" -username $user -password $password -upload
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
