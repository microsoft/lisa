# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Description
    This setup script adds a NIC to all VMs found in $allVmData.
    It will enable SR-IOV if the TC requires it. After attaching the NIC,
    the VMs will be booted and a static IP will be assigned to each one. These
    static IPs will also be set in $allVmData for later use
#>

param(
    [String] $TestParams
)

function Main {
    param (
        $TestParams
    )

    try {
        $testResult = $null
        $sudoUser = "root"
        $bootproto = "static"
        $netmask = "255.255.255.0"
        $newVMData = @()

        # Loop through each VM
        foreach ($vmData in $allVMData) {
            # Stopping VMs
            Stop-HyperVGroupVMs $vmData.HyperVGroupName $vmData.HypervHost

            # Adding NIC
            Write-LogInfo "Adding $($TestParams.PERF_NIC) to $($vmData.RoleName) on $($vmData.HypervHost) host"
            Add-VMNetworkAdapter -VMName $vmData.RoleName -ComputerName `
                $vmData.HypervHost -SwitchName $TestParams.PERF_NIC

            # Enable SR-IOV if it's the case
            if ($currentTestData.AdditionalHWConfig.Networking -imatch "SRIOV") {
                Write-LogInfo "Will enable SR-IOV on the newly added NIC"
                $(Get-VM -Name $vmData.RoleName -ComputerName $vmData.HypervHost).NetworkAdapters `
                    | Where-Object { $_.SwitchName -imatch $TestParams.PERF_NIC } `
                    | Set-VMNetworkAdapter -IovWeight 1
                if ($? -ne $True) {
                    throw "Error: Unable to enable SRIOV"
                }
            }

            # Start VM, get IP and MAC address
            $tempIpv4 = Start-VMandGetIP $vmData.RoleName $vmData.HypervHost $vmData.SSHPort `
                $user $password
            if (-not $tempIpv4) {
                throw "Error: Unable to start $($vmData.RoleName) and get an IPv4 address"
            }
            $testNic = $(Get-VM -Name $vmData.RoleName -ComputerName $vmData.HypervHost).NetworkAdapters `
                | Where-Object { $_.SwitchName -imatch $TestParams.PERF_NIC }
            $testMac = $testNic.MacAddress
            for ($i=2; $i -lt 16; $i=$i+2) {
                $testMac = $testMac.Insert($i,':')
                $i++
            }
            if ($vmData.RoleName -imatch "role-0") {
                $staticIP = $TestParams.STATIC_IP_1
            } elseif ($vmData.RoleName -imatch "role-1") {
                $staticIP = $TestParams.STATIC_IP_2
            } else {
                throw "Could not get the VM names"
            }

            # Configure the newly added NIC with a static IP address
            Set-GuestInterface $sudoUser $tempIpv4 $vmData.SSHPort $password $testMac `
                $staticIP $bootproto $netmask $vmData.RoleName
            if (-not $?) {
                throw "Error: Failed to configure the NIC on $($vmData.RoleName)"
            }

            # Set the static IP in allVMData
            $vmData.InternalIP = $staticIP
            $newVMData += $vmData
        }

        $global:AllVMData = $newVMData
        Write-LogInfo "Successfully configured VMs for Hyper-V Network Perf test"
        $testResult = "PASS"
    } catch {
        $ErrorMessage = $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = "ABORTED"
        }
        $resultArr += $testResult
    }
    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}

Main -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n"))