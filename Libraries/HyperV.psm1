##############################################################################################
# HyperV.psm1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
    PS modules for LISAv2 test automation.
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

function Create-AllHyperVGroupDeployments($SetupTypeData, $GlobalConfig, $TestLocation, $Distro, $VMGeneration = "1", $TestCaseData, $UseExistingRG) {
    $DeployedHyperVGroup = @()

    $HyperVGroupCount = 0
    Write-LogInfo "Current test setup: $($SetupTypeData.Name)"
    $index = 0
    foreach ($HyperVGroupXML in $SetupTypeData.ResourceGroup )
    {
        $deployOnDifferentHosts = $HyperVGroupXML.VirtualMachine.DeployOnDifferentHyperVHost
        $HyperVHostArray = @()
        if ($deployOnDifferentHosts -eq "yes") {
            foreach ($HypervHost in $GlobalConfig.Global.HyperV.Hosts.ChildNodes) {
                $HyperVHostArray += $HyperVHost.ServerName
            }
        } else {
            $HyperVHostArray += $GlobalConfig.Global.HyperV.Hosts.ChildNodes[$index].ServerName
        }

        $DestinationOsVHDPath = $GlobalConfig.Global.HyperV.Hosts.ChildNodes[$index].DestinationOsVHDPath
        $index++
        $readyToDeploy = $false
        while (!$readyToDeploy)
        {
            #TBD Verify the readiness of the HyperV Host.
            $readyToDeploy = $true
        }
        if ($readyToDeploy) {
            $curtime = ([string]((Get-Date).Ticks / 1000000)).Split(".")[0]
            $isHyperVGroupDeployed = "False"
            $retryDeployment = 0
            if ($UseExistingRG) {
                $HyperVGroupName = $Distro
                $isHyperVGroupDeleted = $true
                $CreatedHyperVGroup = $true
            }
            elseif ( $HyperVGroupXML.Tag -ne $null )
            {
                $HyperVGroupName = "LISAv2-" + $HyperVGroupXML.Tag + "-" + $Distro + "-" + "$TestID-" + "$curtime"
            } else {
                $HyperVGroupName = "LISAv2-" + $SetupTypeData.Name + "-" + $Distro + "-" + "$TestID-" + "$curtime"
            }
            while (($isHyperVGroupDeployed -eq "False") -and ($retryDeployment -lt 1)) {
                if (!$UseExistingRG) {
                    Write-LogInfo "Creating HyperV Group : $HyperVGroupName."
                    Write-LogInfo "Verifying that HyperV Group name is not in use."
                    foreach ($HyperVHost in $HyperVHostArray) {
                        $isHyperVGroupDeleted = Delete-HyperVGroup -HyperVGroupName $HyperVGroupName -HyperVHost $HyperVHost -SetupTypeData $SetupTypeData
                    }
                }
                if ($isHyperVGroupDeleted) {
                    if (!$UseExistingRG) {
                        foreach ($HyperVHost in $HyperVHostArray) {
                            $CreatedHyperVGroup = Create-HyperVGroup -HyperVGroupName $HyperVGroupName -HyperVHost $HyperVHost
                        }
                    }
                    if ($CreatedHyperVGroup) {
                        $DeploymentStartTime = (Get-Date)
                        $ExpectedVMs = 0
                        $HyperVGroupXML.VirtualMachine | ForEach-Object {$ExpectedVMs += 1}
                        $VMCreationStatus = Create-HyperVGroupDeployment -HyperVGroupName $HyperVGroupName -HyperVGroupXML $HyperVGroupXML `
                            -HyperVHost $HyperVHostArray -DestinationOsVHDPath $DestinationOsVHDPath `
                            -VMGeneration $VMGeneration -GlobalConfig $GlobalConfig -SetupTypeData $SetupTypeData -CurrentTestData $TestCaseData

                        $DeploymentEndTime = (Get-Date)
                        $DeploymentElapsedTime = $DeploymentEndTime - $DeploymentStartTime
                        if ( $VMCreationStatus[-1] ) {
                            foreach ($HyperVHost in $HyperVHostArray){
                                $StartVMStatus = Start-HyperVGroupVMs -HyperVGroupName $HyperVGroupName -HyperVHost $HyperVHost
                                if ($StartVMStatus) {
                                    $retValue = "True"
                                    $isHyperVGroupDeployed = "True"
                                    $HyperVGroupCount = $HyperVGroupCount + 1
                                    $DeployedHyperVGroup += $HyperVGroupName
                                } else {
                                    Write-LogErr "Unable to start one or more VM's"
                                    $retryDeployment = $retryDeployment + 1
                                    $retValue = "False"
                                    $isHyperVGroupDeployed = "False"
                                }
                            }
                        } else {
                            Write-LogErr "Unable to Deploy one or more VM's"
                            $retryDeployment = $retryDeployment + 1
                            $retValue = "False"
                            $isHyperVGroupDeployed = "False"
                        }
                    } else {
                        Write-LogErr "Unable to create $HyperVGroupName"
                        $retryDeployment = $retryDeployment + 1
                        $retValue = "False"
                        $isHyperVGroupDeployed = "False"
                    }
                } else {
                    Write-LogErr "Unable to delete existing HyperV Group - $HyperVGroupName"
                    $retryDeployment += 1
                    $retValue = "False"
                    $isHyperVGroupDeployed = "False"
                }
            }
        } else {
            Write-LogErr "HyperV server is not ready to deploy."
            $retValue = "False"
            $isHyperVGroupDeployed = "False"
        }
    }
    return $retValue, $DeployedHyperVGroup, $HyperVGroupCount, $DeploymentElapsedTime
}

