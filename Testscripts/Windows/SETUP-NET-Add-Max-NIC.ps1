# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Description
This test script will add the maximum amount of synthetic and legacy NICs supported by a linux VM
#>

param([String] $TestParams)

function AddNICs {
    param (
        [string] $VMName, 
        [string] $HvServer, 
        [string] $type, 
        [string] $network_type, 
        [int] $nicsAmount
    )
    if ($type -eq "legacy") {
        $isLegacy = $True
    } else {
        $isLegacy = $False
    }

    for ($i=0; $i -lt $nicsAmount; $i++) {
        LogMsg "Info : Attaching NIC '${network_type}' to '${VMName}'"
        Add-VMNetworkAdapter -VMName $VMName -SwitchName $network_type -ComputerName $HvServer -IsLegacy $isLegacy
    }
}

# Main script body
function Main {
    param (
        $VMName,
        $HvServer,
        $TestParams
    )
    $params = $testParams.Split(";")
    foreach ($p in $params) {
        $temp = $p.Trim().Split('=')
        if ($temp.Length -ne 2) {
            continue
        }

        if ($temp[0].Trim() -eq "NETWORK_TYPE") {
            $network_type = $temp[1]
            if (@("External", "Internal", "Private", "None") -notcontains $network_type) {
                LogErr "Error: Invalid netowrk type"
                return $false
            }
        }

        if ($temp[0].Trim() -eq "TEST_TYPE") {
            $test_type = $temp[1].Split(',')
            if ($test_type.Length -eq 2) {
                if ($test_type[0] -notlike 'legacy' -and $test_type[0] -notlike 'synthetic') {
                    LogErr "Error: Incorrect test type - $test_type[0]"
                    return $false
                }

                if ($test_type[1] -notlike 'legacy' -and $test_type[1] -notlike 'synthetic') {
                    LogErr "Error: Incorrect test type - $test_type[1]"
                    return $false
                }
            } elseif ($test_type -notlike 'legacy' -and $test_type -notlike 'synthetic') {
                LogErr "Error: Incorrect test type - $test_type"
                return $false
            }
        }

        if ($temp[0].Trim() -eq "SYNTHETIC_NICS") {
            $syntheticNICs = $temp[1] -as [int]
            [int]$hostBuildNumber = (Get-WmiObject -class Win32_OperatingSystem -ComputerName $HvServer).BuildNumber
            if ($hostBuildNumber -le 9200) {
                [int]$syntheticNICs  = 2
            }
        } elseif ($temp[0].Trim() -eq "LEGACY_NICS") {
            $legacyNICs = $temp[1] -as [int]
        }
    }

    #
    # Hot Add a Synthetic NIC to the SUT VM.  Specify a NIC name of "Hot Add NIC".
    # This will make it easy to later identify the NIC to remove.
    #
    if ($test_type.Length -eq 2) {
        foreach ($test in $test_type) {
            if ($test -eq "legacy") {
                AddNICs $VMName $HvServer $test $network_type $legacyNICs
            } else {
                AddNICs $VMName $HvServer $test $network_type $syntheticNICs
            }
        }
    } else {
        if ($test_type -eq "legacy") {
            AddNICs $VMName $HvServer $test_type $network_type $legacyNICs
        } else {
            AddNICs $VMName $HvServer $test_type $network_type $syntheticNICs
        }
    }

    if (-not $?) {
        LogErr 0 "Error: Unable to add multiple NICs on VM '${VMName}' on server '${HvServer}'"
        return $false
    }

    return $True
}

Main -VMName $AllVMData.RoleName -HvServer $xmlConfig.config.Hyperv.Host.ServerName `
         -TestParams $TestParams