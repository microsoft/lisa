# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

function Main {
    # Create test result
    $resultArr = @()

    try {
        $clientVMData = $allVMData
        #region CONFIGURE VM FOR N SERIES GPU TEST
        Write-LogInfo "Test VM details :"
        Write-LogInfo "  RoleName : $($clientVMData.RoleName)"
        Write-LogInfo "  Public IP : $($clientVMData.PublicIP)"
        Write-LogInfo "  SSH Port : $($clientVMData.SSHPort)"

        # PROVISION VMS FOR LISA WILL ENABLE ROOT USER AND WILL MAKE ENABLE PASSWORDLESS AUTHENTICATION ACROSS ALL VMS IN SAME HOSTED SERVICE.
        Provision-VMsForLisa -allVMData $allVMData -installPackagesOnRoleNames "none"
        #endregion

        #region Install N-Vidia Drivers and reboot.
        $myString = @"
cd /root/
./InstallCUDADrivers.sh -logFolder /root &> GPUConsoleLogs.txt
. utils.sh
collect_VM_properties
"@
        $StartScriptName = "StartGPUDriverInstall.sh"
        Set-Content "$LogDir\$StartScriptName" $myString
        Copy-RemoteFiles -uploadTo $clientVMData.PublicIP -port $clientVMData.SSHPort -files "$LogDir\$StartScriptName" -username "root" -password $password -upload
        Copy-RemoteFiles -uploadTo $clientVMData.PublicIP -port $clientVMData.SSHPort -files "$($currentTestData.files)" -username "root" -password $password -upload
        $null = Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort -username "root" -password $password -command "chmod +x *.sh"
        $testJob = Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort -username "root" -password $password -command "/root/$StartScriptName" -RunInBackground
        #endregion

        #region MONITOR TEST
        while ((Get-Job -Id $testJob).State -eq "Running") {
            $currentStatus = Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort -username "root" -password $password -command "tail -n 1 GPUConsoleLogs.txt"
            Write-LogInfo "Current Test Status : $currentStatus"
            Wait-Time -seconds 20
        }

        Copy-RemoteFiles -downloadFrom $clientVMData.PublicIP -port $clientVMData.SSHPort -username "root" -password $password -download -downloadTo $LogDir -files "VM_properties.csv"
        Copy-RemoteFiles -downloadFrom $clientVMData.PublicIP -port $clientVMData.SSHPort -username "root" -password $password -download -downloadTo $LogDir -files "GPUConsoleLogs.txt"
        $GPUDriverInstallLogs = Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort -username "root" -password $password -command "cat GPU_Test_Logs.txt"

        if ($GPUDriverInstallLogs -imatch "GPU_DRIVER_INSTALLATION_SUCCESSFUL") {
            #Reboot VM.
            Write-LogInfo "*********************************************************"
            Write-LogInfo "GPU Drivers installed successfully. Restarting VM now..."
            Write-LogInfo "*********************************************************"
            $restartStatus = Restart-AllDeployments -allVMData $clientVMData
            if ($restartStatus -eq "True") {
                if (($clientVMData.InstanceSize.Contains("Standard_NC6")) -or
                        ($clientVMData.InstanceSize.Contains("Standard_NC6s_v2")) -or
                        ($clientVMData.InstanceSize.Contains("Standard_NV6"))) {
                    $expectedCount = 1
                }
                elseif (($clientVMData.InstanceSize.Contains("Standard_NC12")) -or
                        ($clientVMData.InstanceSize.Contains("Standard_NC12s_v2")) -or
                        ($clientVMData.InstanceSize.Contains("Standard_NV12"))) {
                    $expectedCount = 2
                }
                elseif (($clientVMData.InstanceSize.Contains("Standard_NC24")) -or
                        ($clientVMData.InstanceSize.Contains("Standard_NC24s_v2")) -or
                        ($clientVMData.InstanceSize.Contains("Standard_NV24"))) {
                    $expectedCount = 4
                }
                elseif (($clientVMData.InstanceSize.Contains("Standard_NC24r")) -or
                        ($clientVMData.InstanceSize.Contains("Standard_NC24rs_v2"))) {
                    $expectedCount = 4
                }
                Write-LogInfo "Test VM Size: $($clientVMData.InstanceSize). Expected GPU Adapters : $expectedCount"
                $errorCount = 0
                #Adding sleep of 180 seconds, giving time to load nvidia drivers.
                Write-LogInfo "Waiting 3 minutes. (giving time to load nvidia drivers)"
                Start-Sleep -Seconds 180
                #region PCI Express pass-through
                $PCIExpress = Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort -username "root" -password $password -command "lsvmbus" -ignoreLinuxExitCode
                Set-Content -Value $PCIExpress -Path $LogDir\PIC-Express-pass-through.txt -Force
                if ((Select-String -Path $LogDir\PIC-Express-pass-through.txt -Pattern "PCI Express pass-through").Matches.Count -eq $expectedCount) {
                    Write-LogInfo "Expected `"PCI Express pass-through`" count: $expectedCount. Observed Count: $expectedCount"
                    $currentTestResult.TestSummary += New-ResultSummary -testResult "PASS" -metaData "PCI Express pass-through" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                } else {
                    $errorCount += 1
                    Write-LogErr "Error in lsvmbus Outoput."
                    Write-LogErr "$PCIExpress"
                    $currentTestResult.TestSummary += New-ResultSummary -testResult "FAIL" -metaData "PCI Express pass-through" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                }
                #endregion

                #region lspci
                $lspci = Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort -username "root" -password $password -command "lspci" -ignoreLinuxExitCode
                Set-Content -Value $lspci -Path $LogDir\lspci.txt -Force
                if ((Select-String -Path $LogDir\lspci.txt -Pattern "NVIDIA Corporation").Matches.Count -eq $expectedCount) {
                    Write-LogInfo "Expected `"3D controller: NVIDIA Corporation`" count: $expectedCount. Observed Count: $expectedCount"
                    $currentTestResult.TestSummary += New-ResultSummary -testResult "PASS" -metaData "lspci" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                } else {
                    $errorCount += 1
                    Write-LogErr "Error in lspci Outoput."
                    Write-LogErr "$lspci"
                    $currentTestResult.TestSummary += New-ResultSummary -testResult "FAIL" -metaData "lspci" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                }
                #endregion

                #region PCI lshw -c video
                $lshw = Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort -username "root" -password $password -command "lshw -c video" -ignoreLinuxExitCode
                Set-Content -Value $lshw -Path $LogDir\lshw-c-video.txt -Force
                if (((Select-String -Path $LogDir\lshw-c-video.txt -Pattern "product: NVIDIA Corporation").Matches.Count -eq $expectedCount) -or ((Select-String -Path $LogDir\lshw-c-video.txt -Pattern "vendor: NVIDIA Corporation").Matches.Count -eq $expectedCount)) {
                    Write-LogInfo "Expected Display adapters: $expectedCount. Observed adapters: $expectedCount"
                    $currentTestResult.TestSummary += New-ResultSummary -testResult "PASS" -metaData "lshw -c video" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                } else {
                    $errorCount += 1
                    Write-LogErr "Error in display adapters."
                    Write-LogErr "$lshw"
                    $currentTestResult.TestSummary += New-ResultSummary -testResult "FAIL" -metaData "lshw -c video" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                }
                #endregion

                #region PCI nvidia-smi
                $nvidiasmi = Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort -username "root" -password $password -command "nvidia-smi" -ignoreLinuxExitCode
                Set-Content -Value $nvidiasmi -Path $LogDir\nvidia-smi.txt -Force
                if ((Select-String -Path $LogDir\nvidia-smi.txt -Pattern "Tesla ").Matches.Count -eq $expectedCount) {
                    Write-LogInfo "Expected Tesla count: $expectedCount. Observed count: $expectedCount"
                    $currentTestResult.TestSummary += New-ResultSummary -testResult "PASS" -metaData "nvidia-smi" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                } else {
                    $errorCount += 1
                    Write-LogErr "Error in nvidia-smi."
                    Write-LogErr "$nvidiasmi"
                    $currentTestResult.TestSummary += New-ResultSummary -testResult "FAIL" -metaData "nvidia-smi" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                }
                #endregion
            } else {
                Write-LogErr "Unable to connect to test VM after restart"
                $testResult = "FAIL"
            }
        }
        #endregion

        if ( ($errorCount -ne 0)) {
            Write-LogErr "Test failed. : $summary."
            $testResult = "FAIL"
        }
        elseif ($errorCount -eq 0) {
            Write-LogInfo "Test Completed."
            $testResult = "PASS"
        }
        Write-LogInfo "Test result : $testResult"
        Write-LogInfo "Test Completed"
    } catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogInfo "EXCEPTION : $ErrorMessage at line: $ErrorLine"
        $exception =  $_.Exception
        Write-LogInfo "EXCEPTION FULL: $exception"
    } finally {
        if (!$testResult) {
            $testResult = "Aborted"
        }
        $resultArr += $testResult
    }

    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}

Main
