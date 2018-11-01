##############################################################################################
# HyperV.psm1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
    Required for Hyper-V test execution.

.PARAMETER
    <Parameters>

.INPUTS


.NOTES
    Creation Date:
    Purpose/Change:

.EXAMPLE


#>
###############################################################################################

Function DeployHyperVGroups ($xmlConfig, $setupType, $Distro, $getLogsIfFailed = $false, $GetDeploymentStatistics = $false, $VMGeneration = "1")
{
    if( (!$EconomyMode) -or ( $EconomyMode -and ($xmlConfig.config.HyperV.Deployment.$setupType.isDeployed -eq "NO")))
    {
        try
        {
            $VerifiedGroups =  $NULL
            $retValue = $NULL
            $isAllDeployed = CreateAllHyperVGroupDeployments -setupType $setupType -xmlConfig $xmlConfig `
                -Distro $Distro -VMGeneration $VMGeneration
            $isAllConnected = "False"

            if($isAllDeployed[0] -eq "True")
            {
                $DeployedHyperVGroup = $isAllDeployed[1]
                $DeploymentElapsedTime = $isAllDeployed[3]
                $allVMData = GetAllHyperVDeployementData -HyperVGroupNames $DeployedHyperVGroup
                Set-Variable -Name allVMData -Value $allVMData -Force -Scope Global
                if (!$allVMData) {
                    LogErr "One or more deployments failed..!"
                    $retValue = $NULL
                } else {
                    $isAllConnected = isAllSSHPortsEnabledRG -AllVMDataObject $allVMData
                    if ($isAllConnected -eq "True")
                    {
                        InjectHostnamesInHyperVVMs -allVMData $allVMData
                        $VerifiedGroups = $DeployedHyperVGroup
                        $retValue = $VerifiedGroups
                        if ( Test-Path -Path  .\Extras\UploadDeploymentDataToDB.ps1 )
                        {
                            .\Extras\UploadDeploymentDataToDB.ps1 -allVMData $allVMData -DeploymentTime $DeploymentElapsedTime.TotalSeconds
                        }
                        if(!$IsWindows)
                        {
                            GetAndCheckKernelLogs -allDeployedVMs $allVMData -status "Initial"
                        }
                    }
                    else
                    {
                        LogErr "Unable to connect Some/All SSH ports.."
                        $retValue = $NULL
                    }
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
        if(!$IsWindows)
        {
            GetAndCheckKernelLogs -allDeployedVMs $allVMData -status "Initial"
        }
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

Function CreateAllHyperVGroupDeployments($setupType, $xmlConfig, $Distro, $DebugRG = "", $VMGeneration = "1")
{
    $DeployedHyperVGroup = @()
    if ($DebugRG)
    {
        return "True", $DebugRG, 1, 180
    }
    else
    {
        $HyperVGroupCount = 0
        LogMsg $setupType
        $setupTypeData = $xmlConfig.config.HyperV.Deployment.$setupType
        $index = 0
        foreach ($HyperVGroupXML in $setupTypeData.ResourceGroup )
        {
            $deployOnDifferentHosts = $HyperVGroupXML.VirtualMachine.DeployOnDifferentHyperVHost
            $HyperVHostArray = @()
            if ($deployOnDifferentHosts -eq "yes") {
                foreach ($HypervHost in $xmlConfig.config.HyperV.Hosts.ChildNodes) {
                    $HyperVHostArray += $HyperVHost.ServerName
                }
            } else {
                $HyperVHostArray += $xmlConfig.config.HyperV.Hosts.ChildNodes[$index].ServerName
            }

            $SourceOsVHDPath = $xmlConfig.config.HyperV.Hosts.ChildNodes[$index].SourceOsVHDPath
            $DestinationOsVHDPath = $xmlConfig.config.HyperV.Hosts.ChildNodes[$index].DestinationOsVHDPath
            $index++
            $readyToDeploy = $false
            while (!$readyToDeploy)
            {
                #TBD Verify the readiness of the HyperV Host.
                $readyToDeploy = $true
            }
            if ($readyToDeploy)
            {
                $curtime = ([string]((Get-Date).Ticks / 1000000)).Split(".")[0]
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
                        foreach ($HyperVHost in $HyperVHostArray){
                            $isHyperVGroupDeleted = DeleteHyperVGroup -HyperVGroupName $HyperVGroupName -HyperVHost $HyperVHost
                        }
                    }
                    if ($isHyperVGroupDeleted)
                    {
                        foreach ($HyperVHost in $HyperVHostArray){
                            $CreatedHyperVGroup = CreateHyperVGroup -HyperVGroupName $HyperVGroupName -HyperVHost $HyperVHost
                        }
                        if ($CreatedHyperVGroup)
                        {
                            $DeploymentStartTime = (Get-Date)
                            $ExpectedVMs = 0
                            $HyperVGroupXML.VirtualMachine | ForEach-Object {$ExpectedVMs += 1}
                            $VMCreationStatus = CreateHyperVGroupDeployment -HyperVGroupName $HyperVGroupName -HyperVGroupXML $HyperVGroupXML `
                                -HyperVHost $HyperVHostArray -SourceOsVHDPath $SourceOsVHDPath -DestinationOsVHDPath $DestinationOsVHDPath `
                                -VMGeneration $VMGeneration
                            $DeploymentEndTime = (Get-Date)
                            $DeploymentElapsedTime = $DeploymentEndTime - $DeploymentStartTime
                            if ( $VMCreationStatus )
                            {
                                if($xmlconfig.config.testsDefinition.test.Tags `
                                    -and $xmlconfig.config.testsDefinition.test.Tags.ToString().Contains("nested"))
                                {
                                    LogMsg "Test Platform is $TestPlatform and nested VMs will be created, need to enable nested virtualization"
                                    EnableHyperVNestedVirtualization -HyperVGroupName $HyperVGroupName -HyperVHost $HyperVHost
                                }
                                foreach ($HyperVHost in $HyperVHostArray){
                                    $StartVMStatus = StartHyperVGroupVMs -HyperVGroupName $HyperVGroupName -HyperVHost $HyperVHost
                                    if ($StartVMStatus)
                                    {
                                        $retValue = "True"
                                        $isHyperVGroupDeployed = "True"
                                        $HyperVGroupCount = $HyperVGroupCount + 1
                                        $DeployedHyperVGroup += $HyperVGroupName
                                    }
                                    else 
                                    {
                                        LogErr "Unable to start one or more VM's"
                                        $retryDeployment = $retryDeployment + 1
                                        $retValue = "False"
                                        $isHyperVGroupDeployed = "False"
                                    }
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

Function DeleteHyperVGroup([string]$HyperVGroupName, [string]$HyperVHost) {
    if ($ExistingRG) {
        LogMsg "Skipping removal of Hyper-V VM group ${HyperVGroupName}"
        return $true
    }

    $vmGroup = $null
    LogMsg "Checking if Hyper-V VM group '$HyperVGroupName' exists on $HyperVHost..."
    $vmGroup = Get-VMGroup -Name $HyperVGroupName -ErrorAction SilentlyContinue `
                           -ComputerName $HyperVHost
    if (!$vmGroup) {
        LogWarn "Hyper-V VM group ${HyperVGroupName} does not exist"
        return $true
    }

    $vmGroup.VMMembers | ForEach-Object {
        LogMsg "Stop-VM -Name $($_.Name) -Force -TurnOff "
        $vm = $_
        Stop-VM -Name $vm.Name -Force -TurnOff -ComputerName $HyperVHost
        Remove-VMSnapshot -VMName $vm.Name -ComputerName $HyperVHost `
            -IncludeAllChildCheckpoints -Confirm:$false
        if (!$?) {
            LogErr ("Failed to remove snapshots for VM {0}" -f @($vm.Name))
            return $false
        }
        Wait-VMStatus -VMName $vm.Name -VMStatus "Operating Normally" -RetryInterval 2 `
            -HvServer $HyperVHost
        $vm = Get-VM -Name $vm.Name -ComputerName $HyperVHost
        $vm.HardDrives | ForEach-Object {
            $vhdPath = $_.Path
            $invokeCommandParams = @{
                "ScriptBlock" = {
                    Remove-Item -Path $args[0] -Force
                };
                "ArgumentList" = $vhdPath;
            }
            if ($HyperVHost -ne "localhost" -and $HyperVHost -ne $(hostname)) {
                $invokeCommandParams.ComputerName = $HyperVHost
            }
            Invoke-Command @invokeCommandParams
            if (!$?) {
                LogMsg "Failed to remove ${vhdPath} using Invoke-Command"
                $vhdUncPath = $vhdPath -replace '^(.):', "\\$(HyperVHost)\`$1$"
                LogMsg "Removing ${vhdUncPath} ..."
                Remove-Item -Path $vhdUncPath -Force
                if (!$? -or (Test-Path $vhdUncPath)) {
                    LogErr "Failed to remove ${vhdPath} using UNC paths"
                    return $false
                }
            }
            LogMsg "VHD ${vhdPath} removed!"
        }
        Remove-VM -Name $vm.Name -ComputerName $HyperVHost -Force
        LogMsg "Hyper-V VM $($vm.Name) removed!"
    }

    LogMsg "Hyper-V VM group ${HyperVGroupName} is being removed!"
    Remove-VMGroup -Name $HyperVGroupName -ComputerName $HyperVHost -Force
    LogMsg "Hyper-V VM group ${HyperVGroupName} removed!"
    return $true
}

Function CreateHyperVGroup([string]$HyperVGroupName, [string]$HyperVHost)
{
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

Function CreateHyperVGroupDeployment([string]$HyperVGroup, $HyperVGroupNameXML, $HyperVHost, $SourceOsVHDPath, $DestinationOsVHDPath, $VMGeneration)
{
    $HyperVMappedSizes = [xml](Get-Content .\XML\AzureVMSizeToHyperVMapping.xml)
    $OsVHD = $BaseOsVHD
    $ErrorCount = 0
    $i = 0
    $HyperVHost = $HyperVHost | Select-Object -First 1
    $CurrentHyperVGroup = Get-VMGroup -Name $HyperVGroupName -ComputerName $HyperVHost
    if ( $CurrentHyperVGroup.Count -eq 1)
    {
        foreach ( $VirtualMachine in $HyperVGroupXML.VirtualMachine)
        {
            if ($VirtualMachine.DeployOnDifferentHyperVHost -and ($TestLocation -match ",")) {
                $hostNumber = $HyperVGroupXML.VirtualMachine.indexOf($VirtualMachine)
                $HyperVHost = $xmlConfig.config.HyperV.Hosts.ChildNodes[$hostNumber].ServerName
                $SourceOsVHDPath = $xmlConfig.config.HyperV.Hosts.ChildNodes[$hostNumber].SourceOsVHDPath
                $DestinationOsVHDPath = $xmlConfig.config.HyperV.Hosts.ChildNodes[$hostNumber].DestinationOsVHDPath
            }
            $vhdSuffix = [System.IO.Path]::GetExtension($OsVHD)
            $InterfaceAliasWithInternet = (Get-NetIPConfiguration -ComputerName $HyperVHost | Where-Object {$_.NetProfile.Name -ne 'Unidentified network'}).InterfaceAlias
            $VMSwitches = Get-VMSwitch | Where-Object {$InterfaceAliasWithInternet -match $_.Name} | Select-Object -First 1
            if ( $VirtualMachine.RoleName)
            {
                if ($VirtualMachine.RoleName -match "dependency") {
                    $CurrentVMName = $HyperVGroupName + "-" + $VirtualMachine.RoleName
                } else {
                    $CurrentVMName = $VirtualMachine.RoleName
                }
                $CurrentVMOsVHDPath = "$DestinationOsVHDPath\$HyperVGroupName-$CurrentVMName-diff-OSDisk${vhdSuffix}"
            }
            else
            {
                $CurrentVMName = $HyperVGroupName + "-role-$i"
                $CurrentVMOsVHDPath = "$DestinationOsVHDPath\$HyperVGroupName-role-$i-diff-OSDisk${vhdSuffix}"
                $i += 1
            }

            $parentOsVHDPath = $OsVHD
            if ($SourceOsVHDPath) {
                $parentOsVHDPath = Join-Path $SourceOsVHDPath $OsVHD
            }
            $infoParentOsVHD = Get-VHD $parentOsVHDPath -ComputerName $HyperVHost
            $uriParentOsVHDPath = [System.Uri]$parentOsVHDPath
            if ($uriParentOsVHDPath -and $uriParentOsVHDPath.isUnc) {
                LogMsg "Parent VHD path ${parentOsVHDPath} is on an SMB share."
                if ($infoParentOsVHD.VhdType -eq "Differencing") {
                    LogErr "Unsupported differencing disk on the share."
                    $ErrorCount += 1
                    return $false
                }
                LogMsg "Checking if we have a local VHD with the same disk identifier on the host"
                $hypervVHDLocalPath = (Get-VMHost -ComputerName $HyperVHost).VirtualHardDiskPath
                $vhdName = [System.IO.Path]::GetFileNameWithoutExtension($(Split-Path -Leaf $parentOsVHDPath))
                $newVhdName = "{0}-{1}{2}" -f @($vhdName, $infoParentOsVHD.DiskIdentifier.Replace("-", ""),$vhdSuffix)
                $localVHDPath = Join-Path $hypervVHDLocalPath $newVhdName
                if ((Test-Path $localVHDPath)) {
                    LogMsg "${parentOsVHDPath} is already found at path ${localVHDPath}"
                } else {
                    LogMsg "${parentOsVHDPath} will be copied at path ${localVHDPath}"
                    Copy-Item -Force $parentOsVHDPath $localVHDPath
                }
                $parentOsVHDPath = $localVHDPath
            }

            $Out = New-VHD -ParentPath $parentOsVHDPath -Path $CurrentVMOsVHDPath -ComputerName $HyperVHost
            if ($Out) {
                LogMsg "Prerequiste: Prepare OS Disk $CurrentVMOsVHDPath - Succeeded."
                if ($OverrideVMSize)
                {
                    $CurrentVMSize = $OverrideVMSize
                }
                else
                {
                    $CurrentVMSize = $VirtualMachine.ARMInstanceSize
                }
                Set-Variable -Name HyperVInstanceSize -Value $CurrentVMSize -Scope Global
                $CurrentVMCpu = $HyperVMappedSizes.HyperV.$CurrentVMSize.NumberOfCores
                $CurrentVMMemory = $HyperVMappedSizes.HyperV.$CurrentVMSize.MemoryInMB
                $CurrentVMMemory = [int]$CurrentVMMemory * 1024 * 1024
                LogMsg "New-VM -Name $CurrentVMName -MemoryStartupBytes $CurrentVMMemory -BootDevice VHD -VHDPath $CurrentVMOsVHDPath -Generation $VMGeneration -Switch $($VMSwitches.Name) -ComputerName $HyperVHost"
                $NewVM = New-VM -Name $CurrentVMName -MemoryStartupBytes $CurrentVMMemory -BootDevice VHD `
                    -VHDPath $CurrentVMOsVHDPath -Generation $VMGeneration -Switch $($VMSwitches.Name) -ComputerName $HyperVHost
                if ([string]$VMGeneration -eq "2") {
                    LogMsg "Set-VMFirmware -VMName $CurrentVMName -EnableSecureBoot Off"
                    Set-VMFirmware -VMName $CurrentVMName -EnableSecureBoot Off
                }
                if($currentTestData.AdditionalHWConfig.SwitchName)
                {
                    Add-VMNetworkAdapter -VMName $CurrentVMName -SwitchName $currentTestData.AdditionalHWConfig.SwitchName -ComputerName $HyperVHost
                }
                if ($?)
                {
                    LogMsg "Set-VM -VM $($NewVM.Name) -ProcessorCount $CurrentVMCpu -StaticMemory -CheckpointType Disabled -Notes $HyperVGroupName"

                    $Out = Set-VM -VM $NewVM -ProcessorCount $CurrentVMCpu -StaticMemory  -CheckpointType Disabled -Notes "$HyperVGroupName"
                    LogMsg "Add-VMGroupMember -Name $HyperVGroupName -VM $($NewVM.Name)"
                    $Out = Add-VMGroupMember -Name "$HyperVGroupName" -VM $NewVM -ComputerName $HyperVHost
                    $ResourceDiskPath = ".\Temp\ResourceDisk-$((Get-Date).Ticks)-sdb${vhdSuffix}"
                    if($DestinationOsVHDPath -ne "VHDs_Destination_Path")
                    {
                        $ResourceDiskPath = "$DestinationOsVHDPath\ResourceDisk-$((Get-Date).Ticks)-sdb${vhdSuffix}"
                    }
                    LogMsg "New-VHD -Path $ResourceDiskPath -SizeBytes 1GB -Dynamic -ComputerName $HyperVHost"
                    New-VHD -Path $ResourceDiskPath -SizeBytes 1GB -Dynamic -ComputerName $HyperVHost
                    LogMsg "Add-VMHardDiskDrive -ControllerType SCSI -Path $ResourceDiskPath -VM $($NewVM.Name)"
                    Add-VMHardDiskDrive -ControllerType SCSI -Path $ResourceDiskPath -VM $NewVM
                    $LUNs = $VirtualMachine.DataDisk.LUN
                    if($LUNs.count -gt 0)
                    {
                        LogMsg "check the offline physical disks on host $HyperVHost"
                        $DiskNumbers = (Get-Disk | Where-Object {$_.OperationalStatus -eq 'offline'}).Number
                        if($DiskNumbers.count -ge $LUNs.count)
                        {
                            LogMsg "The offline physical disks are enough for use"
                            $ControllerType = 'SCSI'
                            $count = 0
                            foreach ( $LUN in $LUNs )
                            {
                                LogMsg "Add physical disk $($DiskNumbers[$count]) to $ControllerType controller on virtual machine $CurrentVMName."
                                $NewVM | Add-VMHardDiskDrive -DiskNumber $($DiskNumbers[$count]) -ControllerType $ControllerType
                                $count ++
                            }
                        }
                        else
                        {
                            LogErr "The offline physical disks are not enough for use"
                            $ErrorCount += 1
                        }
                    }
                }
                else 
                {
                    LogErr "Failed to create VM."
                    LogErr "Removing OS Disk : $CurrentVMOsVHDPath"
                    $Out = Remove-Item -Path $CurrentVMOsVHDPath -Force
                    $ErrorCount += 1
                }
            } else {
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

Function EnableHyperVNestedVirtualization($HyperVGroupName, $HyperVHost)
{
    $AllVMs = Get-VMGroup -Name $HyperVGroupName -ComputerName $HyperVHost
    $CurrentErrors = @()
    foreach ( $VM in $AllVMs.VMMembers)
    {
        LogMsg "Enable nested virtualization for $($VM.Name) from $HyperVGroupName..."
        Set-VMProcessor -VMName $($VM.Name) -ExposeVirtualizationExtensions $true -ComputerName $HyperVHost
        Set-VMNetworkAdapter -VMName $($VM.Name) -MacAddressSpoofing on -ComputerName $HyperVHost
        if ( $? )
        {
            LogMsg "Succeeded."
        }
        else
        {
            LogErr "Failed"
            $CurrentErrors += "Enable nested virtualization for $($VM.Name) from $HyperVGroupName failed."
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

Function StartHyperVGroupVMs($HyperVGroupName,$HyperVHost)
{
    $AllVMs = Get-VMGroup -Name $HyperVGroupName -ComputerName $HyperVHost
    $CurrentErrors = @()
    foreach ( $VM in $AllVMs.VMMembers)
    {
        LogMsg "Starting $($VM.Name) from $HyperVGroupName..."
        Start-VM -VM $VM
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

Function StopHyperVGroupVMs($HyperVGroupName, $HyperVHost)
{
    $AllVMs = Get-VMGroup -Name $HyperVGroupName -ComputerName $HyperVHost
    $CurrentErrors = @()
    foreach ( $VM in $AllVMs.VMMembers)
    {
        LogMsg "Shutting down $($VM.Name) from $HyperVGroupName..."
        Stop-VM -VM $VM -ComputerName $HyperVHost
        if ( $? )
        {
            LogMsg "Succeeded."
        }
        else
        {
            LogErr "Shutdown failed. Turning off.."
            Stop-VM -VM $VM  -Force -TurnOff -ComputerName $HyperVHost
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
    $allDeployedVMs = @()
    function CreateQuickVMNode()
    {
        $objNode = New-Object -TypeName PSObject
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name HyperVHost -Value $HyperVHost -Force
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name HyperVGroupName -Value $null -Force 
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name PublicIP -Value $null -Force
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name InternalIP -Value $null -Force
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name RoleName -Value $null -Force
        if($IsWindows){
            Add-Member -InputObject $objNode -MemberType NoteProperty -Name RDPPort -Value 3389 -Force
        }
        else{
            Add-Member -InputObject $objNode -MemberType NoteProperty -Name SSHPort -Value 22 -Force
        }
        return $objNode
    }
    $CurrentRetryAttempt = 0
    $ALLVMs = @{}
    $index = 0
    foreach ($HyperVGroupName in $HyperVGroupNames.Split("^"))
    {
        $HyperVHost = $xmlConfig.config.Hyperv.Hosts.ChildNodes[$index].ServerName
        $index++
        LogMsg "Collecting $HyperVGroupName data.."
        $CurrentGroupData = Get-VMGroup -Name $HyperVGroupName -ComputerName $HyperVHost
        $ALLVMs.Add($CurrentGroupData.ComputerName, $CurrentGroupData.VMMembers)
    }

    foreach ($ComputerName in $AllVMs.Keys)
    {
        foreach($property in $ALLVMs[$ComputerName]) {
            $VM = Get-VM -Name $property.Name -ComputerName $ComputerName
            $VMNicProperties =  Get-VMNetworkAdapter -ComputerName $ComputerName -VMName $property.Name

            $RetryCount = 50
            $CurrentRetryAttempt=0
            $QuickVMNode = CreateQuickVMNode
            do
            {
                $CurrentRetryAttempt++
                Start-Sleep 5
                LogMsg "    [$CurrentRetryAttempt/$RetryCount] : $($property.Name) : Waiting for IP address ..."
                $QuickVMNode.PublicIP = $VMNicProperties.IPAddresses | Where-Object {$_ -imatch "\b(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}\b"}
            }while(($CurrentRetryAttempt -lt $RetryCount) -and (!$QuickVMNode.PublicIP))

            if($QuickVMNode.PublicIP -and $QuickVMNode.PublicIP.Split("").Length -gt 1)
            {
                $QuickVMNode.PublicIP = $QuickVMNode.PublicIP[0]
            }

            $QuickVMNode.InternalIP = $QuickVMNode.PublicIP
            $QuickVMNode.HyperVHost = $ComputerName
            if ($QuickVMNode.PublicIP -notmatch "\b(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}\b")
            {
                LogMsg ("Cannot collect public IP for VM {0}" -f @($VM.Name))
            }
            else
            {
                $QuickVMNode.RoleName = $VM.Name
                $QuickVMNode.HyperVGroupName = $VM.Groups.Name
                $allDeployedVMs += $QuickVMNode
                LogMsg "Collected $($QuickVMNode.RoleName) from $($QuickVMNode.HyperVGroupName) data!"
            }
        }
    }
    return $allDeployedVMs
}

Function RestartAllHyperVDeployments($allVMData)
{
    foreach ( $VM in $allVMData )
    {
        StopHyperVGroupVMs -HyperVGroupName $VM.HyperVGroupName -HyperVHost $VM.HyperVHost
    }
    foreach ( $VM in $allVMData )
    {
        StartHyperVGroupVMs -HyperVGroupName $VM.HyperVGroupName -HyperVHost $VM.HyperVHost
    }
	$isSSHOpened = isAllSSHPortsEnabledRG -AllVMDataObject $AllVMData
	return $isSSHOpened
}

Function InjectHostnamesInHyperVVMs($allVMData)
{
    $ErrorCount = 0
    try 
    {
        foreach ( $VM in $allVMData )
        {
            LogMsg "Injecting hostname '$($VM.RoleName)' in HyperV VM..."
            if(!$IsWindows)
            {
               RunLinuxCmd -username $user -password $password -ip $VM.PublicIP -port $VM.SSHPort -command "echo $($VM.RoleName) > /etc/hostname" -runAsSudo -maxRetryCount 5
            }
            else
            {
                $cred = Get-Cred $user $password
                Invoke-Command -ComputerName $VM.PublicIP -ScriptBlock {$computerInfo=Get-ComputerInfo;if($computerInfo.CsDNSHostName -ne $args[0]){Rename-computer -computername $computerInfo.CsDNSHostName -newname $args[0] -force}} -ArgumentList $VM.RoleName -Credential $cred
            }
        }
        $RestartStatus = RestartAllHyperVDeployments -allVMData $allVMData 
    }
    catch 
    {
        $ErrorCount += 1
    }
    finally 
    {
        if ( ($ErrorCount -eq 0) -and ($RestartStatus -eq "True"))
        {
            LogMsg "Hostnames are injected successfully."
        }
        else 
        {
            LogErr "Failed to inject $ErrorCount hostnames in HyperV VMs. Continuing the tests..."
        }
    }
}

Function Get-Cred($user, $password)
{
    $secstr = New-Object -TypeName System.Security.SecureString
    $password.ToCharArray() | ForEach-Object {$secstr.AppendChar($_)}
    $cred = new-object -typename System.Management.Automation.PSCredential -argumentlist $user, $secstr
    Set-Item WSMan:\localhost\Client\TrustedHosts * -Force
    return $cred
}

function Get-VMPanicEvent {
    param(
        $VMName,
        $HvServer,
        $StartTime,
        $RetryCount=30,
        $RetryInterval=5
    )

    $currentRetryCount = 0
    $testPassed = $false
    while ($currentRetryCount -lt $RetryCount -and !$testPassed) {
        LogMsg "Checking eventlog for 18590 event sent by VM ${VMName}"
        $currentRetryCount++
        $events = @(Get-WinEvent -FilterHashTable `
            @{LogName = "Microsoft-Windows-Hyper-V-Worker-Admin";
              StartTime = $StartTime} `
            -ComputerName $hvServer -ErrorAction SilentlyContinue)
        foreach ($evt in $events) {
            if ($evt.id -eq 18590 -and $evt.message.Contains($vmName)) {
                $testPassed = $true
                break
            }
        }
        Start-Sleep $RetryInterval
    }
    return $testPassed
}

function Wait-VMState {
    param(
        $VMName,
        $VMState,
        $HvServer,
        $RetryCount=30,
        $RetryInterval=5
    )

    $currentRetryCount = 0
    while ($currentRetryCount -lt $RetryCount -and `
              (Get-VM -ComputerName $HvServer -Name $VMName).State -ne $VMState) {
        LogMsg "Waiting for VM ${VMName} to enter ${VMState} state"
        Start-Sleep -Seconds $RetryInterval
        $currentRetryCount++
    }
    if ($currentRetryCount -eq $RetryCount) {
        throw "VM ${VMName} failed to enter ${VMState} state"
    }
}

function Wait-VMStatus {
    param(
        $VMName,
        $VMStatus,
        $HvServer,
        $RetryCount=30,
        $RetryInterval=5
    )

    $currentRetryCount = 0
    while ($currentRetryCount -lt $RetryCount -and `
              (Get-VM -ComputerName $HvServer -Name $VMName).Status -ne $VMStatus) {
        LogMsg "Waiting for VM ${VMName} to enter '${VMStatus}' status"
        Start-Sleep -Seconds $RetryInterval
        $currentRetryCount++
    }
    if ($currentRetryCount -eq $RetryCount) {
        throw "VM ${VMName} failed to enter ${VMStatus} status"
    }
}

function Wait-VMHeartbeatOK {
    param(
        $VMName,
        $HvServer,
        $RetryCount=30,
        $RetryInterval=5
    )

    $currentRetryCount = 0
    do {
        $currentRetryCount++
        Start-Sleep -Seconds $RetryInterval
        LogMsg "Waiting for VM ${VMName} to enter Heartbeat OK state"
    } until ($currentRetryCount -ge $RetryCount -or `
                 (Get-VMIntegrationService -VMName $vmName -ComputerName $hvServer | `
                  Where-Object  { $_.name -eq "Heartbeat" }
              ).PrimaryStatusDescription -eq "OK")
    if ($currentRetryCount -eq $RetryCount) {
        throw "VM ${VMName} failed to enter Heartbeat OK state"
    }
}

Function Wait-ForHyperVVMShutdown($HvServer,$VMNames)
{
    LogMsg "Waiting for VM Shutting Down"
    if ($VMNames -and $HvServer)
    {
        foreach ($VMName in $VMNames.split(","))
        {
            Wait-VMState -VMName $VMName -HvServer $HvServer -VMState "Off"
        }
    }
    else
    {
        LogError "Please provide HvServer and VMNames."
        throw "Wait-ForHyperVVMShutdown Missing Mandatory Paramters"
    }
}
