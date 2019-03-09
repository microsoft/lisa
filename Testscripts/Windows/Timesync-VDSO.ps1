# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Description
    This script tests vDSO.
    The "vDSO" (virtual dynamic shared object) is a small shared library
       that the kernel automatically maps into the address space of all
       user-space applications.
#>

param([string] $TestParams, [object] $AllVMData)

# Main script body
function Main {
    param (
        $Ipv4,
        $VMPort,
        $VMUserName,
        $VMPassword,
        $RootDir
    )
    $supportedKernel = "3.10.0-862"

    # Change the working directory
    if (-not (Test-Path $RootDir)) {
        Write-LogErr "Error: The directory `"${RootDir}`" does not exist"
        return "ABORTED"
    }
    Set-Location $RootDir

    # Check if VM kernel version supports vDSO
    # Kernel version for RHEL 7.5
    $kernelSupport = Get-VMFeatureSupportStatus $Ipv4 $VMPort $VMUserName `
        $VMPassword $supportedKernel

    if ($kernelSupport -ne $True) {
        Write-LogInfo "Info: Current VM Linux kernel version does not support vDSO feature."
        return "ABORTED"
    }

    # Compile gettime.c
    $compileCmd = "gcc /home/${VMUserName}/gettime.c -o /home/${VMUserName}/gettime"
    Run-LinuxCmd -ip $Ipv4 -port $VMPort -username $VMUserName -password `
        $VMPassword -command $compileCmd -runAsSudo
    if ($? -ne $True) {
        Write-LogErr "Error: Unable to compile gettime.c"
        return "ABORTED"
    }

    # Get time
    $timeCmd = "time -p (/home/${VMUserName}/gettime) 2>&1 1>/dev/null"
    $result = Run-LinuxCmd -ip $Ipv4 -port $VMPort -username $VMUserName -password `
             $VMPassword -command $timeCmd -runAsSudo
    $result = $result.Trim()
    Write-LogInfo $result
    #real 3.14 user 3.14 sys 0.00
    $real = $result.split("")[1]  # get real time: 3.14
    $sys = $result.split("")[5]   # get sys time: 0.00

    Write-LogInfo "real time: $real :: sys time: $sys"
    # Support VDSO, sys time should be shorter than 1.0 second
    if (([float]$real -gt 10.0) -or ([float]$sys -gt 1.0)) {
        Write-LogErr "Error: Check real time is $real(>10.0s), sys time is $sys(>1.0s)"
        return "FAIL"
    } else {
        Write-LogInfo "Check real time is $real(<10.0s), sys time is $sys(<1.0s)"
        return "PASS"
    }
}

Main -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
    -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory
