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

Function Deploy-HyperVGroups ($xmlConfig, $setupType, $Distro, $getLogsIfFailed = $false, $GetDeploymentStatistics = $false, $VMGeneration = "1")
{
    try
    {
        $VerifiedGroups =  $NULL
        $retValue = $NULL
        $isAllDeployed = Create-AllHyperVGroupDeployments -setupType $setupType -xmlConfig $xmlConfig `
            -Distro $Distro -VMGeneration $VMGeneration
        $isAllConnected = "False"

        if($isAllDeployed[0] -eq "True")
        {
            $DeployedHyperVGroup = $isAllDeployed[1]
            $DeploymentElapsedTime = $isAllDeployed[3]
            $global:allVMData = Get-AllHyperVDeployementData -HyperVGroupNames $DeployedHyperVGroup
            if (!$allVMData) {
                Write-LogErr "One or more deployments failed..!"
                $retValue = $NULL
            } else {
                $isAllConnected = Check-SSHPortsEnabled -AllVMDataObject $allVMData
                if ($isAllConnected -eq "True")
                {
                    Inject-HostnamesInHyperVVMs -allVMData $allVMData | Out-Null
                    $VerifiedGroups = $DeployedHyperVGroup
                    $retValue = $VerifiedGroups
                    if ( Test-Path -Path  .\Extras\UploadDeploymentDataToDB.ps1 )
                    {
                        .\Extras\UploadDeploymentDataToDB.ps1 -allVMData $allVMData -DeploymentTime $DeploymentElapsedTime.TotalSeconds
                    }
                }
                else
                {
                    Write-LogErr "Unable to connect SSH ports.."
                    $retValue = $NULL
                }
            }
            if ($xmlConfig.config.HyperV.Deployment.($CurrentTestData.setupType).ClusteredVM) {
                foreach ($VM in $allVMData) {
                    Remove-VMGroupMember -Name $VM.HyperVGroupName -VM $(Get-VM -name $VM.RoleName -ComputerName $VM.HyperVHost)
                }
            }
        }
        else
        {
            Write-LogErr "One or More Deployments are Failed..!"
            $retValue = $NULL
        }
    }
    catch
    {
        Write-LogInfo "Exception detected. Source : Deploy-HyperVGroups()"
        $line = $_.InvocationInfo.ScriptLineNumber
        $script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
        $ErrorMessage =  $_.Exception.Message
        Write-LogErr "EXCEPTION : $ErrorMessage"
        Write-LogErr "Source : Line $line in script $script_name."
        $retValue = $NULL
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

Function Create-AllHyperVGroupDeployments($setupType, $xmlConfig, $Distro, $DebugRG = "", $VMGeneration = "1")
{
    $DeployedHyperVGroup = @()
    if ($DebugRG)
    {
        return "True", $DebugRG, 1, 180
    }
    else
    {
        $HyperVGroupCount = 0
        Write-LogInfo "Current test setup: $setupType"
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
            if ($setupTypeData.ClusteredVM) {
                $ClusterVolume = Get-ClusterSharedVolume
                $DestinationOsVHDPath = $ClusterVolume.SharedVolumeInfo.FriendlyVolumeName
            } else {
                $DestinationOsVHDPath = $xmlConfig.config.HyperV.Hosts.ChildNodes[$index].DestinationOsVHDPath
            }
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
                    $HyperVGroupName = "ICA-HG-" + $HyperVGroupXML.Tag + "-" + $Distro + "-" + "$TestID-" + "$curtime"
                }
                else
                {
                    $HyperVGroupName = "ICA-HG-" + $setupType + "-" + $Distro + "-" + "$TestID-" + "$curtime"
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
                        Write-LogInfo "Creating HyperV Group : $HyperVGroupName."
                        Write-LogInfo "Verifying that HyperV Group name is not in use."
                        foreach ($HyperVHost in $HyperVHostArray){
                            $isHyperVGroupDeleted = Delete-HyperVGroup -HyperVGroupName $HyperVGroupName -HyperVHost $HyperVHost
                        }
                    }
                    if ($isHyperVGroupDeleted)
                    {
                        foreach ($HyperVHost in $HyperVHostArray){
                            $CreatedHyperVGroup = Create-HyperVGroup -HyperVGroupName $HyperVGroupName -HyperVHost $HyperVHost
                        }
                        if ($CreatedHyperVGroup)
                        {
                            $DeploymentStartTime = (Get-Date)
                            $ExpectedVMs = 0
                            $HyperVGroupXML.VirtualMachine | ForEach-Object {$ExpectedVMs += 1}
                            $VMCreationStatus = Create-HyperVGroupDeployment -HyperVGroupName $HyperVGroupName -HyperVGroupXML $HyperVGroupXML `
                                -HyperVHost $HyperVHostArray -SourceOsVHDPath $SourceOsVHDPath -DestinationOsVHDPath $DestinationOsVHDPath `
                                -VMGeneration $VMGeneration
                            $DeploymentEndTime = (Get-Date)
                            $DeploymentElapsedTime = $DeploymentEndTime - $DeploymentStartTime
                            if ( $VMCreationStatus )
                            {
                                if($xmlconfig.config.testsDefinition.test.Tags `
                                    -and $xmlconfig.config.testsDefinition.test.Tags.ToString().Contains("nested"))
                                {
                                    Write-LogInfo "Test Platform is $TestPlatform and nested VMs will be created, need to enable nested virtualization"
                                    $null = Enable-HyperVNestedVirtualization -HyperVGroupName $HyperVGroupName -HyperVHost $HyperVHost
                                }
                                foreach ($HyperVHost in $HyperVHostArray){
                                    $StartVMStatus = Start-HyperVGroupVMs -HyperVGroupName $HyperVGroupName -HyperVHost $HyperVHost
                                    if ($StartVMStatus)
                                    {
                                        $retValue = "True"
                                        $isHyperVGroupDeployed = "True"
                                        $HyperVGroupCount = $HyperVGroupCount + 1
                                        $DeployedHyperVGroup += $HyperVGroupName
                                    }
                                    else
                                    {
                                        Write-LogErr "Unable to start one or more VM's"
                                        $retryDeployment = $retryDeployment + 1
                                        $retValue = "False"
                                        $isHyperVGroupDeployed = "False"
                                    }
                                }
                            }
                            else
                            {
                                Write-LogErr "Unable to Deploy one or more VM's"
                                $retryDeployment = $retryDeployment + 1
                                $retValue = "False"
                                $isHyperVGroupDeployed = "False"
                            }
                        }
                        else
                        {
                            Write-LogErr "Unable to create $HyperVGroupName"
                            $retryDeployment = $retryDeployment + 1
                            $retValue = "False"
                            $isHyperVGroupDeployed = "False"
                        }
                    }
                    else
                    {
                        Write-LogErr "Unable to delete existing HyperV Group - $HyperVGroupName"
                        $retryDeployment += 1
                        $retValue = "False"
                        $isHyperVGroupDeployed = "False"
                    }
                }
            }
            else
            {
                Write-LogErr "HyperV server is not ready to deploy."
                $retValue = "False"
                $isHyperVGroupDeployed = "False"
            }
        }
        return $retValue, $DeployedHyperVGroup, $HyperVGroupCount, $DeploymentElapsedTime
    }
}