function Delete-HyperVGroup([string]$HyperVGroupName, [string]$HyperVHost, $SetupTypeData, [bool]$UseExistingRG) {
    $vmGroup = $null
    Write-LogInfo "Checking if Hyper-V VM group '$HyperVGroupName' exists on $HyperVHost..."
    $vmGroup = Get-VMGroup -Name $HyperVGroupName -ErrorAction SilentlyContinue `
                           -ComputerName $HyperVHost
    if (!$vmGroup) {
        Write-LogWarn "Hyper-V VM group ${HyperVGroupName} does not exist"
        return $true
    }

    $cleanupDone = 0
    $vmGroup.VMMembers | ForEach-Object {
        $vm = Get-VM -Name $_.Name -ComputerName $HyperVHost

        Write-LogInfo "Stop-VM -Name $($vm.Name) -Force -TurnOff"
        Stop-VM -Name $vm.Name -Force -TurnOff -ComputerName $HyperVHost
        try {
            Wait-VMState -VMName $vm.Name -VMState "Off" -RetryInterval 3 `
                -HvServer $HyperVHost
            Wait-VMStatus -VMName $vm.Name -VMStatus "Operating Normally" -RetryInterval 3 `
                -HvServer $HyperVHost
        } catch {
            return $false
        }

        # Note(v-advlad): Need to remove also the parents of the .avhdx (snapshots)
        $hardDiskPath = @()
        $vm.HardDrives | ForEach-Object {
            $hardDiskPath += $_.Path
            if ($_.Path -match ".avhdx") {
                $snapshotParent = Get-VHD $_.Path -ComputerName $HyperVHost
                if ($snapshotParent -and $snapshotParent.ParentPath) {
                    $hardDiskPath += $snapshotParent.ParentPath
                }
            }
        }

        $hardDiskPath | ForEach-Object {
            $vhdPath = $_
            $invokeCommandParams = @{
                "ScriptBlock" = {
                    if ((Test-Path $args[0])) {
                        Remove-Item -Path $args[0] -Force
                    }
                };
                "ArgumentList" = $vhdPath;
            }
            if ($HyperVHost -ne "localhost" -and $HyperVHost -ne $(hostname)) {
                $invokeCommandParams.ComputerName = $HyperVHost
            }
            Invoke-Command @invokeCommandParams
            if (!$?) {
                $vhdUncPath = $vhdPath -replace '^(.):', "\\${HyperVHost}\`$1$"
                if ((Test-Path $vhdUncPath)) {
                    Write-LogWarn "Failed to remove ${vhdPath} using Invoke-Command"
                    Write-LogInfo "Removing ${vhdUncPath} ..."
                    Remove-Item -Path $vhdUncPath -Force
                    if (!$? -or (Test-Path $vhdUncPath)) {
                        Write-LogErr "Failed to remove ${vhdPath} using UNC paths"
                        return $false
                    }
                }
            }
            Write-LogInfo "VHD ${vhdPath} removed!"
        }
        Remove-VM -Name $vm.Name -ComputerName $HyperVHost -Force
        Write-LogInfo "Hyper-V VM $($vm.Name) removed!"
        if ($SetupTypeData.ClusteredVM) {
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
                if (Get-ClusterGroup -ErrorAction SilentlyContinue) {
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

    if ($cleanupDone -eq 0 -and !$UseExistingRG) {
        Remove-VMGroup -Name $HyperVGroupName -ComputerName $HyperVHost -Force
        Write-LogInfo "Hyper-V VM group ${HyperVGroupName} removed!"
    }
    return $true
}

function Create-HyperVGroup([string]$HyperVGroupName, [string]$HyperVHost) {
    $FailCounter = 0
    $retValue = "False"
    while (($retValue -eq $false) -and ($FailCounter -lt 5)) {
        try
        {
            $FailCounter++
            Write-LogInfo "Using HyperV server : $HyperVHost"
            $CreatedHyperVGroup = New-VMGroup -Name $HyperVGroupName -ComputerName $HyperVHost -GroupType VMCollectionType
            if ($?) {
                Write-LogInfo "HyperV Group $HyperVGroupName Created with Instance ID: $($CreatedHyperVGroup.InstanceId)."
                $retValue = $CreatedHyperVGroup
            } else {
                Write-LogErr "Failed to HyperV Group $HyperVGroupName."
                $retValue = $false
                $FailCounter += 1
            }
        } catch {
            $retValue = $false
        }
    }
    return $retValue
}

function Get-ClusterVolumePath {
	param(
		$ComputerName
	)
	$invokeCommandParams = @{
		"ScriptBlock" = {
			$ClusterVolume = Get-ClusterSharedVolume -ErrorAction SilentlyContinue
			if ($ClusterVolume) {
				Write-Output $ClusterVolume.SharedVolumeInfo.FriendlyVolumeName
			}
		};
	}
	if ($ComputerName -ne "localhost" -and $ComputerName -ne $(hostname)) {
		$invokeCommandParams.ComputerName = $ComputerName
	}
	return (Invoke-Command @invokeCommandParams)
}

function Create-HyperVGroupDeployment([string]$HyperVGroupName, $HyperVGroupXML, $HyperVHost, $DestinationOsVHDPath, $VMGeneration,
    $GlobalConfig, $SetupTypeData, $CurrentTestData) {
    $HyperVMappedSizes = [xml](Get-Content .\XML\AzureVMSizeToHyperVMapping.xml)
    $OsVHD = $global:BaseOsVHD
    $ErrorCount = 0
    $i = 0
    $HyperVHost = $HyperVHost | Select-Object -First 1
    $CurrentHyperVGroup = Get-VMGroup -Name $HyperVGroupName -ComputerName $HyperVHost
    if ( $CurrentHyperVGroup.Count -eq 1) {
        foreach ( $VirtualMachine in $HyperVGroupXML.VirtualMachine) {
            if ($VirtualMachine.DeployOnDifferentHyperVHost -and ($TestLocation -match ",")) {
                $hostNumber = $HyperVGroupXML.VirtualMachine.indexOf($VirtualMachine)
                $HyperVHost = $GlobalConfig.Global.HyperV.Hosts.ChildNodes[$hostNumber].ServerName
                $DestinationOsVHDPath = $GlobalConfig.Global.HyperV.Hosts.ChildNodes[$hostNumber].DestinationOsVHDPath
            }
            if ($SetupTypeData.ClusteredVM) {
                $DestinationOsVHDPath = Get-ClusterVolumePath -ComputerName $HyperVHost
                if (!$DestinationOsVHDPath) {
                    Write-LogErr "ClusterVolume could not be found. Make sure that server ${HyperVHost} has clustering enabled."
                    $ErrorCount += 1
                    continue
                }
            }

            $vhdSuffix = [System.IO.Path]::GetExtension($OsVHD)
            $InterfaceAliasWithInternet = (Get-NetIPConfiguration -ComputerName $HyperVHost | Where-Object {$_.NetProfile.Name -ne 'Unidentified network'}).InterfaceAlias
            $VMSwitches = Get-VMSwitch -ComputerName $HyperVHost | Where-Object {$InterfaceAliasWithInternet -match $_.Name} | Select-Object -First 1
            if ( $VirtualMachine.RoleName) {
                $CurrentVMName = $HyperVGroupName + "-" + $VirtualMachine.RoleName
                $CurrentVMOsVHDPath = "$DestinationOsVHDPath\$HyperVGroupName-$CurrentVMName-diff-OSDisk${vhdSuffix}"
            } else {
                $CurrentVMName = $HyperVGroupName + "-role-$i"
                $CurrentVMOsVHDPath = "$DestinationOsVHDPath\$HyperVGroupName-role-$i-diff-OSDisk${vhdSuffix}"
                $i += 1
            }

            $parentOsVHDPath = $OsVHD
            $uriParentOsVHDPath = [System.Uri]$parentOsVHDPath
            if ($uriParentOsVHDPath -and $uriParentOsVHDPath.isUnc) {
                Write-LogInfo "Parent VHD path ${parentOsVHDPath} is on an SMB share."
                $infoParentOsVHD = Get-VHD $parentOsVHDPath
                if ($infoParentOsVHD.VhdType -eq "Differencing") {
                    Write-LogErr "Unsupported differencing disk on the share."
                    $ErrorCount += 1
                    return $false
                }
            } elseif ($uriParentOsVHDPath.Scheme -imatch "http") {
                $FileName = Split-Path $uriParentOsVHDPath -Leaf
                $DownloadFile = Join-Path "$($pwd.Path)\VHDs_Destination_Path" $FileName
                $parentOsVHDPath = $DownloadFile
                if ( -not $Global:OsVhdDownloaded ) {
                    Write-LogInfo "Parent VHD path $($uriParentOsVHDPath.AbsoluteUri) is web URL."
                    Download-File -URL $uriParentOsVHDPath.AbsoluteUri -FilePath $DownloadFile
                    Set-Variable -Name OsVhdDownloaded -Value $DownloadFile -Scope Global
                } else {
                    Write-LogInfo "$($uriParentOsVHDPath.AbsoluteUri) is already downloaded for current test session."
                }
            }
            $infoParentOsVHD = Get-VHD $parentOsVHDPath
            $vhdName = [System.IO.Path]::GetFileNameWithoutExtension($(Split-Path -Leaf $parentOsVHDPath))
            Write-LogInfo "Checking if we have a local VHD with the same disk identifier on the host"
            $hypervVHDLocalPath = (Get-VMHost -ComputerName $HyperVHost).VirtualHardDiskPath
            if ($SetupTypeData.ClusteredVM) {
                $hypervVHDLocalPath = $DestinationOsVHDPath
            }
            $newVhdName = "{0}-{1}{2}" -f @($vhdName, $infoParentOsVHD.DiskIdentifier.Replace("-", ""),$vhdSuffix)
            $localVHDPath = "{0}{1}{2}" -f @($hypervVHDLocalPath,[System.IO.Path]::DirectorySeparatorChar,$newVhdName)
            $localVHDUncPath = $localVHDPath -replace '^(.):', "\\${HyperVHost}\`$1$"
            if ((Test-Path $localVHDUncPath)) {
                Write-LogInfo "${parentOsVHDPath} is already found at path ${localVHDUncPath}"
            } else {
                Write-LogInfo "${parentOsVHDPath} will be copied at path ${localVHDUncPath}"
                Copy-Item -Path ${parentOsVHDPath} -Destination ${localVHDUncPath}
            }
            $parentOsVHDPath = $localVHDPath

            $Out = New-VHD -ParentPath $parentOsVHDPath -Path $CurrentVMOsVHDPath -ComputerName $HyperVHost
            if ($Out) {
                Write-LogInfo "Prerequiste: Prepare OS Disk $CurrentVMOsVHDPath - Succeeded."
                if ($CurrentTestData.OverrideVMSize) {
                    $CurrentVMSize = $CurrentTestData.OverrideVMSize
                } else {
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
                    Write-LogInfo "Set-VMFirmware -VMName $CurrentVMName -EnableSecureBoot Off -ComputerName $HyperVHost"
                    Set-VMFirmware -VMName $CurrentVMName -EnableSecureBoot Off -ComputerName $HyperVHost
                }
                if ($NewVM.AutomaticCheckpointsEnabled) {
                    Write-LogInfo "Set-VM -Name $CurrentVMName -AutomaticCheckpointsEnabled $false -ComputerName $HyperVHost"
                    Set-VM -Name $CurrentVMName -AutomaticCheckpointsEnabled $false -ComputerName $HyperVHost
                }
                if ($currentTestData.AdditionalHWConfig.SwitchName) {
                    Add-VMNetworkAdapter -VMName $CurrentVMName -SwitchName $currentTestData.AdditionalHWConfig.SwitchName -ComputerName $HyperVHost
                }
                if ($?) {
                    Write-LogInfo "Set-VM -VM $($NewVM.Name) -ProcessorCount $CurrentVMCpu -StaticMemory -CheckpointType Disabled -Notes $HyperVGroupName"

                    $Out = Set-VM -VM $NewVM -ProcessorCount $CurrentVMCpu -StaticMemory  -CheckpointType Disabled -Notes "$HyperVGroupName"
                    Write-LogInfo "Add-VMGroupMember -Name $HyperVGroupName -VM $($NewVM.Name)"
                    $Out = Add-VMGroupMember -Name "$HyperVGroupName" -VM $NewVM -ComputerName $HyperVHost
                    $ResourceDiskPath = Join-Path $env:TEMP "ResourceDisk-$((Get-Date).Ticks)-sdb${vhdSuffix}"
                    if ($DestinationOsVHDPath -ne "VHDs_Destination_Path") {
                        $ResourceDiskPath = "$DestinationOsVHDPath\ResourceDisk-$((Get-Date).Ticks)-sdb${vhdSuffix}"
                    }
                    Write-LogInfo "New-VHD -Path $ResourceDiskPath -SizeBytes 1GB -Dynamic -ComputerName $HyperVHost"
                    New-VHD -Path $ResourceDiskPath -SizeBytes 1GB -Dynamic -ComputerName $HyperVHost
                    Write-LogInfo "Add-VMHardDiskDrive -ControllerType SCSI -Path $ResourceDiskPath -VM $($NewVM.Name)"
                    Add-VMHardDiskDrive -ControllerType SCSI -Path $ResourceDiskPath -VM $NewVM
                } else {
                    Write-LogErr "Failed to create VM."
                    Write-LogErr "Removing OS Disk : $CurrentVMOsVHDPath"
                    $Out = Remove-Item -Path $CurrentVMOsVHDPath -Force
                    $ErrorCount += 1
                }
            } else {
                Write-LogInfo "Prerequiste: Prepare OS Disk $CurrentVMOsVHDPath - Failed."
                $ErrorCount += 1
            }
            if ($SetupTypeData.ClusteredVM) {
                Move-VMStorage -Name $CurrentVMName -DestinationStoragePath $DestinationOsVHDPath -ComputerName $HyperVHost
                $invokeCommandParams = @{
                    "ScriptBlock" = {
                        Add-ClusterVirtualMachineRole -VirtualMachine $args[0]
                    };
                    "ArgumentList" = $CurrentVMName;
                }
                if ($HyperVHost -ne "localhost" -and $HyperVHost -ne $(hostname)) {
                    $invokeCommandParams.ComputerName = $HyperVHost
                }
                Invoke-Command @invokeCommandParams
                if ($? -eq $False) {
                    Write-LogErr "High Availability VM ${CurrentVMName} could not be added to the Hyper-V cluster on ${HyperVHost}"
                    $ErrorCount += 1
                }
            }
        }
    } else {
        Write-LogErr "There are $($CurrentHyperVGroup.Count) HyperV groups. We need 1 HyperV group."
        $ErrorCount += 1
    }
    if ( $ErrorCount -eq 0 ) {
        $ReturnValue = $true
    } else {
        $ReturnValue = $false
    }
    return $ReturnValue
}

function Start-HyperVGroupVMs($HyperVGroupName,$HyperVHost) {
    $AllVMs = Get-VMGroup -Name $HyperVGroupName -ComputerName $HyperVHost
    $CurrentErrors = @()
    foreach ( $VM in $AllVMs.VMMembers)
    {
        Write-LogInfo "Starting $($VM.Name) from $HyperVGroupName..."
        # ComputerName is inherited here from line 530. Don't add it
        # because Start-VM will fail
        Start-VM -VM $VM
        if ( $? ) {
            Write-LogInfo "Succeeded."
        } else {
            Write-LogErr "Failed"
            $CurrentErrors += "Starting $($VM.Name) from $HyperVGroupName failed."
        }
    }
    if ($CurrentErrors.Count -eq 0) {
        $ReturnValue = $true
        $CurrentErrors | ForEach-Object { Write-LogErr "$_" }
    } else {
        $ReturnValue = $false
    }
    return $ReturnValue
}

function Stop-HyperVGroupVMs($HyperVGroupName, $HyperVHost) {
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
            Write-LogInfo "VM stopped successfully."
        } else {
            Write-LogErr "Shutdown failed. Turning off.."
            Stop-VM -VM $VM  -Force -TurnOff -ComputerName $HyperVHost
            if ( $? ) {
                Write-LogInfo "VM turned-off successfully."
            } else {
                Write-LogErr "Failed"
                $CurrentErrors += "Stopping $($VM.Name) from $HyperVGroupName failed."
            }
        }
    }
    if ($CurrentErrors.Count -eq 0) {
        $ReturnValue = $true
        $CurrentErrors | ForEach-Object { Write-LogErr "$_" }
    } else {
        $ReturnValue = $false
    }
    return $ReturnValue
}
function Get-AllHyperVDeployementData($HyperVGroupNames,$GlobalConfig,$RetryCount = 100) {
    $allDeployedVMs = @()
    function Create-QuickVMNode() {
        $objNode = New-Object -TypeName PSObject
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name HyperVHost -Value $HyperVHost -Force
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name HyperVGroupName -Value $null -Force
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name PublicIP -Value $null -Force
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name InternalIP -Value $null -Force
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name RoleName -Value $null -Force
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name VMGeneration -Value $null -Force
        if ($global:IsWindowsImage) {
            Add-Member -InputObject $objNode -MemberType NoteProperty -Name RDPPort -Value 3389 -Force
        } else {
            Add-Member -InputObject $objNode -MemberType NoteProperty -Name SSHPort -Value 22 -Force
        }
        return $objNode
    }
    $CurrentRetryAttempt = 0
    $ALLVMs = @{}
    $index = 0
    foreach ($HyperVGroupName in $HyperVGroupNames.Split("^")) {
        $HyperVHost = $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[$index].ServerName
        $index++
        Write-LogInfo "Collecting $HyperVGroupName data.."
        $CurrentGroupData = Get-VMGroup -Name $HyperVGroupName -ComputerName $HyperVHost
        $ALLVMs.Add($CurrentGroupData.ComputerName, $CurrentGroupData.VMMembers)
    }

    foreach ($ComputerName in $AllVMs.Keys)
    {
        foreach($property in $ALLVMs[$ComputerName]) {
            $VM = Get-VM -Name $property.Name -ComputerName $ComputerName
            # Make sure the VM is started
            if ((Check-VMState $property.Name $ComputerName) -eq "Off") {
                Start-VM -ComputerName $ComputerName -Name $property.Name
                Wait-VMState -VMName $property.Name -HvServer $ComputerName -VMState "Running"
            }
            $VMNicProperties =  Get-VMNetworkAdapter -ComputerName $ComputerName -VMName $property.Name

            $RetryCount = 50
            $CurrentRetryAttempt=0
            $QuickVMNode = Create-QuickVMNode
            do {
                $CurrentRetryAttempt++
                Start-Sleep 5
                Write-LogInfo "    [$CurrentRetryAttempt/$RetryCount] : $($property.Name) : Waiting for IP address ..."
                $QuickVMNode.PublicIP = $VMNicProperties.IPAddresses | Where-Object {$_ -imatch "\b(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}\b"}
            } while(($CurrentRetryAttempt -lt $RetryCount) -and (!$QuickVMNode.PublicIP))

            if ($QuickVMNode.PublicIP -and $QuickVMNode.PublicIP.Split("").Length -gt 1) {
                $QuickVMNode.PublicIP = $QuickVMNode.PublicIP[0]
            }

            $QuickVMNode.InternalIP = $QuickVMNode.PublicIP
            $QuickVMNode.HyperVHost = $ComputerName
            $QuickVMNode.VMGeneration = $VM.Generation
            if ($QuickVMNode.PublicIP -notmatch "\b(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}\b") {
                Write-LogInfo ("Cannot collect public IP for VM {0}" -f @($VM.Name))
            } else {
                $QuickVMNode.RoleName = $VM.Name
                $QuickVMNode.HyperVGroupName = $VM.Groups.Name
                $allDeployedVMs += $QuickVMNode
                Write-LogInfo "Collected $($QuickVMNode.RoleName) from $($QuickVMNode.HyperVGroupName) data!"
            }
        }
    }
    return $allDeployedVMs
}

Function Inject-HostnamesInHyperVVMs($allVMData)
{
    $ErrorCount = 0
    try
    {
        foreach ( $VM in $allVMData )
        {
            Write-LogInfo "Injecting hostname '$($VM.RoleName)' in HyperV VM..."
            if (!$global:IsWindowsImage) {
                Run-LinuxCmd -username $user -password $password -ip $VM.PublicIP -port $VM.SSHPort `
                    -command "echo $($VM.RoleName) > /etc/hostname ; sed -i `"/127/s/`$/ $($VM.RoleName)/`" /etc/hosts" -runAsSudo -maxRetryCount 5
            } else {
                $cred = Get-Cred $user $password
                Invoke-Command -ComputerName $VM.PublicIP -ScriptBlock {$computerInfo=Get-ComputerInfo;if($computerInfo.CsDNSHostName -ne $args[0]){Rename-computer -computername $computerInfo.CsDNSHostName -newname $args[0] -force}} -ArgumentList $VM.RoleName -Credential $cred
            }
        }
    } catch {
        $ErrorCount += 1
    }
    finally
    {
        if ( $ErrorCount -eq 0 ) {
            Write-LogInfo "Hostnames are injected successfully."
        } else {
            Write-LogErr "Failed to inject $ErrorCount hostnames in HyperV VMs. Continuing the tests..."
        }
    }
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

