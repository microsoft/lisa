# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Install the nVidia drivers and validates GPU presence
    and total count based on Azure VM size.

.Description
    This script performs the following operations:
    1. On RedHat\CentOS it will first install the LIS RPM drivers
    2. Install nVidia CUDA or GRID drivers
    3. Reboot VM
    4. Check if the nVidia driver is loaded
    5. Compare number of expected GPU adapters with the actual count.
    6. The following tools are used for validation: lsvmbus, lspci, lshw and nvidia-smi
    7. If test parameter "disable_enable_pci=yes" is provided, the 3D controller PCI device
    will be disabled and reenabled first.

#>

param([object] $AllVmData,
      [object] $CurrentTestData,
      [object] $TestProvider,
      [object] $TestParams
    )

function Start-Validation {
    # region PCI Express pass-through in lsvmbus
    $PCIExpress = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort `
        -username $superuser -password $password "lsvmbus -vv" -ignoreLinuxExitCode
    if ( $PCIExpress ) {
        Write-Debug "Successfully fetched the PCIExpress result from lsvmbus"
    } else {
        Write-Error "Could not succeed to fetch out PCIExpress result from lsvmbus"
    }

    Set-Content -Value $PCIExpress -Path $LogDir\PCI-Express-passthrough.txt -Force
    # Scope to match GPUs only since there can be other pass-through devices
    $pciExpressCount = (Select-String -Path $LogDir\PCI-Express-passthrough.txt -Pattern "Device_ID.*47505500").Matches.Count
    if ( $pciExpressCount -gt 0 ) {
        Write-Debug "Successfully found more than a PCI Expess device "
    } else {
        Write-Error "Could not find the PCI Express device count"
    }

    if ($pciExpressCount -eq $expectedGPUCount) {
        $currentResult = $resultPass
        Write-Debug "Successfully verified PCI Express device count with the expected GPU count: $pciExpressCount"
    } else {
        $currentResult = $resultFail
        Write-Error "Failed to verify the PCI Express device count. Expected: $expectedGPUCount, but found: $pciExpressCount"
        $failureCount += 1
    }
    $metaData = "lsvmbus: Expected `"PCI Express pass-through`" count: $expectedGPUCount, count inside the VM: $pciExpressCount"
    $resultArr += $currentResult
    $CurrentTestResult.TestSummary += New-ResultSummary -testResult $currentResult -metaData $metaData `
        -checkValues "PASS,FAIL,ABORTED" -testName $CurrentTestData.testName
    #endregion

    #region lspci
    Write-LogInfo "Install package pciutils to use lspci command."
    Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username $user -password $password `
            -command "which lspci || (. ./utils.sh && install_package pciutils)" -runAsSudo -ignoreLinuxExitCode | Out-Null
    $lspci = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort `
        -username $superuser -password $password "lspci" -ignoreLinuxExitCode

    if ( $lspci ) {
        Write-Debug "Successfully fetched the lspci command result"
    } else {
        Write-Error "Failed to fetch the lspci command result"
    }
    Set-Content -Value $lspci -Path $LogDir\lspci.txt -Force
    $lspciCount = (Select-String -Path $LogDir\lspci.txt -Pattern "NVIDIA Corporation").Matches.Count
    if ($lspciCount -eq $expectedGPUCount) {
        $currentResult = $resultPass
        Write-Debug "Successfully verified PCI device count with lspci result: $lspciCount"
    } else {
        $currentResult = $resultFail
        Write-Error "Failed to verify the PCI device count with lspci device result. Expected: $expectedGPUCount, found: $lspciCount"
        $failureCount += 1
    }
    $metaData = "lspci: Expected `"3D controller: NVIDIA Corporation`" count: $expectedGPUCount, found inside the VM: $lspciCount"
    $resultArr += $currentResult
    $CurrentTestResult.TestSummary += New-ResultSummary -testResult $currentResult -metaData $metaData `
        -checkValues "PASS,FAIL,ABORTED" -testName $CurrentTestData.testName
    #endregion

    #region lshw -c video
    $lshw = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort `
        -username $superuser -password $password "lshw -c video" -ignoreLinuxExitCode
    if ( $lshw ) {
        Write-Debug "Successfully fetch the lshw command result"
    } else {
        Write-Error "Failed to fetch the lshw command result"
    }
    Set-Content -Value $lshw -Path $LogDir\lshw-c-video.txt -Force
    $lshwCount = (Select-String -Path $LogDir\lshw-c-video.txt -Pattern "vendor: NVIDIA Corporation").Matches.Count
    if ($lshwCount -eq $expectedGPUCount) {
        $currentResult = $resultPass
        Write-Debug "Successfully verified lshw count: $lshwCount"
    } else {
        $currentResult = $resultFail
        Write-Error "Failed to verify the lshw command result. Expected: $expectedGPUcount, found: $lshwCount"
        $failureCount += 1
    }
    $metaData = "lshw: Expected Display adapters: $expectedGPUCount, total adapters found in VM: $lshwCount"
    $resultArr += $currentResult
    $CurrentTestResult.TestSummary += New-ResultSummary -testResult $currentResult -metaData $metaData `
        -checkValues "PASS,FAIL,ABORTED" -testName $CurrentTestData.testName
    #endregion

    #region nvidia-smi
    $nvidiasmi = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort `
        -username $superuser -password $password "nvidia-smi" -ignoreLinuxExitCode
    if ( $nvdiasmi ) {
        Write-Debug "Successfully fetched the nvidia-smi command result"
    } else {
        Write-Error "Failed to fetch the nvidia-smi command result"
    }
    Set-Content -Value $nvidiasmi -Path $LogDir\nvidia-smi.txt -Force
    $nvidiasmiCount = (Select-String -Path $LogDir\nvidia-smi.txt -Pattern "Tesla").Matches.Count
    if ($nvidiasmiCount -eq $expectedGPUCount) {
        $currentResult = $resultPass
        Write-Debug "Successfully verified nvidia-smi device count: $nvidiasmiCount"
    } else {
        $currentResult = $resultFail
        Write-Error "Failed to verify nvidia-smi device count. Expected: $expectedGPUCount, found: $nvidiasmiCount"
        $failureCount += 1
    }
    $metaData = "nvidia-smi: Expected GPU count: $expectedGPUCount, found inside the VM: $nvidiasmiCount"
    $resultArr += $currentResult
    $CurrentTestResult.TestSummary += New-ResultSummary -testResult $currentResult -metaData $metaData `
        -checkValues "PASS,FAIL,ABORTED" -testName $CurrentTestData.testName
    return $failureCount
    #endregion
}

function Collect-Logs {
    # Get logs. An extra check for the previous $state is needed
    # The test could actually hang. If state.txt is showing
    # 'TestRunning' then abort the test
    #####
    # We first need to move copy from root folder to user folder for
    # Collect-TestLogs function to work
    Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username $superuser `
        -password $password -command "cp * /home/$user" -ignoreLinuxExitCode:$true
    Collect-TestLogs -LogsDestination $LogDir -ScriptName `
        $currentTestData.files.Split('\')[3].Split('.')[0] -TestType "sh" -PublicIP `
        $allVMData.PublicIP -SSHPort $allVMData.SSHPort -Username $user `
        -password $password -TestName $currentTestData.testName | Out-Null
    # Depending on the stage of the test the files may or may not exist.
    if ($driver -eq "CUDA") {
        Collect-CustomLogFile -PublicIP $allVMData.PublicIP -SSHPort $allVMData.SSHPort `
            -Username $user -Password $password -LogsDestination $LogDir -FileName "install_drivers.log"
        Collect-CustomLogFile -PublicIP $allVMData.PublicIP -SSHPort $allVMData.SSHPort `
            -Username $user -Password $password -LogsDestination $LogDir -FileName "nvidia_dkms_make.log"
        Write-Debug "Successfully collected the CUDA test log"
    }
    if ($driver -eq "GRID") {
        Collect-CustomLogFile -PublicIP $allVMData.PublicIP -SSHPort $allVMData.SSHPort `
            -Username $user -Password $password -LogsDestination $LogDir -FileName "nvidia-installer.log"
        Write-Debug "Successfully collected the GRID test log"
    }
}

