# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
 This script tests the file copy functionality after a cycle of disable and
 enable of the Guest Service Integration.

.Description
 This script will disable and reenable Guest Service Interface for a number
 of times, it will check the service and daemon integrity and if everything is
 fine it will copy a 5GB large file from host to guest and then check if the size
 is matching.


#>
param([String] $TestParams,
      [object] $AllVmData)

function Main {
    param (
        $VMName,
        $HvServer,
        $Ipv4,
        $VMPort,
        $VMUserName,
        $VMPassword,
        $RootDir,
        $TestParams
    )

    #######################################################################
    #
    #   Main body script
    #
    #######################################################################
    # Read parameters
    $params = $TestParams.TrimEnd(";").Split(";")
    foreach ($p in $params) {
        $fields = $p.Split("=")
        switch ($fields[0].Trim()) {
            "ipv4" { $ipv4 = $fields[1].Trim() }
            "rootDIR" { $rootDir = $fields[1].Trim() }
            "CycleCount" { $CycleCount = $fields[1].Trim() }
            "FcopyFileSize" { $FcopyFileSize = $fields[1].Trim() }
            default {}  # unknown param - just ignore it
        }
    }
    # Change directory
    Set-Location $RootDir
    # if host build number lower than 9600, skip test
    $BuildNumber = Get-HostBuildNumber $HvServer
    if ($BuildNumber -eq 0) {
        return "FAIL"
    }
    elseif ($BuildNumber -lt 9600) {
        return "ABORTED"
    }
    # Check VM state
    $currentState = Check-VMState -vmName $VMName -hvServer $HvServer
    if ($? -ne "True") {
        Write-LogErr "Cannot check VM state"
        return "FAIL"
    }

    # If the VM is in any state other than running power it ON
    if ($currentState -ne "Running") {
        Write-LogInfo "Found $VMName in $currentState state. Powering ON ... "
        Start-VM -vmName $VMName -ComputerName $HvServer
        if ($? -ne "True") {
            Write-LogErr "Unable to Power ON the VM"
            return "FAIL"
        }
        Write-LogInfo "Waiting 60 secs for VM $VMName to start ..."
        Start-Sleep 60
    }

    $null = Check-Systemd -Ipv4 $Ipv4 -SSHPort $VMPort -Username $VMUserName -Password $VMPassword
    if ( -not $True) {
        Write-LogErr "Systemd is not being used. Test Skipped"
        return "FAIL"
    }

    # Get Integration Services status
    $gsi = Get-VMIntegrationService -vmName $VMName -ComputerName $HvServer -Name "Guest Service Interface"
    if ($? -ne "True") {
        Write-LogErr "Unable to run Get-VMIntegrationService on $VMName ($HvServer)"
        return "FAIL"
    }

    # If guest services are not enabled, enable them
    if ($gsi.Enabled -ne "True") {
        Enable-VMIntegrationService -Name "Guest Service Interface" -vmName $VMName -ComputerName $HvServer
        if ($? -ne "True") {
            Write-LogErr "Unable to enable VMIntegrationService on $VMName ($HvServer)"
            return "FAIL"
        }
    }

    # Disable and Enable Guest Service according to the given parameter
    $counter = 0
    while ($counter -lt $CycleCount) {
        Disable-VMIntegrationService -Name "Guest Service Interface" -vmName $VMName -ComputerName $HvServer
        if ($? -ne "True") {
            Write-LogErr "Unable to disable VMIntegrationService on $VMName ($HvServer) on $counter run"
            return "FAIL"
        }
        Start-Sleep 5

        Enable-VMIntegrationService -Name "Guest Service Interface" -vmName $VMName -ComputerName $HvServer
        if ($? -ne "True") {
            Write-LogErr "Unable to enable VMIntegrationService on $VMName ($HvServer) on $counter run"
            return "FAIL"
        }
        Start-Sleep 5
        $counter += 1
    }
    Write-LogInfo "Disabled and Enabled Guest Services $counter times"

    # Get VHD path of tested server; file will be copied there
    $hvPath = Get-VMHost -ComputerName $HvServer | Select-Object -ExpandProperty VirtualHardDiskPath
    if ($? -ne "True") {
        Write-LogErr "Unable to get VM host"
        return "FAIL"
    }

    # Fix path format if it's broken
    if ($hvPath.Substring($hvPath.Length - 1, 1) -ne "\") {
        $hvPath = $hvPath + "\"
    }

    $hvPathFormatted = $hvPath.Replace(':', '$')

    # Define the file-name to use with the current time-stamp
    $testfile = "testfile-$(Get-Date -uformat '%H-%M-%S-%Y-%m-%d').file"
    $filePath = $hvPath + $testfile
    $filePathFormatted = $hvPathFormatted + $testfile

    # Make sure the fcopy daemon is running and Integration Services are OK
    $timer = 0
    while ((Get-VMIntegrationService $VMName | Where-Object {$_.name -eq "Guest Service Interface"}).PrimaryStatusDescription -ne "OK") {
        Start-Sleep -Seconds 5
        Write-LogInfo "Waiting for VM Integration Services $timer"
        $timer += 1
        if ($timer -gt 20) {
            break
        }
    }

    $operStatus = (Get-VMIntegrationService -vmName $VMName -ComputerName $HvServer -Name "Guest Service Interface").PrimaryStatusDescription
    Write-LogInfo "Current Integration Services PrimaryStatusDescription is: $operStatus"
    if ($operStatus -ne "Ok") {
        Write-LogErr "The Guest services are not working properly for VM $VMName!"
        return "FAIL"
    }
    else {
        $fileToCopySize = Convert-StringToUInt64 -str $FcopyFileSize

        # Create a 5GB sample file
        $createFile = fsutil file createnew \\$HvServer\$filePathFormatted $fileToCopySize
        if ($createFile -notlike "File *testfile-*.file is created") {
            Write-LogErr "Could not create the sample test file in the working directory!"
            return "FAIL"
        }
    }

    # Mount attached VHDX
    $sts = Mount-Disk -vmUsername $VMUserName -vmPassword $VMPassword -vmPort $VMPort -ipv4 $Ipv4
    if (-not $sts) {
        Write-LogErr "FAIL to mount the disk in the VM."
        return "FAIL"
    }

    # Daemon name might vary. Get the correct daemon name based on systemctl output
    $daemonName = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort "systemctl list-unit-files | grep fcopy" -runAsSudo
    $daemonName = $daemonName.Split(".")[0]

    $checkProcess = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
        "systemctl is-active $daemonName --quiet" -runAsSudo -ignoreLinuxExitCode
    #will exit with status zero if service is active
    if ( $checkProcess -ne "0" ) {
        Write-LogErr "Warning: $daemonName was not automatically started by systemd. Will start it manually."
        $null = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
        " systemctl start $daemonName" -runAsSudo
    }

    $gsi = Get-VMIntegrationService -vmName $VMName -ComputerName $HvServer -Name "Guest Service Interface"
    if ($gsi.Enabled -ne "True") {
        Write-LogErr "FCopy Integration Service is not enabled"
        return "FAIL"
    }

    # Check for the file to be copied
    Test-Path $filePathFormatted
    if ($? -ne "True") {
        Write-LogErr "File to be copied not found."
        return "FAIL"
    }

    $Error.Clear()
    $copyDuration = (Measure-Command { Copy-VMFile -vmName $VMName -ComputerName $HvServer -SourcePath $filePath -DestinationPath `
                "/mnt/test/" -FileSource host -ErrorAction SilentlyContinue }).totalseconds

    if ($Error.Count -eq 0) {
        Write-LogInfo "File has been successfully copied to guest VM '${vmName}'"
    }
    else {
        Write-LogErr "File could not be copied!"
        return "FAIL"
    }

    [int]$copyDuration = [math]::floor($copyDuration)
    Write-LogInfo "The file copy process took ${copyDuration} seconds"

    # Checking if the file is present on the guest and file size is matching
    $sts = Check-FileInLinuxGuest -vmUserName $VMUserName -vmPassword $VMPassword -vmPort $VMPort -ipv4 $Ipv4 -fileName "/mnt/test/$testfile" -checkSize $true
    if (-not $sts) {
        Write-LogErr "File is not present on the guest VM"
        return "FAIL"
    }
    elseif ($sts -eq $fileToCopySize) {
        Write-LogInfo "The file copied matches the $FcopyFileSize size."
        return "PASS"
    }
    else {
        Write-LogErr "The file copied doesn't match the $FcopyFileSize size!"
        return "FAIL"
    }

    # Removing the temporary test file
    Remove-Item -Path \\$HvServer\$filePathFormatted -Force
    if (-not $?) {
        Write-LogErr "Cannot remove the test file '${testfile}'!"
        return "FAIL"
    }

    $sts = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort "echo 'sleep 5 && bash ~/check_traces.sh ~/check_traces.log &' > runtest.sh" -runAsSudo
    $sts = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort "chmod +x ~/runtest.sh" -runAsSudo
    $sts = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort "./runtest.sh > check_traces.log 2>&1" -runAsSudo
    Start-Sleep 6
    $sts = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort "cat ~/check_traces.log | grep ERROR" -runAsSudo
    Start-Sleep 6
    if ($sts.Contains("ERROR")) {
        Write-LogInfo "Warning: Call traces have been found on VM"
    }
    if ($sts -eq $NULL) {
        Write-LogInfo " No Call traces have been found on VM"
    }
    return "PASS"
}

Main -VMName $AllVMData.RoleName -HvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
    -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
    -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory `
    -TestParams $TestParams
