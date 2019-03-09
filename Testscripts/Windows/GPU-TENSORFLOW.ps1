# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

param([object] $AllVmData,
      [object] $CurrentTestData,
      [String] $TestParams,
      [object] $TestProvider
    )

function Run-TestScript ($ip, $port, $testScript)
{
    Run-LinuxCmd -username $user -password $password -ip $ip -port $port -command "chmod a+x *.sh" -runAsSudo
    Write-LogInfo "Executing : ${testScript}"
    $cmd = "bash /home/$user/${testScript}"
    $testJob = Run-LinuxCmd -username $user -password $password -ip $ip -port $port -command $cmd -runAsSudo -RunInBackground
    $timeCount = 0
    while ((Get-Job -Id $testJob).State -eq "Running") {
        $currentStatus = Run-LinuxCmd -username $user -password $password -ip $ip -port $port -command "cat /home/$user/state.txt" -runAsSudo
        Write-LogInfo "Current test status : $currentStatus"
        Wait-Time -seconds 30
        $timeCount += 30
        if ($timeCount -gt 7200) {
            break
        }
    }
    $currentStatus = Run-LinuxCmd -username $user -password $password -ip $ip -port $port -command "cat /home/$user/state.txt" -runAsSudo
    return $currentStatus
}

function Main {
    param (
        [object] $AllVmData,
        [object] $CurrentTestData,
        $TestParams,
        [object] $TestProvider
    )
    # Create test result
    $currentTestResult = Create-TestResultObject
    $resultArr = @()

    try {
        Provision-VMsForLisa -allVMData $allVMData -installPackagesOnRoleNames "none"
        Copy-RemoteFiles -uploadTo $allVMData.PublicIP -port $allVMData.SSHPort `
            -files $currentTestData.files -username $user -password $password -upload | Out-Null

        # This covers both NV and NVv2 series
        if ($allVMData.InstanceSize -imatch "Standard_NV") {
            $driver = "GRID"
        # NC and ND series use CUDA
        } elseif ($allVMData.InstanceSize -imatch "Standard_NC" -or $allVMData.InstanceSize -imatch "Standard_ND") {
            $driver = "CUDA"
        } else {
            Write-LogErr "Azure VM size $($allVMData.InstanceSize) not supported in automation!"
            $currentTestResult.TestResult = Get-FinalResultHeader -resultarr "ABORTED"
            return $currentTestResult
        }

        # Install CUDA/GRID driver
        $workDir = Get-Location
        $SETUP_SCRIPT = $currentTestData.preTestScript
        $scriptLocation = Join-Path $workDir ".\Testscripts\Windows\$SETUP_SCRIPT"
        $result = & "${scriptLocation}" -TestParams $scriptParameters -AllVMData $VMData `
                  -CurrentTestData $CurrentTestData -TestProvider $TestProvider
        if ($result -match "PASS") {
            #Start the test script
            $testScript = "gpu-tensorflow.sh"
            Run-TestScript -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -testScript $testScript | Out-Null
            $testResult = Collect-TestLogs -LogsDestination $LogDir -ScriptName $currentTestData.files.Split('\')[3].Split('.')[0] `
                          -TestType "sh" -PublicIP $allVMData.PublicIP -SSHPort $allVMData.SSHPort -Username $user `
                          -password $password -TestName $currentTestData.testName

            Remove-Item "$LogDir\*.csv" -Force
            $remoteFiles = "*.csv,*.log"
            Copy-RemoteFiles -download -downloadFrom $allVMData.PublicIP -files $remoteFiles -downloadTo $LogDir `
                -port $allVMData.SSHPort -username $user -password $password
        }

        if ($testResult -match "PASS") {
            Write-LogInfo "Generating the performance data for database insertion"
            foreach ($param in $currentTestData.TestParameters.param) {
                if ($param -match "CUDADriverVersion") {
                    $CUDADriverVersion = $param.Replace("CUDADriverVersion=","").Replace('"',"")
                }
                if ($param -match "CudaToolkitVersion") {
                    $CudaToolkitVersion = $param.Replace("CudaToolkitVersion=","").Replace('"',"")
                }
                if ($param -match "TensorflowVersion") {
                    $TensorflowVersion = $param.Replace("TensorflowVersion=","").Replace('"',"")
                    if (-not $TensorflowVersion) {
                        $TensorflowVersion = "tf-nightly-gpu"
                    }
                }
            }

            $detectedDistro = Detect-LinuxDistro -VIP $vmData.PublicIP -SSHport $vmData.SSHPort `
                    -testVMUser $user -testVMPassword $password
            $properties = Get-VMProperties -PropertyFilePath "$LogDir\VM_properties.csv"
            $testDate = $(Get-Date -Format yyyy-MM-dd)
            $testDataCsv = Import-Csv -Path $LogDir\tensorflowBenchmark.csv
            foreach ($mode in $testDataCsv) {
                $resultMap = @{}
                if ($properties) {
                    $resultMap["GuestDistro"] = $properties.GuestDistro
                    $resultMap["KernelVersion"] = $properties.KernelVersion
                }
                $resultMap["DriverType"] = $driver
                $resultMap["CUDADriverVersion"] = $CUDADriverVersion
                $resultMap["CudaToolkitVersion"] = $CudaToolkitVersion
                $resultMap["TensorflowVersion"] = $TensorflowVersion
                $resultMap["HostType"] = $global:TestPlatform
                $resultMap["HostBy"] = $global:TestLocation
                $resultMap["GuestOSType"] = $detectedDistro
                $resultMap["GuestSize"] = $AllVMData.InstanceSize
                $resultMap["TestCaseName"] = $global:GlobalConfig.Global.Azure.ResultsDatabase.testTag
                $resultMap["TestDate"] = $testDate
                $resultMap["TestMode"] = $mode.model
                $resultMap["BatchSize"] = [int32]($mode.batch_size)
                $resultMap["GpuCount"] = [int32]($mode.num_gpus)
                $resultMap["TotalImages_sec"] = [Decimal]($mode.total_images_sec)
                $resultMap["UtilizationMemory"] = [int32]($mode.utilization_mem_avg)
                $resultMap["UtilizationGPU"] = [int32]($mode.utilization_gpu_avg)
                Write-LogInfo "Collected performance data for $($mode.model) mode."
                $currentTestResult.TestResultData += $resultMap
            }
        }
        Write-LogInfo "Test Completed."
        Write-LogInfo "Test Result: $testResult"
    } catch {
        $ErrorMessage = $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogInfo "EXCEPTION: $ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = "ABORTED"
        }
        $resultArr += $testResult
    }

    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult
}

Main -AllVmData $AllVmData -CurrentTestData $CurrentTestData -TestProvider $TestProvider -TestParams $TestParams
