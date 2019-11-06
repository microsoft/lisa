# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Description
   This script tests the VMs Heartbeat after the VM enters in PausedCritical state.
   For the VM to enter in PausedCritical state the disk where the VHD is has to be full.
   We create a new partition, copy the VHD and fill up the partition.
   After the VM enters in PausedCritical state we free some space and the VM
   should return to normal OK Heartbeat.
   This feature to recover from the PauseCritical state is a new feature implemented
   since Windows Server 2016.
#>

param([String] $TestParams,
      [object] $AllVmData)

function Main {
    param (
        $VMName,
        $HvServer,
        $VMPort,
        $VMUserName,
        $VMPassword,
        $RootDir
    )
    $ipv4vm1 = $null
    $vm_gen = $null
    $foundName = $false
    $driveletter = $null

    # Change the working directory for the log files
    if (-not (Test-Path $RootDir)) {
        Write-LogErr "Error: The directory `"${RootDir}`" does not exist"
        return "FAIL"
    }
    Set-Location $RootDir

    # Check host version and skipp TC in case of WS2012 or older
    $hostVersion = Get-HostBuildNumber $HvServer
    if ($hostVersion -le 9600) {
        Write-LogInfo "Info: Host is WS2012R2 or older. Skipping test case."
        return "ABORTED"
    }

    # check what drive letter is available and pick one randomly
    $driveletter = Get-ChildItem function:[g-y]: -n | Where-Object {!(Test-Path $_)} | Get-Random

    if ([string]::IsNullOrEmpty($driveletter)) {
        Write-LogErr "Error: The driveletter variable is empty!"
        return "FAIL"
    } else {
        Write-LogInfo "The drive letter of test volume is $driveletter"
    }

    # Shutdown gracefully so we don't corrupt the VHD
    Stop-VM -Name $VMName -ComputerName $HvServer
    if (-not $?) {
        Write-LogErr "Error: Unable to Shut Down VM"
        return "FAIL"
    }

    # Get Parent VHD
    $ParentVHD = Get-ParentVHD $VMName $HvServer
    if (-not $ParentVHD) {
        Write-LogErr "Error getting Parent VHD of VM $VMName"
        return "FAIL"
    }

    # Get VHD size
    $VHDSize = (Get-Vhd -Path $ParentVHD -ComputerName $HvServer).FileSize

    $baseVhdPath = $(Get-VMHost).VirtualHardDiskPath
    if (-not $baseVhdPath.EndsWith("\")) {
        $baseVhdPath += "\"
    }

    $newsize = ($VHDSize + 1GB)

    # Check if VHD path exists and is being used by another process
    $startDate = Get-Date
    while (-not $foundName -and $startDate.AddMinutes(2) -gt (Get-Date)) {
        $vhdName = $(-join ((48..57) + (97..122) | Get-Random -Count 10 | ForEach-Object {[char]$_}))
        $vhdpath = "${baseVhdPath}${vhdName}.vhdx"
        if (Test-Path $vhdpath) {
            try {
                [IO.File]::OpenWrite($file).close()
                Write-LogInfo "Deleting existing VHD $vhdpath"
                Remove-Item $vhdpath -Force
                $foundName = $true
            } catch {
                $foundName = $false
            }
        } else {
            $foundName = $true
        }
    }

    Get-Partition -DriveLetter $driveletter[0] -ErrorAction SilentlyContinue
    if ($?) {
        Dismount-VHD -Path $vhdpath -ComputerName $HvServer -ErrorAction SilentlyContinue
    }

    # Create the new partition
    Invoke-Command -ComputerName $hvServer -ScriptBlock { New-VHD -Path $args[0] -Dynamic -SizeBytes $args[1] | Mount-VHD -Passthru | Initialize-Disk -Passthru |
        New-Partition -DriveLetter $args[2] -UseMaximumSize | Format-Volume -FileSystem NTFS -Confirm:$false -Force } `
    -ArgumentList $vhdpath, $newsize, $driveletter[0]

    if (-not $?) {
        Write-LogErr "Error: Failed to create the new partition $driveletter"
        return "FAIL"
    }

    "hvServer=$HvServer" | Out-File './heartbeat_params.info'
    $test_vhd = [regex]::escape($vhdpath)
    "test_vhd=$test_vhd" | Out-File './heartbeat_params.info' -Append

    # Copy parent VHD to partition
    # this will be appended the .vhd or .vhdx file extension
    $defaultpath = "${driveletter}\child_disk"
    if ($ParentVHD.EndsWith("x")) {
        [string]$ChildVHD = $defaultpath + ".vhdx"
    } else {
        [string]$ChildVHD = $defaultpath + ".vhd"
    }
    Write-LogInfo $ParentVHD
    Write-LogInfo $ChildVHD
    Start-Sleep -s 15
    Invoke-command -ComputerName $hvServer { xcopy $Using:ParentVHD $Using:ChildVHD* /Y }
    if (-not $?) {
        Write-LogErr "Error: Creating Child VHD of VM $VMName"
        return "FAIL"
    }

    $child_vhd = [regex]::escape($ChildVHD)
    "child_vhd=$child_vhd" | Out-File "./heartbeat_params.info" -Append

    # Get the VM Network adapter so we can attach it to the new VM
    $VMNetAdapter = Get-VMNetworkAdapter $VMName -ComputerName $HvServer
    if (-not $?) {
        Write-LogErr "Error: Failed to run Get-VMNetworkAdapter to obtain the source VM configuration"
        return "FAIL"
    }

    # Get VM Generation
    $vm_gen = Get-VMGeneration $VMName $HvServer

    $VMName1 = "${vmName}_ChildVM"
    # Remove old VM
    if ( Get-VM $VMName1 -ComputerName $HvServer -ErrorAction SilentlyContinue ) {
        Remove-VM -Name $VMName1 -ComputerName $HvServer -Confirm:$false -Force
    }

    # Create the ChildVM
    New-VM -Name $VMName1 -ComputerName $HvServer -VHDPath $ChildVHD -MemoryStartupBytes 2048MB -SwitchName $VMNetAdapter[0].SwitchName -Generation $vm_gen
    if (-not $?) {
       Write-LogErr "Error: Creating new VM $VMName1 failed!"
       return "FAIL"
    }
    "vm_name=$VMName1" | Out-File './heartbeat_params.info' -Append

    # Disable secure boot
    if ($vm_gen -eq 2) {
        Set-VMFirmware -VMName $VMName1 -ComputerName $HvServer -EnableSecureBoot Off
        if(-not $?) {
            Write-LogErr "Error: Unable to disable secure boot!"
            return "FAIL"
        }
    }

    Write-LogInfo "Info: Child VM $VMName1 created"

    $timeout = 300
    Start-VM -Name $VMName1 -ComputerName $HvServer
    if (-not (Wait-ForVMToStartKVP $VMName1 $HvServer $timeout )) {
        Write-LogErr "Error: ${vmName1} failed to start"
        return "FAIL"
    }
    Start-VM -Name $VMName -ComputerName $HvServer
    Write-LogInfo "Info: New VM $VMName1 started"

    # Get the VM1 ip
    $ipv4vm1 = Get-IPv4ViaKVP $VMName1 $HvServer
    Start-Sleep 15

    # Get partition size
    $disk = Get-WmiObject Win32_LogicalDisk -ComputerName $HvServer -Filter "DeviceID='${driveletter}'" | Select-Object FreeSpace

    # Leave 52428800 bytes (50 MB) of free space after filling the partition
    $filesize = $disk.FreeSpace - 52428800
    $file_path_formatted = $driveletter[0] + '$\' + 'testfile'

    # Fill up the partition
    $createfile = fsutil file createnew \\$HvServer\$file_path_formatted $filesize
    if ($createfile -notlike "File *testfile* is created") {
        Write-LogErr "Error: Could not create the sample test file in the working directory! $file_path_formatted"
        return "FAIL"
    }
    Write-LogInfo "Info: Created test file on \\$HvServer\$file_path_formatted with the size $filesize"
    Write-LogInfo "Info: Writing data on the VM disk in order to hit the disk limit"

    # Get the used space reported by the VM on the root partition
    $usedSpaceVM = Run-LinuxCmd -username  $VMUserName -password $VMPassword -ip $ipv4vm1 -port $VMPort -command "df -B1 /home/${VMUserName} |  awk '{print `$3}' | tail -1" -RunAsSudo
    Write-LogInfo "Used space: $usedSpaceVM"

    # Divide by 1 to convert string to double
    $usedSpaceVM = ($usedSpaceVM/1)
    $vmFileSize = ($VHDSize - $usedSpaceVM)
    $ddFileSize = [math]::Round($vmFileSize/1MB) #The value supplied to dd command has to be in MB

    if ($ddFileSize -le 0) {
        Write-LogWarn "Warning: The difference between the created partition size and the used VM space is negative."
        # If the number is negative, convert it to possitive and if it is a one or two digit number use the filesize value
        $ddFileSize = $ddFileSize * -1
        if ($ddFileSize.length -eq 1 -or $ddFileSize.length -eq 2) {
            $ddFileSize = $filesize
        }
    }

    Write-LogInfo "Info: Filling $VMName with $ddFileSize MB of data."
    Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $ipv4vm1 -port $VMPort -command "nohup dd if=/dev/urandom of=/home/${VMUserName}/data2 bs=1M count=$ddFileSize" -RunInBackGround -RunAsSudo
    Start-Sleep 90

    $vm1 = Get-VM -Name $VMName1 -ComputerName $HvServer
    if ($vm1.State -ne "PausedCritical") {
        Write-LogErr "Error: VM $VMName1 is not in Paused-Critical after we filled the disk"
        return "FAIL"
    }
    Write-LogInfo "Info: VM $VMName1 entered in Paused-Critical state, as expected."

    # Create space on partition
    Remove-Item -Path \\$HvServer\$file_path_formatted -Force
    if (-not $?) {
        Write-LogErr "ERROR: Cannot remove the test file '${testfile1}'!"
        return "FAIL"
    }
    Write-LogInfo "Info: Test file deleted from mounted VHDx"

    # Resume VM after we created space on the partition
    Resume-VM -Name $VMName1 -ComputerName $HvServer
    if (-not $?) {
        Write-LogErr "Error: Failed to resume the vm $VMName1"
    }

    # Check Heartbeat
    Start-Sleep 5
    if ($vm1.Heartbeat -eq "OkApplicationsUnknown") {
        Write-LogInfo "Info: Heartbeat detected, status OK."
        Write-LogInfo "Info: Test Passed. Heartbeat is again reported as OK."
        return "PASS"
    } else {
        Write-LogErr "Error: Heartbeat is not in the OK state."
        return "FAIL"
    }
}

Main -VMName $AllVMData.RoleName -hvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
         -VMPort $AllVMData.SSHPort -VMUserName $user -VMPassword $password `
         -RootDir $WorkingDirectory