function Create-HyperVCheckpoint {
    <#
    .DESCRIPTION
    Creates new checkpoint for each Hyper-V VM in deployment.
    #>

    param(
        [array]   $VMData,
        [string]  $CheckpointName,
        [boolean] $ShouldTurnOffVMBeforeCheckpoint = $true,
        [boolean] $ShouldTurnOnVMAfterCheckpoint = $true,
        [string]  $CheckpointType = "Standard",
        [boolean] $TurnOff = $true
    )

    foreach ($VM in $VMData) {
        if ($ShouldTurnOffVMBeforeCheckpoint) {
            Stop-VM -Name $VM.RoleName -ComputerName $VM.HyperVHost -TurnOff:$TurnOff -Force
            if ($TurnOff) {
                Wait-VMState -VMName $VM.RoleName -HvServer $VM.HyperVHost -VMState "Off"
            }
        } else {
            Start-VM -Name $VM.RoleName -ComputerName $VM.HyperVHost
        }
        Set-VM -Name $VM.RoleName -ComputerName $VM.HyperVHost -CheckpointType $CheckpointType
        Checkpoint-VM -Name $VM.RoleName -ComputerName $VM.HyperVHost -SnapshotName $CheckpointName
        $msg = ("Checkpoint {0} created for VM {1}." `
                 -f @($CheckpointName,$VM.RoleName))
        Write-LogInfo $msg
        if ($ShouldTurnOnVMAfterCheckpoint) {
            Start-VM -Name $VM.RoleName -ComputerName $VM.HyperVHost
        } else {
            Stop-VM -Name $VM.RoleName -ComputerName $VM.HyperVHost -TurnOff -Force
        }
    }
}

function Apply-HyperVCheckpoint {
    <#
    .DESCRIPTION
    Applies an existing checkpoint to each Hyper-V VM in deployment.
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
            while ((-not $publicIP) -and ($runTime -le $Timeout)) {
                Write-LogInfo "$($VM.RoleName) : Waiting for IP address (Timeout in $($Timeout-$runTime) seconds)..."
                $vmNic = Get-VM -Name $VM.RoleName -ComputerName `
                    $VM.HyperVHost | Get-VMNetworkAdapter
                if ($vmNic.Length -gt 1) {
                   $vmNic = $vmNic[0]
                }
                $vmIP = $vmNic.IPAddresses[0]
                if ($vmIP) {
                    $vmIP = $([ipaddress]$vmIP.trim()).IPAddressToString
                    if ($global:IsWindowsImage) {
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

function Check-VMState {
    param(
        [String] $vmName,
        [String] $hvServer
    )

    $vm = Get-Vm -VMName $vmName -ComputerName $hvServer
    $vmStatus = $vm.state

    return $vmStatus
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
        Write-LogInfo "Get host build number failed"
        return 0
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

function Wait-ForHyperVVMShutdown($HvServer,$VMNames) {
    Write-LogInfo "Waiting for VM to shutdown"
    if ($VMNames -and $HvServer) {
        foreach ($VMName in $VMNames.split(",")) {
            Wait-VMState -VMName $VMName -HvServer $HvServer -VMState "Off"
        }
    } else {
        Write-LogErr "Please provide HvServer and VMNames."
        throw "Wait-ForHyperVVMShutdown Missing Mandatory Parameters"
    }
}
