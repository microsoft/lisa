# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Description
        This is a script that performs a cleanup on LISAv2 Hyper-V VMs:
    -If the VMs are more than 1 day old, they will be stopped.
    -If the VMs are more than 2 days old, the VM/VHD files
    will be removed.
    -If empty VM groups are detected on the Hyper-V host, they will be
    deleted
#>
param(
    [String] $HvServer
)

function Main
{
    param (
        $HvServer
    )

    $vmNamePrefixes = @("LISAv2-*","ICA-HG-*")
    $stoppedVMsCount = 0
    $deletedVMsCount = 0
    $deletedVMGroupsCount = 0

    Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } `
        | ForEach-Object { Import-Module $_.FullName -Force -Global -DisableNameChecking }

    foreach ($prefix in $vmNamePrefixes) {
        $vm = Get-VM -VMName $prefix -ComputerName $HvServer
        if ($vm -ne $null){
            $vmList += $vm
        }
    }

    foreach ($vm in $vmList) {
        $vmState = $(Get-VM -Name $vm.VMName -ComputerName $HvServer).State
        if (($vmState -notlike "Running") -and ($vmState -notlike "Off")) {
            continue
        }
        # Check the running VM(s) creation time: if it is greater than 48 hours, stop it
        $dateComparison = (Get-Date).AddDays(-1)
        if (($vm.CreationTime -lt $dateComparison) -and (Get-VM -Name $vm.VMName `
            -ComputerName $HvServer | Where-Object { $_.State -like "Running" })) {
            $stoppedVMsCount++
            $msg = "$($vm.VMName) was created more than 1 day ago" `
                + " and it will be shut down`n"
            Write-Host $msg
            if (Stop-VM -VMName $vm.VMName -ComputerName $HvServer -Force -TurnOff) {
                Write-Host "Successfully turned off $($vm.VMName)"
            }
        }

        # Check the creation time of each Hyper-V VM.
        # Remove VM and VHD files if it is older than 2 days
        $dateComparison = (Get-Date).AddDays(-2)
        if ($vm.CreationTime -lt $dateComparison) {
            $deletedVMsCount++
            $msg = "$($vm.VMName) has been created on $($vm.CreationTime). " `
                + "It is older than 2 days and it will be removed`n"
            Write-Host $msg

            # Stop VM in case it is running
            if (Get-VM -Name $vm.VMName -ComputerName $HvServer | Where-Object { $_.State -like "Running" }) {
                if (Stop-VM -VMName $vm.VMName -ComputerName $HvServer -Force -TurnOff) {
                    Write-Host "Successfully turned off $($vm.VMName)"
                }
            }

            # Remove snapshots first
            Remove-VMSnapshot -VMName $vm.VMName -ComputerName $HvServer -IncludeAllChildSnapshots `
                -EA SilentlyContinue -Confirm:$false
            Wait-VMStatus -VMName $vm.VMName -VMStatus "Operating Normally" -HvServer $HvServer `
                -RetryInterval 10 -RetryCount 60

            # Remove Hard Drives
            $vm.HardDrives | ForEach-Object {
                $vhdPath = $_.Path
                $invokeCommandParams = @{
                    "ScriptBlock" = {
                        Remove-Item -Path $args[0] -Force -EA SilentlyContinue
                    };
                    "ArgumentList" = $vhdPath;
                }
                $invokeCommandParams.ComputerName = $HvServer
                Invoke-Command @invokeCommandParams
                if (!$?) {
                    Write-Host "Failed to remove ${vhdPath} using Invoke-Command"
                    $vhdUncPath = $vhdPath -replace '^(.):', "\\${HvServer}\`$1$"
                    Remove-Item -Path $vhdUncPath -Force -EA SilentlyContinue
                    if (!$? -or (Test-Path $vhdUncPath)) {
                        Write-Host "Failed to remove ${vhdPath} using UNC paths"
                    }
                }
                Write-Host "VHD ${vhdPath} removed!"
            }

            # Remove VM
            if (Remove-VM -Name $vm.VMName -ComputerName $HvServer -Force) {
                Write-Host "Successfully removed $($vm.VMName)"
            }
        }
    }

    # Search for empty Hyper-V VM groups and delete them
    $vmGroups = Get-VMGroup -ComputerName $HvServer
    foreach ($vmGroup in $vmGroups) {
        if ([bool]$vmGroup.VMMembers -eq $False) {
            Remove-VMGroup -Name $vmGroup.Name -ComputerName $HvServer -Force -EA SilentlyContinue
            if ($?) {
                $deletedVMGroupsCount++
                Write-Host "Deleted $($vmGroup.Name) empty VM Group on $HvServer"
            }
        }
    }

    Write-Host "`nCleanup status for $HvServer"
    $msg = "VMs stopped: ${stoppedVMsCount}`nVMs deleted: ${deletedVMsCount}" `
                + "`nEmpty VM Groups deleted: ${deletedVMGroupsCount}"
    Write-Host $msg
    return 0
}

Main -HvServer $HvServer
exit 0