Function Delete-HyperVGroup([string]$HyperVGroupName, [string]$HyperVHost) {
    if ($ExistingRG) {
        Write-LogInfo "Skipping removal of Hyper-V VM group ${HyperVGroupName}"
        return $true
    }

    $vmGroup = $null
    Write-LogInfo "Checking if Hyper-V VM group '$HyperVGroupName' exists on $HyperVHost..."
    $vmGroup = Get-VMGroup -Name $HyperVGroupName -ErrorAction SilentlyContinue `
                           -ComputerName $HyperVHost
    if (!$vmGroup) {
        Write-LogWarn "Hyper-V VM group ${HyperVGroupName} does not exist"
        return $true
    }

    $vmGroup.VMMembers | ForEach-Object {
        Write-LogInfo "Stop-VM -Name $($_.Name) -Force -TurnOff "
        $vm = $_
        Stop-VM -Name $vm.Name -Force -TurnOff -ComputerName $HyperVHost
        Remove-VMSnapshot -VMName $vm.Name -ComputerName $HyperVHost `
            -IncludeAllChildCheckpoints -Confirm:$false
        if (!$?) {
            Write-LogErr ("Failed to remove snapshots for VM {0}" -f @($vm.Name))
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
                Write-LogInfo "Failed to remove ${vhdPath} using Invoke-Command"
                $vhdUncPath = $vhdPath -replace '^(.):', "\\$(HyperVHost)\`$1$"
                Write-LogInfo "Removing ${vhdUncPath} ..."
                Remove-Item -Path $vhdUncPath -Force
                if (!$? -or (Test-Path $vhdUncPath)) {
                    Write-LogErr "Failed to remove ${vhdPath} using UNC paths"
                    return $false
                }
            }
            Write-LogInfo "VHD ${vhdPath} removed!"
        }
        Remove-VM -Name $vm.Name -ComputerName $HyperVHost -Force
        Write-LogInfo "Hyper-V VM $($vm.Name) removed!"
        if ($xmlConfig.config.HyperV.Deployment.($CurrentTestData.setupType).ClusteredVM) {
            Write-LogInfo "Deleting VM on Cluster"
            Get-Command "Get-ClusterResource" -ErrorAction SilentlyContinue
            if ($?) {
                $group = Get-ClusterGroup -ErrorAction SilentlyContinue
                $MatchedVM = $group -match $vm.Name
                foreach ($vm in $MatchedVM) {
                    Remove-ClusterGroup -Name $vm.name -RemoveResources -Force
                    if (-not $?) {
                        Write-LogErr "Failed to remove Cluster Role for VM $vm"
                        return $False
                    }
                    Write-LogInfo "Cleanup was successful for $vm on Cluster"
                }
                # Also remove VM from other node if it's located there
                if (Get-ClusterGroup -ErrorAction SilentlyContinue){
                    $currentNode = (Get-Clusternode -Name $env:computername).Name.ToLower()
                    $clusterNodes = Get-ClusterNode
                    foreach ( $Node in $clusterNodes) {
	                    if ($currentNode -ne $Node.Name.ToLower()) {
		                    $destinationNode = $Node.Name.ToLower()
		                    if (Get-VM -Name $vm.Name -ComputerName $destinationNode -ErrorAction SilentlyContinue) {
			                    Remove-VM $vm.Name -ComputerName $destinationNode -Force
				    }
	                    }
                    }
                }
            }
        }
    }

    Write-LogInfo "Hyper-V VM group ${HyperVGroupName} is being removed!"
    Remove-VMGroup -Name $HyperVGroupName -ComputerName $HyperVHost -Force
    Write-LogInfo "Hyper-V VM group ${HyperVGroupName} removed!"
    return $true
}

Function Create-HyperVGroup([string]$HyperVGroupName, [string]$HyperVHost)
{
    $FailCounter = 0
    $retValue = "False"
    While(($retValue -eq $false) -and ($FailCounter -lt 5))
    {
        try
        {
            $FailCounter++
            Write-LogInfo "Using HyperV server : $HyperVHost"
            $CreatedHyperVGroup = New-VMGroup -Name $HyperVGroupName -ComputerName $HyperVHost -GroupType VMCollectionType
            if ($?)
            {
                Write-LogInfo "HyperV Group $HyperVGroupName Created with Instance ID: $($CreatedHyperVGroup.InstanceId)."
                $retValue = $CreatedHyperVGroup
            }
            else
            {
                Write-LogErr "Failed to HyperV Group $HyperVGroupName."
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

Function Create-HyperVGroupDeployment([string]$HyperVGroup, $HyperVGroupNameXML, $HyperVHost, $SourceOsVHDPath, $DestinationOsVHDPath, $VMGeneration)
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
                if ($xmlConfig.config.HyperV.Deployment.($CurrentTestData.setupType).ClusteredVM) {
                    $ClusterVolume = Get-ClusterSharedVolume
                    $DestinationOsVHDPath = $ClusterVolume.SharedVolumeInfo.FriendlyVolumeName
                } else {
                    $DestinationOsVHDPath = $xmlConfig.config.HyperV.Hosts.ChildNodes[$hostNumber].DestinationOsVHDPath
                }
            }
            $vhdSuffix = [System.IO.Path]::GetExtension($OsVHD)
            $InterfaceAliasWithInternet = (Get-NetIPConfiguration -ComputerName $HyperVHost | Where-Object {$_.NetProfile.Name -ne 'Unidentified network'}).InterfaceAlias
            $VMSwitches = Get-VMSwitch -ComputerName $HyperVHost | Where-Object {$InterfaceAliasWithInternet -match $_.Name} | Select-Object -First 1
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
                Write-LogInfo "Parent VHD path ${parentOsVHDPath} is on an SMB share."
                if ($infoParentOsVHD.VhdType -eq "Differencing") {
                    Write-LogErr "Unsupported differencing disk on the share."
                    $ErrorCount += 1
                    return $false
                }
                Write-LogInfo "Checking if we have a local VHD with the same disk identifier on the host"
                $hypervVHDLocalPath = (Get-VMHost -ComputerName $HyperVHost).VirtualHardDiskPath
                $vhdName = [System.IO.Path]::GetFileNameWithoutExtension($(Split-Path -Leaf $parentOsVHDPath))
                $newVhdName = "{0}-{1}{2}" -f @($vhdName, $infoParentOsVHD.DiskIdentifier.Replace("-", ""),$vhdSuffix)
                $localVHDPath = Join-Path $hypervVHDLocalPath $newVhdName
                if ((Test-Path $localVHDPath)) {
                    Write-LogInfo "${parentOsVHDPath} is already found at path ${localVHDPath}"
                } else {
                    Write-LogInfo "${parentOsVHDPath} will be copied at path ${localVHDPath}"
                    Copy-Item -Force $parentOsVHDPath $localVHDPath
                }
                $parentOsVHDPath = $localVHDPath
            }

            $Out = New-VHD -ParentPath $parentOsVHDPath -Path $CurrentVMOsVHDPath -ComputerName $HyperVHost
            if ($Out) {
                Write-LogInfo "Prerequiste: Prepare OS Disk $CurrentVMOsVHDPath - Succeeded."
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
                Write-LogInfo "New-VM -Name $CurrentVMName -MemoryStartupBytes $CurrentVMMemory -BootDevice VHD -VHDPath $CurrentVMOsVHDPath -Generation $VMGeneration -Switch $($VMSwitches.Name) -ComputerName $HyperVHost"
                $NewVM = New-VM -Name $CurrentVMName -MemoryStartupBytes $CurrentVMMemory -BootDevice VHD `
                    -VHDPath $CurrentVMOsVHDPath -Generation $VMGeneration -Switch $($VMSwitches.Name) -ComputerName $HyperVHost
                if ([string]$VMGeneration -eq "2") {
                    Write-LogInfo "Set-VMFirmware -VMName $CurrentVMName -EnableSecureBoot Off"
                    Set-VMFirmware -VMName $CurrentVMName -EnableSecureBoot Off
                }
                if($currentTestData.AdditionalHWConfig.SwitchName)
                {
                    Add-VMNetworkAdapter -VMName $CurrentVMName -SwitchName $currentTestData.AdditionalHWConfig.SwitchName -ComputerName $HyperVHost
                }
                if ($?)
                {
                    Write-LogInfo "Set-VM -VM $($NewVM.Name) -ProcessorCount $CurrentVMCpu -StaticMemory -CheckpointType Disabled -Notes $HyperVGroupName"

                    $Out = Set-VM -VM $NewVM -ProcessorCount $CurrentVMCpu -StaticMemory  -CheckpointType Disabled -Notes "$HyperVGroupName"
                    Write-LogInfo "Add-VMGroupMember -Name $HyperVGroupName -VM $($NewVM.Name)"
                    $Out = Add-VMGroupMember -Name "$HyperVGroupName" -VM $NewVM -ComputerName $HyperVHost
                    $ResourceDiskPath = Join-Path $env:TEMP "ResourceDisk-$((Get-Date).Ticks)-sdb${vhdSuffix}"
                    if($DestinationOsVHDPath -ne "VHDs_Destination_Path")
                    {
                        $ResourceDiskPath = "$DestinationOsVHDPath\ResourceDisk-$((Get-Date).Ticks)-sdb${vhdSuffix}"
                    }
                    Write-LogInfo "New-VHD -Path $ResourceDiskPath -SizeBytes 1GB -Dynamic -ComputerName $HyperVHost"
                    New-VHD -Path $ResourceDiskPath -SizeBytes 1GB -Dynamic -ComputerName $HyperVHost
                    Write-LogInfo "Add-VMHardDiskDrive -ControllerType SCSI -Path $ResourceDiskPath -VM $($NewVM.Name)"
                    Add-VMHardDiskDrive -ControllerType SCSI -Path $ResourceDiskPath -VM $NewVM
                    $LUNs = $VirtualMachine.DataDisk.LUN
                    if($LUNs.count -gt 0)
                    {
                        Write-LogInfo "check the offline physical disks on host $HyperVHost"
                        $DiskNumbers = (Get-Disk | Where-Object {$_.OperationalStatus -eq 'offline'}).Number
                        if($DiskNumbers.count -ge $LUNs.count)
                        {
                            Write-LogInfo "The offline physical disks are enough for use"
                            $ControllerType = 'SCSI'
                            $count = 0
                            foreach ( $LUN in $LUNs )
                            {
                                Write-LogInfo "Add physical disk $($DiskNumbers[$count]) to $ControllerType controller on virtual machine $CurrentVMName."
                                $NewVM | Add-VMHardDiskDrive -DiskNumber $($DiskNumbers[$count]) -ControllerType $ControllerType
                                $count ++
                            }
                        }
                        else
                        {
                            Write-LogErr "The offline physical disks are not enough for use"
                            $ErrorCount += 1
                        }
                    }
                }
                else
                {
                    Write-LogErr "Failed to create VM."
                    Write-LogErr "Removing OS Disk : $CurrentVMOsVHDPath"
                    $Out = Remove-Item -Path $CurrentVMOsVHDPath -Force
                    $ErrorCount += 1
                }
            } else {
                Write-LogInfo "Prerequiste: Prepare OS Disk $CurrentVMOsVHDPath - Failed."
                $ErrorCount += 1
            }
            if ($xmlConfig.config.HyperV.Deployment.($CurrentTestData.setupType).ClusteredVM) {
                Move-VMStorage $CurrentVMName -DestinationStoragePath $DestinationOsVHDPath
                Add-ClusterVirtualMachineRole -VirtualMachine $CurrentVMName
                if ($? -eq $False) {
                    LogErr "High Availability configure for VM ${CurrentVMName} could not be added to the Hyper-V cluster"
                    $ErrorCount += 1
                }
            }
        }
    }
    else
    {
        Write-LogErr "There are $($CurrentHyperVGroup.Count) HyperV groups. We need 1 HyperV group."
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

Function Enable-HyperVNestedVirtualization($HyperVGroupName, $HyperVHost)
{
    $AllVMs = Get-VMGroup -Name $HyperVGroupName -ComputerName $HyperVHost
    $CurrentErrors = @()
    foreach ( $VM in $AllVMs.VMMembers)
    {
        Write-LogInfo "Enable nested virtualization for $($VM.Name) from $HyperVGroupName..."
        Set-VMProcessor -VMName $($VM.Name) -ExposeVirtualizationExtensions $true -ComputerName $HyperVHost
        Set-VMNetworkAdapter -VMName $($VM.Name) -MacAddressSpoofing on -ComputerName $HyperVHost
        if ( $? )
        {
            Write-LogInfo "Succeeded."
        }
        else
        {
            Write-LogErr "Failed"
            $CurrentErrors += "Enable nested virtualization for $($VM.Name) from $HyperVGroupName failed."
        }
    }
    if($CurrentErrors.Count -eq 0)
    {
        $ReturnValue = $true
        $CurrentErrors | ForEach-Object { Write-LogErr "$_" }
    }
    else
    {
        $ReturnValue = $false
    }
    return $ReturnValue
}

Function Start-HyperVGroupVMs($HyperVGroupName,$HyperVHost)
{
    $AllVMs = Get-VMGroup -Name $HyperVGroupName -ComputerName $HyperVHost
    $CurrentErrors = @()
    foreach ( $VM in $AllVMs.VMMembers)
    {
        Write-LogInfo "Starting $($VM.Name) from $HyperVGroupName..."
        # ComputerName is inherited here from line 530. Don't add it
        # because Start-VM will fail
        Start-VM -VM $VM
        if ( $? )
        {
            Write-LogInfo "Succeeded."
        }
        else
        {
            Write-LogErr "Failed"
            $CurrentErrors += "Starting $($VM.Name) from $HyperVGroupName failed."
        }
    }
    if($CurrentErrors.Count -eq 0)
    {
        $ReturnValue = $true
        $CurrentErrors | ForEach-Object { Write-LogErr "$_" }
    }
    else
    {
        $ReturnValue = $false
    }
    return $ReturnValue
}

Function Stop-HyperVGroupVMs($HyperVGroupName, $HyperVHost)
{
    $AllVMs = Get-VMGroup -Name $HyperVGroupName -ComputerName $HyperVHost
    $CurrentErrors = @()
    foreach ( $VM in $AllVMs.VMMembers)
    {
        Write-LogInfo "Shutting down $($VM.Name) from $HyperVGroupName..."
        # ComputerName is inherited here from line 562. Don't add it
        # because Stop-VM will fail
        Stop-VM -VM $VM
        if ( $? )
        {
            Write-LogInfo "Succeeded."
        }
        else
        {
            Write-LogErr "Shutdown failed. Turning off.."
            Stop-VM -VM $VM  -Force -TurnOff -ComputerName $HyperVHost
            if ( $? )
            {
                Write-LogInfo "Succeeded."
            }
            else
            {
                Write-LogErr "Failed"
                $CurrentErrors += "Stopping $($VM.Name) from $HyperVGroupName failed."
            }
        }
    }
    if($CurrentErrors.Count -eq 0)
    {
        $ReturnValue = $true
        $CurrentErrors | ForEach-Object { Write-LogErr "$_" }
    }
    else
    {
        $ReturnValue = $false
    }
    return $ReturnValue
}
Function Get-AllHyperVDeployementData($HyperVGroupNames,$RetryCount = 100)
{
    $allDeployedVMs = @()
    function Create-QuickVMNode()
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
        Write-LogInfo "Collecting $HyperVGroupName data.."
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
            $QuickVMNode = Create-QuickVMNode
            do
            {
                $CurrentRetryAttempt++
                Start-Sleep 5
                Write-LogInfo "    [$CurrentRetryAttempt/$RetryCount] : $($property.Name) : Waiting for IP address ..."
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
                Write-LogInfo ("Cannot collect public IP for VM {0}" -f @($VM.Name))
            }
            else
            {
                $QuickVMNode.RoleName = $VM.Name
                $QuickVMNode.HyperVGroupName = $VM.Groups.Name
                $allDeployedVMs += $QuickVMNode
                Write-LogInfo "Collected $($QuickVMNode.RoleName) from $($QuickVMNode.HyperVGroupName) data!"
            }
        }
    }
    return $allDeployedVMs
}

Function Restart-AllHyperVDeployments($allVMData)
{
    foreach ( $VM in $allVMData )
    {
        Stop-HyperVGroupVMs -HyperVGroupName $VM.HyperVGroupName -HyperVHost $VM.HyperVHost
    }
    foreach ( $VM in $allVMData )
    {
        Start-HyperVGroupVMs -HyperVGroupName $VM.HyperVGroupName -HyperVHost $VM.HyperVHost
    }
	$isSSHOpened = Check-SSHPortsEnabled -AllVMDataObject $AllVMData
	return $isSSHOpened
}

Function Inject-HostnamesInHyperVVMs($allVMData)
{
    $ErrorCount = 0
    try
    {
        foreach ( $VM in $allVMData )
        {
            Write-LogInfo "Injecting hostname '$($VM.RoleName)' in HyperV VM..."
            if(!$IsWindows)
            {
               Run-LinuxCmd -username $user -password $password -ip $VM.PublicIP -port $VM.SSHPort -command "echo $($VM.RoleName) > /etc/hostname" -runAsSudo -maxRetryCount 5
            }
            else
            {
                $cred = Get-Cred $user $password
                Invoke-Command -ComputerName $VM.PublicIP -ScriptBlock {$computerInfo=Get-ComputerInfo;if($computerInfo.CsDNSHostName -ne $args[0]){Rename-computer -computername $computerInfo.CsDNSHostName -newname $args[0] -force}} -ArgumentList $VM.RoleName -Credential $cred
            }
        }
        $RestartStatus = Restart-AllHyperVDeployments -allVMData $allVMData
    }
    catch
    {
        $ErrorCount += 1
    }
    finally
    {
        if ( ($ErrorCount -eq 0) -and ($RestartStatus -eq "True"))
        {
            Write-LogInfo "Hostnames are injected successfully."
        }
        else
        {
            Write-LogErr "Failed to inject $ErrorCount hostnames in HyperV VMs. Continuing the tests..."
        }
    }
}

Function Get-Cred($user, $password)
{
    $secstr = New-Object -TypeName System.Security.SecureString
    $password.ToCharArray() | ForEach-Object {$secstr.AppendChar($_)}
    $cred = New-Object -typename System.Management.Automation.PSCredential -argumentlist $user, $secstr
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
        Write-LogInfo "Checking eventlog for 18590 event sent by VM ${VMName}"
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
        Write-LogInfo "Waiting for VM ${VMName} to enter ${VMState} state"
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
        Write-LogInfo "Waiting for VM ${VMName} to enter '${VMStatus}' status"
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
        Write-LogInfo "Waiting for VM ${VMName} to enter Heartbeat OK state"
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
    Write-LogInfo "Waiting for VM Shutting Down"
    if ($VMNames -and $HvServer)
    {
        foreach ($VMName in $VMNames.split(","))
        {
            Wait-VMState -VMName $VMName -HvServer $HvServer -VMState "Off"
        }
    }
    else
    {
        Write-LogErr "Please provide HvServer and VMNames."
        throw "Wait-ForHyperVVMShutdown Missing Mandatory Paramters"
    }
}

Function Set-VMDynamicMemory
{
    param (
        $VM,
        $MinMem,
        $MaxMem,
        $StartupMem,
        $MemWeight
    )
    $MinMem = Convert-ToMemSize $MinMem $VM.HyperVHost
    $MaxMem = Convert-ToMemSize $MaxMem $VM.HyperVHost
    $StartupMem = Convert-ToMemSize $StartupMem $VM.HyperVHost
    Stop-VM -Name $VM.RoleName -ComputerName $VM.HyperVHost -force
    Set-VMMemory -vmName $VM.RoleName -ComputerName $VM.HyperVHost -DynamicMemoryEnabled $true `
        -MinimumBytes $MinMem -MaximumBytes $MaxMem -StartupBytes $StartupMem -Priority $MemWeight
    # check if mem is set correctly
    $vmMem = (Get-VMMemory -vmName $VM.RoleName -ComputerName $VM.HyperVHost).Startup
    if( $vmMem -eq $StartupMem ) {
        Write-LogInfo "Set VM Startup Memory for $($VM.RoleName) to $StartupMem"
        return $True
    }
    else {
        Write-LogErr "Unable to set VM Startup Memory for $($VM.RoleName) to $StartupMem"
        return $False
    }

}

Function Get-VMDemandMemory {
    param (
        [String] $VMName,
        [String] $Server,
        [int] $Timeout
    )
    $waitTimeOut = $Timeout
    while($waitTimeOut -gt 0) {
        $vm = Get-VM -Name $VMName -ComputerName $Server
        if (-not $vm) {
            Write-LogErr "Get-VMDemandMemory: Unable to find VM ${VMName}"
            return $false
        }
        if ($vm.MemoryDemand -and $vm.MemoryDemand -gt 0) {
            return $True
        }
        $waitTimeOut -= 5  # Note - Test Port will sleep for 5 seconds
        Start-Sleep -s 5
    }
    Write-LogErr "Get-VMDemandMemory: VM ${VMName} did not get demand within timeout period ($Timeout)"
    return $False
}

function Create-HyperVCheckpoint {
    <#
    .DESCRIPTION
    Creates new checkpoint for each VM in deployment.
    Supports Hyper-V only.
    #>

    param(
        $VMData,
        [string]$CheckpointName
    )

    foreach ($VM in $VMData) {
        Stop-VM -Name $VM.RoleName -ComputerName $VM.HyperVHost -TurnOff -Force
        Set-VM -Name $VM.RoleName -ComputerName $VM.HyperVHost -CheckpointType Standard
        Checkpoint-VM -Name $VM.RoleName -ComputerName $VM.HyperVHost -SnapshotName $CheckpointName
        $msg = ("Checkpoint:{0} created for VM:{1}" `
                 -f @($CheckpointName,$VM.RoleName))
        Write-LogInfo $msg
        Start-VM -Name $VM.RoleName -ComputerName $VM.HyperVHost
    }
}

function Apply-HyperVCheckpoint {
    <#
    .DESCRIPTION
    Applies existing checkpoint to each VM in deployment.
    Supports Hyper-V only.
    #>

    param(
        $VMData,
        [string]$CheckpointName
    )

    foreach ($VM in $VMData) {
        Stop-VM -Name $VM.RoleName -ComputerName $VM.HyperVHost -TurnOff -Force
        Restore-VMSnapshot -Name $CheckpointName -VMName $VM.RoleName -ComputerName $VM.HyperVHost -Confirm:$false
        $msg = ("VM:{0} restored to checkpoint: {1}" `
                 -f ($VM.RoleName,$CheckpointName))
        Write-LogInfo $msg
        Start-VM -Name $VM.RoleName -ComputerName $VM.HyperVHost
    }
}

function Check-IP {
    <#
    .DESCRIPTION
    Checks if the IP exists (and SSH port is open) for each VM in deployment.
    Return a structure (similar to AllVMData) with updated information.
    Supports Hyper-V only.
    #>

    param(
        $VMData,
        [string]$SSHPort,
        [int]$Timeout = 300
    )

    $newVMData = @()
    $runTime = 0

    while ($runTime -le $Timeout) {
        foreach ($VM in $VMData) {
            if ($VM.RoleName -match "dependency") {
                Set-Variable -Name DependencyVmName -Value $VM.RoleName -Scope Global
                Set-Variable -Name DependencyVmHost -Value $VM.HyperVHost -Scope Global
                continue
            }
            $publicIP = ""
            while (-not $publicIP) {
                Write-LogInfo "$($VM.RoleName) : Waiting for IP address..."
                $vmNic = Get-VM -Name $VM.RoleName -ComputerName `
                    $VM.HyperVHost | Get-VMNetworkAdapter
                if ($vmNic.Length -gt 1){
                   $vmNic = $vmNic[0]
                }
                $vmIP = $vmNic.IPAddresses[0]
                if ($vmIP) {
                    $vmIP = $([ipaddress]$vmIP.trim()).IPAddressToString
                    if($IsWindows){
                        $port = $($VM.RDPPort)
                    } else {
                        $port = $($VM.SSHPort)
                    }
                    $sshConnected = Test-TCP -testIP $($vmIP) -testport $port
                    if ($sshConnected -eq "True") {
                        $publicIP = $vmIP
                    }
                }
                if (-not $publicIP) {
                    Start-Sleep 5
                    $runTime += 5
                }
            }
            $VM.PublicIP = $publicIP
            $newVMData += $VM
        }
        break
    }

    if ($runTime -gt $Timeout) {
        Write-LogInfo "Cannot find IP for one or more VMs"
        throw "Cannot find IP for one or more VMs"
    } else {
        return $newVMData
    }
}

Function Get-GuestInterfaceByVSwitch {
    param (
        [String] $VSwitchName,
        [String] $VMName,
        [String] $HvServer,
        [String] $GuestUser,
        [String] $GuestIP,
        [String] $GuestPassword,
        [String] $GuestPort
    )

    $testNic = $(Get-VM -Name $VMName -ComputerName $HvServer).NetworkAdapters `
                | Where-Object { $_.SwitchName -imatch $VSwitchName }
    $testMac = $testNic.MacAddress
    # The above $testMac doesn't have any separators - e.g. AABBCCDDEEFF
    for ($i=2; $i -lt 16; $i=$i+3) {
        $testMac = $testMac.Insert($i,':')
    }
    # We added ':' separators and now the MAC is in this format: AA:BB:CC:DD:EE:FF
    # Get the interface name that corresponds to the MAC address
    $cmdToSend = "testInterface=`$(grep -il ${testMac} /sys/class/net/*/address) ; basename `"`$(dirname `$testInterface)`""
    $testInterfaceName = Run-LinuxCmd -username $GuestUser -password $GuestPassword -ip $GuestIP -port $GuestPort `
        -command $cmdToSend -runAsSudo
    if (-not $testInterfaceName) {
        Write-LogErr "Failed to get the interface name that has $testMac MAC address"
        return $False
    }

    Write-LogInfo "The interface that will be configured on $VMName is $testInterfaceName"
    return $testInterfaceName
}