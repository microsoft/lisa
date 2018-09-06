# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Description
    Test LIS and shutdown with different RAM settings
#>

param([string] $TestParams)

# Main script body
function Main {
    param (
        $VMName,
        $HvServer,
        $Ipv4,
        $VMPort,
        $VMUserName,
        $VMPassword,
        $RootDir
    )
    $retVal = "FAIL"
    $new_ipv4 = $null

    # Change the working directory to where we need to be
    if (-not (Test-Path $rootDir)) {
        LogErr "Error: The directory `"${rootDir}`" does not exist"
        return "FAIL"
    }
    Set-Location $rootDir

    # Get free memory from server
    $osInfo = Get-WMIObject Win32_OperatingSystem -ComputerName $HvServer
    $freeMem = [int]$($OSInfo.FreePhysicalMemory) / 1MB

    # Array of memory size to boot( total available memory, 70% of available memory, 40% of available memory)
    $mem100 = "{0:N0}" -f $($freeMem - 2)
    $mem70 = "{0:N0}" -f $($freeMem * 0.7)
    $mem40 = "{0:N0}" -f $($freeMem * 0.4)
    $memArray = $mem100, $mem70, $mem40

    foreach ($memory in $memArray) {
        # Shutdown VM.
        $vm = Get-VM -Name $VMName -ComputerName $HvServer
        if ($vm.State -ne "Off") {
            Stop-VM -Name $VMName -ComputerName $HvServer -Force
            if (-not $?) {
               LogErr "Error: Unable to Shut Down VM"
               $retVal = "FAIL"
               break
            }

            $timeout = 180
            $sts = Wait-ForVMToStop $VMName $HvServer $timeout
            if (-not $sts) {
               LogErr "Error: WaitForVMToStop fail"
               $retVal = "FAIL"
               break
            }
        }

        $memoryParam = "VMMemory = ${memory}GB"
        $sts = .\Testscripts\Windows\Set-VM-Memory.ps1 -vmName $VMName -hvServer $HvServer -testParams $memoryParam
        if ($sts[-1] -eq "True") {
            LogMsg "VM memory count updated to $memory GB RAM"
        } else {
            LogErr "Error: Unable to update VM memory to $memory GB RAM. Consider changing the value."
            $retVal = "FAIL"
            break
        }

        $Error.Clear()
        Start-VM -Name $VMName -ComputerName $HvServer  -ErrorAction SilentlyContinue
        if ($Error[0] -and $Error[0].Exception.Message.Contains("Not enough memory")) {
            LogErr "Error: Not enough memory ($memory) GB to start VM. Consider changing the value."
            $retVal = "FAIL"
            break
        }

        $Error.Clear()
        # If the VM has no IP it means it rebooted
        $new_ipv4 = Get-IPv4AndWaitForSSHStart $VMName $HvServer $VMPort $VMUserName $VMPassword 300
        if ($new_ipv4) {
            # In some cases the IP changes after a reboot
            LogMsg "${VMName} IP Address after reboot: ${new_ipv4}"
            Set-Variable -Name "Ipv4" -Value $new_ipv4 -Scope Global
        } else {
            LogErr "Error: VM $VMName failed to start after setting $numCPUs vCPUs"
            $retVal = "FAIL"
            break
        }

        $retVal = "PASS"
    }

    return $retVal
}

Main -VMName $AllVMData.RoleName -hvServer $xmlConfig.config.Hyperv.Host.ServerName `
         -ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
         -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory