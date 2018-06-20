Function DeployHyperVGroups ($xmlConfig, $setupType, $Distro, $getLogsIfFailed = $false, $GetDeploymentStatistics = $false)
{
    if( (!$EconomyMode) -or ( $EconomyMode -and ($xmlConfig.config.HyperV.Deployment.$setupType.isDeployed -eq "NO")))
    {
        try
        {
            $VerifiedGroups =  $NULL
            $retValue = $NULL
            $i = 0
            $role = 1
            $setupTypeData = $xmlConfig.config.$TestPlatform.Deployment.$setupType
            #DEBUGRG
            #$isAllDeployed = CreateAllHyperVGroupDeployments -setupType $setupType -xmlConfig $xmlConfig -Distro $Distro -region $region -storageAccount $storageAccount -DebugRG "ICA-RG-M1S1-SSTEST-GZBX-636621761998"
            $isAllDeployed = CreateAllHyperVGroupDeployments -setupType $setupType -xmlConfig $xmlConfig -Distro $Distro -HyperVHost "localhost"
            $isAllVerified = "False"
            $isAllConnected = "False"
            #$isAllDeployed = @("True","ICA-RG-IEndpointSingleHS-U1510-8-10-12-34-9","30")
            if($isAllDeployed[0] -eq "True")
            {
                $DeployedHyperVGroup = $isAllDeployed[1]
                $HyperVGroupCount = $isAllDeployed[2]
                $DeploymentElapsedTime = $isAllDeployed[3]
                $GroupsToVerify = $DeployedHyperVGroup.Split('^')
                $allVMData = GetAllHyperVDeployementData -HyperVGroupNames $DeployedHyperVGroup
                Set-Variable -Name allVMData -Value $allVMData -Force -Scope Global
                $isAllConnected = isAllSSHPortsEnabledRG -AllVMDataObject $allVMData
                if ($isAllConnected -eq "True")
                {
                    $VerifiedGroups = $DeployedHyperVGroup
                    $retValue = $VerifiedGroups
                    if ( Test-Path -Path  .\Extras\UploadDeploymentDataToDB.ps1 )
                    {
                        $out = .\Extras\UploadDeploymentDataToDB.ps1 -allVMData $allVMData -DeploymentTime $DeploymentElapsedTime.TotalSeconds
                    }
                    $KernelLogOutput= GetAndCheckKernelLogs -allDeployedVMs $allVMData -status "Initial"
                }
                else
                {
                    LogErr "Unable to connect Some/All SSH ports.."
                    $retValue = $NULL  
                }                
            }
            else
            {
                LogErr "One or More Deployments are Failed..!"
                $retValue = $NULL
            }
        }
        catch
        {
            LogMsg "Exception detected. Source : DeployVMs()"
            $line = $_.InvocationInfo.ScriptLineNumber
            $script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
            $ErrorMessage =  $_.Exception.Message
            LogErr "EXCEPTION : $ErrorMessage"
            LogErr "Source : Line $line in script $script_name."              
            $retValue = $NULL
        }
    }
    else
    {
        $retValue = $xmlConfig.config.$TestPlatform.Deployment.$setupType.isDeployed
        $KernelLogOutput= GetAndCheckKernelLogs -allDeployedVMs $allVMData -status "Initial"
    }
    if ( $GetDeploymentStatistics )
    {
        return $retValue, $DeploymentElapsedTime
    }
    else
    {
        return $retValue
    }
}