function Main {
    param (
        [object] $AllVmData,
        [object] $CurrentTestData,
        [object] $TestProvider,
        [object] $TestParams
    )
    # Create test result
    $currentTestResult = Create-TestResultObject
    $resultArr = @()
    $failureCount = 0
    $superuser="root"
    $testScript = "gpu-driver-install.sh"
    $driverLoaded = $null

    try {
        Provision-VMsForLisa -allVMData $allVMData -installPackagesOnRoleNames "none"
        Copy-RemoteFiles -uploadTo $allVMData.PublicIP -port $allVMData.SSHPort `
            -files $currentTestData.files -username $superuser -password $password -upload | Out-Null
        Write-Debug "Copied all required files to the Guest OS system"

        #Skip test case against distro CLEARLINUX and COREOS based here https://docs.microsoft.com/en-us/azure/virtual-machines/linux/n-series-driver-setup
        if (@("CLEARLINUX", "COREOS").contains($global:detectedDistro)) {
            Write-LogInfo "$($global:detectedDistro) is not supported! Test skipped"
            return $ResultSkipped
        }

        # this covers both NV and NVv2 series
        if ($allVMData.InstanceSize -imatch "Standard_NV") {
            $driver = "GRID"
            Write-Debug "Verfied this instance is with GRID device driver"
        # NC and ND series use CUDA
        } elseif ($allVMData.InstanceSize -imatch "Standard_NC" -or $allVMData.InstanceSize -imatch "Standard_ND") {
            $driver = "CUDA"
            Write-Debug "Verified this instance is with CUDA device driver"
        } else {
            Write-LogErr "Azure VM size $($allVMData.InstanceSize) not supported in automation!"
            $currentTestResult.TestResult = Get-FinalResultHeader -resultarr "ABORTED"
            return $currentTestResult
        }
        $currentTestResult.TestSummary += New-ResultSummary -metaData "Using nVidia driver" -testName $CurrentTestData.testName -testResult $driver

        $cmdAddConstants = "echo -e `"driver=$($driver)`" >> constants.sh"
        Run-LinuxCmd -username $superuser -password $password -ip $allVMData.PublicIP -port $allVMData.SSHPort `
            -command $cmdAddConstants | Out-Null
        Write-Debug "Added GPU driver name to constants.sh file"

        # For CentOS and RedHat the requirement is to install LIS RPMs
        if (@("REDHAT", "CENTOS").contains($global:detectedDistro)) {
            # HPC images already have the LIS RPMs installed
            $sts = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username $user -password $password `
                -command "rpm -qa | grep kmod-microsoft-hyper-v && rpm -qa | grep microsoft-hyper-v" -ignoreLinuxExitCode
            Write-Debug "Checking if HPC image has rpm packages already. Here is query result: $sts"

            if (-not $sts) {
                # Download and install the latest LIS version
                Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username $superuser -password $password `
                    -command "which wget || (. ./utils.sh && install_package wget)" -runAsSudo -ignoreLinuxExitCode | Out-Null
                Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username $superuser `
                    -password $password -command "wget -q https://aka.ms/lis -O - | tar -xz" -ignoreLinuxExitCode | Out-Null
                Write-Debug "Installed the latest LIS package"
                Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username $superuser `
                    -password $password -command "cd LISISO && ./install.sh > installLIS.log" -ignoreLinuxExitCode | Out-Null
                $installLIS = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username $superuser `
                    -password $password -command "cat /$superuser/LISISO/installLIS.log" -ignoreLinuxExitCode
                Write-Debug "Checking installLIS log: $installLIS"

                if ($installLIS -imatch "Unsupported kernel version") {
                    Write-LogInfo "Unsupported kernel version!"
                    $currentTestResult.TestSummary += New-ResultSummary -testName $CurrentTestData.testName -testResult "Unsupported kernel version!"
                    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr "SKIPPED"
                    return $currentTestResult
                } elseif ($installLIS -imatch "Linux Integration Services for Hyper-V has been installed") {
                    Write-LogInfo "LIS has been installed successfully!"
                } else {
                    Write-LogErr "Unable to install the LIS RPMs!"
                    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr "ABORTED"
                    return $currentTestResult
                }
                # Restart VM to load the new LIS drivers
                if (-not $TestProvider.RestartAllDeployments($allVMData)) {
                    Write-LogErr "Unable to connect to VM after restart!"
                    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr "ABORTED"
                    return $currentTestResult
                }
            }
        }

        # Start the test script
        Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username $superuser `
            -password $password -command "/$superuser/${testScript}" -runMaxAllowedTime 1800 -ignoreLinuxExitCode | Out-Null
        Write-Debug "Ran test script $testscript in the Guest OS"

        $installState = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username $superuser `
            -password $password -command "cat /$superuser/state.txt"
        Write-Debug "Found installState: $installState"

        if ($installState -eq "TestSkipped") {
            $currentTestResult.TestResult = Get-FinalResultHeader -resultarr "SKIPPED"
            return $currentTestResult
        }

        if ($installState -imatch "TestAborted") {
            Write-LogErr "GPU drivers installation aborted"
            $currentTestResult.TestResult = Get-FinalResultHeader -resultarr "ABORTED"
            Collect-Logs
            return $currentTestResult
        }

        if ($installState -ne "TestCompleted") {
            Write-LogErr "Unable to install the GPU drivers!"
            $currentTestResult.TestResult = Get-FinalResultHeader -resultarr "FAIL"
            Collect-Logs
            return $currentTestResult
        }

        # Restart VM to load the driver and run validation
        if (-not $TestProvider.RestartAllDeployments($allVMData)) {
            Write-LogErr "Unable to connect to VM after restart!"
            $currentTestResult.TestResult = Get-FinalResultHeader -resultarr "ABORTED"
            return $currentTestResult
        }

        # Mandatory to have the nvidia driver loaded after restart
        $driverLoaded = Run-LinuxCmd -username $user -password $password -ip $allVMData.PublicIP `
            -port $allVMData.SSHPort -command "lsmod | grep nvidia" -ignoreLinuxExitCode
        if ($null -eq $driverLoaded) {
            Write-LogErr "GPU driver is not loaded after VM restart!"
            $currentTestResult.TestResult = Get-FinalResultHeader -resultarr "FAIL"
            Collect-Logs
            return $currentTestResult
        }

        $expectedGPUCount,$null = Get-ExpectedDevicesCount -vmData $allVMData -username $user -password $password -size $allVMData.InstanceSize -type "GPU"
        Write-LogInfo "Azure VM Size: $($allVMData.InstanceSize), expected GPU Adapters total: $expectedGPUCount"

        # Disable and enable the PCI device first if the parameter is given
        if ($TestParams.disable_enable_pci -eq "yes") {
            Run-LinuxCmd -username $user -password $password -ip $allVMData.PublicIP -port $allVMData.SSHPort `
                -command ". utils.sh && DisableEnablePCI GPU" -RunAsSudo -ignoreLinuxExitCode | Out-Null
            if (-not $?) {
                $metaData = "Could not disable and reenable PCI device."
                Write-LogErr "$metaData"
            } else {
                $metaData = "Successfully disabled and reenabled the PCI device."
                Write-LogInfo "$metaData"
            }
            $CurrentTestResult.TestSummary += New-ResultSummary -metaData "$metaData" -testName $CurrentTestData.testName
        }

        # run the tools
        $failureCount = Start-Validation
        if ($failureCount -eq 0) {
            $testResult = $resultPass
        } else {
            $testResult = $resultFail
        }

        Collect-Logs

        Write-LogInfo "Test Completed."
        Write-LogInfo "Test Result: $testResult"
    } catch {
        $ErrorMessage = $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogInfo "EXCEPTION: $ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = $resultAborted
        }
        $resultArr += $testResult
    }

    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult
}

Main -AllVmData $AllVmData -CurrentTestData $CurrentTestData -TestProvider $TestProvider `
    -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n"))
