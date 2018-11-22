# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Description
    Modify the number of CPUs the VM has.
#>

param([String] $TestParams)

function Main {
    param (
        $VMName,
        $HvServer,
        $TestParams
    )

    $numCPUs = 0
    $maxCPUs = 0
    $numaNodes = 8
    $sockets = 1
    $mem = $null
    $memWeight = $null
    $startupMem = $null
    $retVal = $false

    # Check input arguments
    if ($null -eq $TestParams -or $TestParams.Length -lt 3) {
        LogErr "The script $MyInvocation.InvocationName requires the VCPU test parameter"
        return $retVal
    }

    # Find the TestParams we require.  Complain if not found
    $params = $TestParams.Split(";")
    foreach ($p in $params) {
        $fields = $p.Split("=")
        if ($fields[0].Trim() -eq "VCPU") {
            $numCPUs = $fields[1].Trim()
        }
        if ($fields[0].Trim() -eq "NumaNodes") {
            $numaNodes = $fields[1].Trim()
        }
        if ($fields[0].Trim() -eq "Sockets") {
            $sockets = $fields[1].Trim()
        }
        if ($fields[0].Trim() -eq "MemSize") {
            $mem = $fields[1].Trim()
        }
        if ($fields[0].Trim() -eq "MemWeight") {
            $memWeight = [Convert]::ToInt32($fields[1].Trim())
        }
        if ($fields[0].Trim() -eq "startupMem") {
            $startupMem = Convert-ToMemSize $fields[1].Trim() $HvServer
        }
    }

    if ($numCPUs -eq 0) {
        LogErr "VCPU test parameter not found in TestParams"
        return $retVal
    }

    # Do a sanity check on the value provided in the TestParams
    $procs = get-wmiobject -computername $HvServer win32_processor
    if ($procs) {
        if ($procs -is [array]) {
            foreach ($n in $procs) {
                $maxCPUs += $n.NumberOfLogicalProcessors
            }
        } else {
            $maxCPUs = $procs.NumberOfLogicalProcessors
        }
    }

    # If 'max' parameter was specified, will try to add the maximum vCPU allowed
    if ($numCPUs -eq "max")  {
        $vm = Get-VM -Name $VMName -ComputerName $HvServer

        # Depending on generation, the maximum allowed vCPU varies
        # On gen1 is 64 vCPU, on gen2 is 240 vCPU
        if ($vm.generation -eq 1) {
            [int]$maxAllowed = 64
        }
        else {
            [int]$maxAllowed = 240
        }

        if ($maxCPUs -gt $maxAllowed) {
            $numCPUs = $maxAllowed
        } else {
            $numCPUs = $maxCPUs
        }

    } else {
       [int]$numCPUs = $numCPUs
    }

    if ($numCPUs -lt 1 -or $numCPUs -gt $maxCPUs) {
        LogErr "Incorrect VCPU value: $numCPUs (max CPUs = $maxCPUs)"
    }

    # Update the CPU count on the VM
    Set-VM -Name $VMName -ComputerName $HvServer -ProcessorCount $numCPUs

    if ($? -eq "True") {
        LogMsg "CPU count updated to $numCPUs"
        $retVal = $true
    } else {
        LogErr "Unable to update CPU count to $numCPUs"
        return $retVal
    }

    Set-VMProcessor -VMName $VMName -ComputerName $HvServer -MaximumCountPerNumaNode $numaNodes -MaximumCountPerNumaSocket $sockets
    if ($? -eq "True") {
        LogMsg "NUMA Nodes updated"
        $retVal = $true
    } else {
        $retVal = $false
        LogErr "Unable to update NUMA nodes!"
    }

    if ($null -ne $memWeight) {
        Set-VMMemory $VMName -ComputerName $HvServer -Priority $memWeight
    }

    if ($null -ne $startupMem) {
        Set-VMMemory -vmName $VMName -ComputerName $HvServer -DynamicMemoryEnabled $false -StartupBytes $startupMem
    }

    if ($null -ne $mem) {
        $staticMemory = Convert-StringToDecimal $mem
        Set-VMMemory $VMName -ComputerName $HvServer -MaximumAmountPerNumaNodeBytes $staticMemory -Priority $memWeight
        if ($? -eq "True") {
            LogMsg "NUMA memory updated"
            $retVal = $true
        } else {
            LogErr "Unable to update NUMA memory $mem"
            $retVal = $false
        }
    }

    return $retVal
}

Main -VMName $AllVMData.RoleName -hvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
         -TestParams $TestParams