Function CreateAllHyperVGroupDeployments($setupType, $xmlConfig, $Distro, [string]$HyperVHost = "", $DebugRG = "")
{
    if (!$HyperVHost)
    {
        $HyperVHost = $xmlConfig.config.HyperV.Host.ServerName
    }
    if ($DebugRG)
    {
        return "True", $DebugRG, 1, 180
    }
    else
    {
        $HyperVGroupCount = 0
        LogMsg $setupType
        $setupTypeData = $xmlConfig.config.HyperV.Deployment.$setupType
        if($region)
        {
          $location = $region;
        }
        foreach ($HyperVGroupXML in $setupTypeData.ResourceGroup )
        {
            $validateStartTime = Get-Date
            $readyToDeploy = $false
            while (!$readyToDeploy)
            {
                #TBD Verify the readiness of the HyperV Host.
                $readyToDeploy = $true
            }
            if ($readyToDeploy)
            {
                $curtime = ([string]((Get-Date).Ticks / 1000000)).Split(".")[0]
                $randomNumber = $global4digitRandom
                $isHyperVGroupDeployed = "False"
                $retryDeployment = 0
                if ( $HyperVGroupXML.Tag -ne $null )
                {
                    $HyperVGroupName = "ICA-HG-" + $HyperVGroupXML.Tag + "-" + $Distro + "-" + "$shortRandomWord-" + "$curtime"
                }
                else
                {
                    $HyperVGroupName = "ICA-HG-" + $setupType + "-" + $Distro + "-" + "$shortRandomWord-" + "$curtime"
                }
                while (($isHyperVGroupDeployed -eq "False") -and ($retryDeployment -lt 1))
                {
                    if ($ExistingRG)
                    {
                        #TBD 
                        #Use existing HypeV group for test.
                    }
                    else
                    {
                        LogMsg "Creating HyperV Group : $HyperVGroupName."
                        LogMsg "Verifying that HyperV Group name is not in use."
                        $isHyperVGroupDeleted = DeleteHyperVGroup -HyperVGroupName $HyperVGroupName
                    }
                    if ($isHyperVGroupDeleted)
                    {    			
                        $CreatedHyperVGroup = CreateHyperVGroup -HyperVGroupName $HyperVGroupName
                        if ($CreatedHyperVGroup)
                        {
                            $DeploymentStartTime = (Get-Date)
                            $ExpectedVMs = 0
                            $HyperVGroupXML.VirtualMachine | ForEach-Object {$ExpectedVMs += 1}
                            $VMCreationStatus = CreateHyperVGroupDeployment -HyperVGroupName $HyperVGroupName -HyperVGroupXML $HyperVGroupXML
                            $DeploymentEndTime = (Get-Date)
                            $DeploymentElapsedTime = $DeploymentEndTime - $DeploymentStartTime
                            if ( $VMCreationStatus )
                            {
                                $StartVMStatus = StartHyperVGroupVMs -HyperVGroupName $HyperVGroupName
                                if ($StartVMStatus)
                                {
                                    $retValue = "True"
                                    $isHyperVGroupDeployed = "True"
                                    $HyperVGroupCount = $HyperVGroupCount + 1
                                    $DeployedHyperVGroup = $HyperVGroupName
                                }
                                else 
                                {
                                    LogErr "Unable to start one or more VM's"
                                    $retryDeployment = $retryDeployment + 1
                                    $retValue = "False"
                                    $isHyperVGroupDeployed = "False"
                                }
                            }
                            else
                            {
                                LogErr "Unable to Deploy one or more VM's"
                                $retryDeployment = $retryDeployment + 1
                                $retValue = "False"
                                $isHyperVGroupDeployed = "False"
                            }
                        }
                        else
                        {
                            LogErr "Unable to create $HyperVGroupName"
                            $retryDeployment = $retryDeployment + 1
                            $retValue = "False"
                            $isHyperVGroupDeployed = "False"
                        }
                    }    
                    else
                    {
                        LogErr "Unable to delete existing HyperV Group - $HyperVGroupName"
                        $retryDeployment += 1
                        $retValue = "False"
                        $isHyperVGroupDeployed = "False"
                    }
                }
            }
            else
            {
                LogErr "HyperV server is not ready to deploy."
                $retValue = "False"
                $isHyperVGroupDeployed = "False"
            }
        }
        return $retValue, $DeployedHyperVGroup, $HyperVGroupCount, $DeploymentElapsedTime
    }
}

Function DeleteHyperVGroup([string]$HyperVGroupName)
{
    $HyperVHost = $xmlConfig.config.HyperV.Host.ServerName
    try
    {
        LogMsg "Checking if HyperV VM group '$HyperVGroupName' exists in $HyperVHost..."
        $AllGroups = Get-VMGroup -Name $HyperVGroupName -ErrorAction SilentlyContinue -ComputerName $HyperVHost
    }
    catch
    {
    }
    if ($AllGroups)
    {
		if ($ExistingRG)
		{
			#TBD If user mentiones to use existing group, then skip the deletion of the HyperV group.
		}
		else
		{
            $CurrentGroup = $null
            $AllGroups = $null
            $AllGroups = Get-VMGroup -Name $HyperVGroupName -ErrorAction SilentlyContinue -ComputerName $HyperVHost
            foreach ( $CurrentGroup in $AllGroups )
            {
                if ( $CurrentGroup.VMMembers.Count -gt 0 )
                {
                    $CleanupVMList = @()
                    foreach ($CleanupVM in $CurrentGroup.VMMembers)
                    {
                        if ($VMnames)
                        {
                            if ( $VMNames.Split(",").Contains($CleanupVM.Name) )
                            {
                                $CleanupVMList += $CleanupVM
                            }
                        }
                        else
                        {
                            $CleanupVMList += $CleanupVM
                        }
                    }
                    foreach ($CleanupVM in $CleanupVMList)
                    {
                        $CleanupVM | Stop-VM -Force  -TurnOff
                        $VM = Get-VM -Id $CleanupVM.Id
                        foreach ($VHD in $CleanupVM.HardDrives)
                        {
                            
                            Remove-Item -Force -Path $VHD.Path 
                            LogMsg "$($VHD.Path) Removed!"
                        }
                        $CleanupVM | Remove-VM -Force 
                        LogMsg "$($CleanupVM.Name) Removed!"
                    }
                    Remove-VMGroup -Name $HyperVGroupName -Force 
                    LogMsg "$($HyperVGroupName) Removed!"
                }
                elseif ($CurrentGroup)
                {
                    LogMsg "$HyperVGroupName is empty. Removing..."
                    Remove-VMGroup -Name $HyperVGroupName -Force 
                    LogMsg "$HyperVGroupName Removed!"
                }
                else
                {
                    LogMsg "$HyperVGroupName does not exists."
                }
            }
        }
    }
    else
    {
        LogMsg "$HyperVGroupName does not exists."
        $retValue = $true
    }
    return $retValue
}

Function CreateHyperVGroup([string]$HyperVGroupName)
{
    $HyperVHost = $xmlConfig.config.HyperV.Host.ServerName
    $FailCounter = 0
    $retValue = "False"
    While(($retValue -eq $false) -and ($FailCounter -lt 5))
    {
        try
        {
            $FailCounter++
            LogMsg "Using HyperV server : $HyperVHost"
            $CreatedHyperVGroup = New-VMGroup -Name $HyperVGroupName -ComputerName $HyperVHost -GroupType VMCollectionType
            if ($?)
            {
                LogMsg "HyperV Group $HyperVGroupName Created with Instance ID: $($CreatedHyperVGroup.InstanceId)."
                $retValue = $CreatedHyperVGroup
            }
            else 
            {
                LogErr "Failed to HyperV Group $HyperVGroupName."
                $retValue = $false
                $FailCounter += 1
            }
        }
        catch
        {
            $retValue = $false
        }
    }
    return $retValue
}

Function CreateHyperVGroupDeployment([string]$HyperVGroup, $HyperVGroupNameXML)
{
    $HyperVHost = $xmlConfig.config.Hyperv.Host.ServerName
    $HyperVMappedSizes = [xml](Get-Content .\XML\AzureVMSizeToHyperVMapping.xml)
    $CreatedVMs =  @()
    #$OsVHD =  "SS-RHEL75-TEST-VHD-DYNAMIC.vhd"
    $OsVHD = $BaseOsVHD
    $VMSwitches = Get-VMSwitch  * | Where { $_.Name -imatch "Ext" }
    $ErrorCount = 0
    $SourceOsVHDPath = $xmlConfig.config.Hyperv.Host.SourceOsVHDPath
    $DestinationOsVHDPath = $xmlConfig.config.Hyperv.Host.DestinationOsVHDPath
    $i = 0
    $CurrentHyperVGroup = Get-VMGroup -Name $HyperVGroupName
    if ( $CurrentHyperVGroup.Count -eq 1)
    {
        foreach ( $VirtualMachine in $HyperVGroupXML.VirtualMachine)
        {
            if ( $VirtualMachine.RoleName)
            {
                $CurrentVMName = $VirtualMachine.RoleName
                $CurrentVMOsVHDPath = "$DestinationOsVHDPath\$HyperVGroupName-$CurrentVMName-diff-OSDisk.vhd"
            }
            else 
            {
                $CurrentVMName = $HyperVGroupName + "-role-$i"
                $CurrentVMOsVHDPath = "$DestinationOsVHDPath\$HyperVGroupName-role-$i-diff-OSDisk.vhd"
                $i += 1
            }
            $Out = New-VHD -ParentPath "$SourceOsVHDPath\$OsVHD" -Path $CurrentVMOsVHDPath 
            #Convert-VHD -Path "$SourceOsVHDPath\$OsVHD" -DestinationPath $CurrentVMOsVHDPath -VHDType Dynamic 
            if ($?)
            {
                LogMsg "Prerequiste: Prepare OS Disk $CurrentVMOsVHDPath - Succeeded."
                $CurrentVMCpu = $HyperVMappedSizes.HyperV.$($VirtualMachine.ARMInstanceSize).NumberOfCores
                $CurrentVMMemory = $HyperVMappedSizes.HyperV.$($VirtualMachine.ARMInstanceSize).MemoryInMB
                $CurrentVMMemory = [int]$CurrentVMMemory * 1024 * 1024
                LogMsg "New-VM -Name $CurrentVMName -MemoryStartupBytes $CurrentVMMemory -BootDevice VHD -VHDPath $CurrentVMOsVHDPath -Path .\Temp\VMData -Generation 1 -Switch $($VMSwitches.Name)"
                $NewVM = New-VM -Name $CurrentVMName -MemoryStartupBytes $CurrentVMMemory -BootDevice VHD -VHDPath $CurrentVMOsVHDPath -Path .\Temp\VMData -Generation 1 -Switch $($VMSwitches.Name)
                if ($?)
                {
                    $Out = Set-VM -VM $NewVM -ProcessorCount $CurrentVMCpu -StaticMemory  -CheckpointType Disabled -Notes "$HyperVGroupName"
                    $Out = Add-VMGroupMember -Name "$HyperVGroupName" -VM $NewVM
                }
                else 
                {
                    LogErr "Failed to create VM."
                    LogErr "Removing OS Disk : $CurrentVMOsVHDPath"
                    $Out = Remove-Item -Path $CurrentVMOsVHDPath -Force 
                    $ErrorCount += 1
                }
            }
            else 
            {
                LogMsg "Prerequiste: Prepare OS Disk $CurrentVMOsVHDPath - Failed." 
                $ErrorCount += 1   
            }
        }
    }
    else 
    {
        LogErr "There are $($CurrentHyperVGroup.Count) HyperV groups. We need 1 HyperV group."
        $ErrorCount += 1    
    }
    if ( $ErrorCount -eq 0 )
    {
        $ReturnValue = $true
    }
    else 
    {
        $ReturnValue = $false    
    }
    return $ReturnValue
}
Function StartHyperVGroupVMs($HyperVGroupName)
{
    $HyperVHost = $xmlConfig.config.Hyperv.Host.ServerName
    $AllVMs = Get-VMGroup -Name $HyperVGroupName
    $CurrentErrors = @()
    foreach ( $VM in $AllVMs.VMMembers)
    {
        LogMsg "Starting $($VM.Name) from $HyperVGroupName..."
        $StartVMStatus = Start-VM -VM $VM 
        if ( $? )
        {
            LogMsg "Succeeded."
        }
        else
        {
            LogErr "Failed"
            $CurrentErrors += "Starting $($VM.Name) from $HyperVGroupName failed."
        }
    }
    if($CurrentErrors.Count -eq 0)
    {
        $ReturnValue = $true
        $CurrentErrors | ForEach-Object { LogErr "$_" }
    }
    else 
    {
        $ReturnValue = $false    
    }
    return $ReturnValue
}

Function StopHyperVGroupVMs($HyperVGroupName)
{
    $HyperVHost = $xmlConfig.config.Hyperv.Host.ServerName
    $AllVMs = Get-VMGroup -Name $HyperVGroupName
    $CurrentErrors = @()
    foreach ( $VM in $AllVMs.VMMembers)
    {
        LogMsg "Shutting down $($VM.Name) from $HyperVGroupName..."
        $StopVMStatus = Stop-VM -VM $VM 
        if ( $? )
        {
            LogMsg "Succeeded."
        }
        else
        {
            LogErr "Shutdown failed. Turning off.."
            $StopVMStatus = Stop-VM -VM $VM  -Force -TurnOff
            if ( $? )
            {
                LogMsg "Succeeded."
            }
            else 
            {
                LogErr "Failed"
                $CurrentErrors += "Stopping $($VM.Name) from $HyperVGroupName failed."                
            }            
        }
    }
    if($CurrentErrors.Count -eq 0)
    {
        $ReturnValue = $true
        $CurrentErrors | ForEach-Object { LogErr "$_" }
    }
    else 
    {
        $ReturnValue = $false    
    }
    return $ReturnValue
}
Function GetAllHyperVDeployementData($HyperVGroupNames,$RetryCount = 100)
{
    $HyperVHost = $xmlConfig.config.Hyperv.Host.ServerName
    $allDeployedVMs = @()
    function CreateQuickVMNode()
    {
        $objNode = New-Object -TypeName PSObject
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name HyperVHost -Value $HyperVHost -Force
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name HyperVGroupName -Value $null -Force 
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name PublicIP -Value $null -Force
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name RoleName -Value $null -Force
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name SSHPort -Value 22 -Force
        return $objNode
    }
    $CurrentRetryAttempt = 0
    $AllPublicIPsCollected = $false
    $ALLVMs = @()
    foreach ($HyperVGroupName in $HyperVGroupNames.Split("^"))
    {
        LogMsg "Collecting $HyperVGroupName data.."
        $CurrentGroupData = Get-VMGroup -Name $HyperVGroupName
        foreach ( $VM in $CurrentGroupData.VMMembers)
        {
            $ALLVMs += $VM
        }
    }    
    while (( $CurrentRetryAttempt -le $RetryCount) -and (! $AllPublicIPsCollected ) )
    {
        $CurrentRetryAttempt += 1
        $RecheckVMs = @()
        foreach ( $VM in $AllVMs)
        {
            $QuickVMNode = CreateQuickVMNode
            LogMsg "    $($VM.Name) : Waiting for IP address..."
            $VMNicProperties = $VM | Get-VMNetworkAdapter
            $QuickVMNode.PublicIP = $VMNicProperties.IPAddresses | Where-Object {$_ -imatch "\b(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}\b"}
            if ($QuickVMNode.PublicIP -notmatch "\b(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}\b")
            {
                $RecheckVMs += $VM
                $AllPublicIPsCollected = $false
            }
            else 
            {
                $QuickVMNode.RoleName = $VM.Name
                $QuickVMNode.HyperVGroupName = $VM.Groups.Name
                $allDeployedVMs += $QuickVMNode
                LogMsg "    Collected $($QuickVMNode.RoleName) from $($QuickVMNode.HyperVGroupName) data!"
            }
        }
        if ($RecheckVMs)
        {
            $AllVMs = $RecheckVMs
            sleep 5
        }
        else 
        {
            $AllPublicIPsCollected = $true    
        }		
    }
    return $allDeployedVMs
}

Function RestartAllHyperVDeployments($allVMData)
{
    foreach ( $VM in $allVMData )
    {
        $out = StopHyperVGroupVMs -HyperVGroupName $VM.HyperVGroupName
    }
    foreach ( $VM in $allVMData )
    {
        $out = StartHyperVGroupVMs -HyperVGroupName $VM.HyperVGroupName
    }
	$isSSHOpened = isAllSSHPortsEnabledRG -AllVMDataObject $AllVMData
	return $isSSHOpened    
}