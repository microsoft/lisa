# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

function Main {
    $resultArr = @()

    try {
        $NoServer = $true
        $NoClient = $true
        $ClientMachines = @()
        $SlaveInternalIPs = ""
        foreach ( $VmData in $AllVMData ) {
            if ( $VmData.RoleName -imatch "controller" ) {
                $ServerVMData = $VmData
                $NoServer = $false
            }
            elseif ( $VmData.RoleName -imatch "Client" ) {
                $ClientMachines += $VmData
                $NoClient = $fase
                if ( $SlaveInternalIPs ) {
                    $SlaveInternalIPs += "," + $VmData.InternalIP
                }
                else {
                    $SlaveInternalIPs = $VmData.InternalIP
                }
            }
        }
        if ( $NoServer ) {
            Throw "No any server VM defined. Be sure that, `
            server VM role name matches with the pattern `"*server*`". Aborting Test."
        }
        if ( $NoClient ) {
            Throw "No any client VM defined. Be sure that, `
            client machine role names matches with pattern `"*client*`" Aborting Test."
        }
        if ($ServerVMData.InstanceSize -imatch "Standard_NC") {
            LogMsg "Waiting 5 minutes to finish RDMA update for NC series VMs."
            Start-Sleep -Seconds 300
        }
        #region CONFIGURE VMs for TEST

        LogMsg "SERVER VM details :"
        LogMsg "  RoleName : $($ServerVMData.RoleName)"
        LogMsg "  Public IP : $($ServerVMData.PublicIP)"
        LogMsg "  SSH Port : $($ServerVMData.SSHPort)"
        $i = 1
        foreach ( $ClientVMData in $ClientMachines ) {
            LogMsg "CLIENT VM #$i details :"
            LogMsg "  RoleName : $($ClientVMData.RoleName)"
            LogMsg "  Public IP : $($ClientVMData.PublicIP)"
            LogMsg "  SSH Port : $($ClientVMData.SSHPort)"
            $i += 1
        }
        $FirstRun = $true

        ProvisionVMsForLisa -AllVMData $AllVMData -installPackagesOnRoleNames "none"

        #endregion

        #region Generate constants.sh
        # We need to add extra parameters to constants.sh file apart from parameter properties defined in XML.
        # Hence, we are generating constants.sh file again in test script.

        LogMsg "Generating constansts.sh ..."
        $constantsFile = ".\$LogDir\constants.sh"
        foreach ($TestParam in $CurrentTestData.TestParameters.param ) {
            Add-Content -Value "$TestParam" -Path $constantsFile
            LogMsg "$TestParam added to constansts.sh"
            if ($TestParam -imatch "imb_mpi1_tests_iterations") {
                $ImbMpiTestIterations = [int]($TestParam.Replace("imb_mpi1_tests_iterations=", "").Trim('"'))
            }
            if ($TestParam -imatch "imb_rma_tests_iterations") {
                $ImbRmaTestIterations = [int]($TestParam.Replace("imb_rma_tests_iterations=", "").Trim('"'))
            }
            if ($TestParam -imatch "imb_nbc_tests_iterations") {
                $ImbNbcTestIterations = [int]($TestParam.Replace("imb_nbc_tests_iterations=", "").Trim('"'))
            }
            if ($TestParam -imatch "ib_nic") {
                $InfinibandNic = [string]($TestParam.Replace("ib_nic=", "").Trim('"'))
            }
        }

        Add-Content -Value "master=`"$($ServerVMData.InternalIP)`"" -Path $constantsFile
        LogMsg "master=$($ServerVMData.InternalIP) added to constansts.sh"

        Add-Content -Value "slaves=`"$SlaveInternalIPs`"" -Path $constantsFile
        LogMsg "slaves=$SlaveInternalIPs added to constansts.sh"

        LogMsg "constanst.sh created successfully..."
        #endregion

        #region Upload files to master VM...
        RemoteCopy -uploadTo $ServerVMData.PublicIP -port $ServerVMData.SSHPort `
            -files "$constantsFile,$($CurrentTestData.files)" -username "root" -password $password -upload
        #endregion

        RemoteCopy -uploadTo $ServerVMData.PublicIP -port $ServerVMData.SSHPort `
            -files "$constantsFile" -username "root" -password $password -upload
        $out = RunLinuxCmd -ip $ServerVMData.PublicIP -port $ServerVMData.SSHPort `
        -username "root" -password $password -command "chmod +x *.sh"
        $RemainingRebootIterations = $CurrentTestData.NumberOfReboots
        $ExpectedSuccessCount = [int]($CurrentTestData.NumberOfReboots) + 1
        $TotalSuccessCount = 0
        $Iteration = 0
        do {
            if ($FirstRun) {
                $FirstRun = $false
                $ContinueMPITest = $true
                foreach ( $ClientVMData in $ClientMachines ) {
                    LogMsg "Getting initial MAC address info from $($ClientVMData.RoleName)"
                    RunLinuxCmd -ip $ServerVMData.PublicIP -port $ServerVMData.SSHPort -username "root" `
                        -password $password "ifconfig $InfinibandNic | grep ether | awk '{print `$2}' > InitialInfiniBandMAC.txt"
                }
            }
            else {
                $ContinueMPITest = $true
                foreach ( $ClientVMData in $ClientMachines ) {
                    LogMsg "Step 1/2: Getting current MAC address info from $($ClientVMData.RoleName)"
                    $CurrentMAC = RunLinuxCmd -ip $ServerVMData.PublicIP -port $ServerVMData.SSHPort -username "root" `
                        -password $password "ifconfig $InfinibandNic | grep ether | awk '{print `$2}'"
                    $InitialMAC = RunLinuxCmd -ip $ServerVMData.PublicIP -port $ServerVMData.SSHPort -username "root" `
                        -password $password "cat InitialInfiniBandMAC.txt"
                    if ($CurrentMAC -eq $InitialMAC) {
                        LogMsg "Step 2/2: MAC address verified in $($ClientVMData.RoleName)."
                    }
                    else {
                        LogErr "Step 2/2: MAC address swapped / changed in $($ClientVMData.RoleName)."
                        $ContinueMPITest = $false
                    }
                }
            }

            if ($ContinueMPITest) {
                #region EXECUTE TEST
                $Iteration += 1
                LogMsg "******************Iteration - $Iteration/$ExpectedSuccessCount*******************"
                $TestJob = RunLinuxCmd -ip $ServerVMData.PublicIP -port $ServerVMData.SSHPort -username "root" `
                    -password $password -command "/root/TestRDMA_MultiVM.sh" -RunInBackground
                #endregion

                #region MONITOR TEST
                while ( (Get-Job -Id $TestJob).State -eq "Running" ) {
                    $CurrentStatus = RunLinuxCmd -ip $ServerVMData.PublicIP -port $ServerVMData.SSHPort -username "root" `
                        -password $password -command "tail -n 1 /root/TestExecution.log"
                    LogMsg "Current Test Staus : $CurrentStatus"
                    WaitFor -seconds 10
                }

                RemoteCopy -downloadFrom $ServerVMData.PublicIP -port $ServerVMData.SSHPort -username "root" `
                    -password $password -download -downloadTo $LogDir -files "/root/$InfinibandNic-status*"
                RemoteCopy -downloadFrom $ServerVMData.PublicIP -port $ServerVMData.SSHPort -username "root" `
                    -password $password -download -downloadTo $LogDir -files "/root/IMB-*"
                RemoteCopy -downloadFrom $ServerVMData.PublicIP -port $ServerVMData.SSHPort -username "root" `
                    -password $password -download -downloadTo $LogDir -files "/root/kernel-logs-*"
                RemoteCopy -downloadFrom $ServerVMData.PublicIP -port $ServerVMData.SSHPort -username "root" `
                    -password $password -download -downloadTo $LogDir -files "/root/TestExecution.log"
                RemoteCopy -downloadFrom $ServerVMData.PublicIP -port $ServerVMData.SSHPort -username "root" `
                    -password $password -download -downloadTo $LogDir -files "/root/state.txt"
                $ConsoleOutput = ( Get-Content -Path "$LogDir\TestExecution.log" | Out-String )
                $FinalStatus = RunLinuxCmd -ip $ServerVMData.PublicIP -port $ServerVMData.SSHPort -username "root" `
                    -password $password -command "cat /root/state.txt"
                if ($Iteration -eq 1) {
                    $TempName = "FirstBoot"
                }
                else {
                    $TempName = "Reboot"
                }
                $out = mkdir -Path "$LogDir\InfiniBand-Verification-$Iteration-$TempName" -Force | Out-Null
                $out = Move-Item -Path "$LogDir\$InfinibandNic-status*" -Destination "$LogDir\InfiniBand-Verification-$Iteration-$TempName" | Out-Null
                $out = Move-Item -Path "$LogDir\IMB-*" -Destination "$LogDir\InfiniBand-Verification-$Iteration-$TempName" | Out-Null
                $out = Move-Item -Path "$LogDir\kernel-logs-*" -Destination "$LogDir\InfiniBand-Verification-$Iteration-$TempName" | Out-Null
                $out = Move-Item -Path "$LogDir\TestExecution.log" -Destination "$LogDir\InfiniBand-Verification-$Iteration-$TempName" | Out-Null
                $out = Move-Item -Path "$LogDir\state.txt" -Destination "$LogDir\InfiniBand-Verification-$Iteration-$TempName" | Out-Null

                #region Check if $InfinibandNic got IP address
                $logFileName = "$LogDir\InfiniBand-Verification-$Iteration-$TempName\TestExecution.log"
                $pattern = "INFINIBAND_VERIFICATION_SUCCESS_$InfinibandNic"
                LogMsg "Analysing $logFileName"
                $metaData = "InfiniBand-Verification-$Iteration-$TempName : $InfinibandNic IP"
                $SucessLogs = Select-String -Path $logFileName -Pattern $pattern
                if ($SucessLogs.Count -eq 1) {
                    $currentResult = "PASS"
                }
                else {
                    $currentResult = "FAIL"
                }
                LogMsg "$pattern : $currentResult"
                $resultArr += $currentResult
                $CurrentTestResult.TestSummary += CreateResultSummary -testResult $currentResult -metaData $metaData `
                    -checkValues "PASS,FAIL,ABORTED" -testName $CurrentTestData.testName
                #endregion

                #region Check MPI pingpong intranode tests
                $logFileName = "$LogDir\InfiniBand-Verification-$Iteration-$TempName\TestExecution.log"
                $pattern = "INFINIBAND_VERIFICATION_SUCCESS_MPI1_INTRANODE"
                LogMsg "Analysing $logFileName"
                $metaData = "InfiniBand-Verification-$Iteration-$TempName : PingPong Intranode"
                $SucessLogs = Select-String -Path $logFileName -Pattern $pattern
                if ($SucessLogs.Count -eq 1) {
                    $currentResult = "PASS"
                }
                else {
                    $currentResult = "FAIL"
                }
                LogMsg "$pattern : $currentResult"
                $resultArr += $currentResult
                $CurrentTestResult.TestSummary += CreateResultSummary -testResult $currentResult -metaData $metaData `
                    -checkValues "PASS,FAIL,ABORTED" -testName $CurrentTestData.testName
                #endregion

                #region Check MPI pingpong internode tests
                $logFileName = "$LogDir\InfiniBand-Verification-$Iteration-$TempName\TestExecution.log"
                $pattern = "INFINIBAND_VERIFICATION_SUCCESS_MPI1_INTERNODE"
                LogMsg "Analysing $logFileName"
                $metaData = "InfiniBand-Verification-$Iteration-$TempName : PingPong Internode"
                $SucessLogs = Select-String -Path $logFileName -Pattern $pattern
                if ($SucessLogs.Count -eq 1) {
                    $currentResult = "PASS"
                }
                else {
                    $currentResult = "FAIL"
                }
                LogMsg "$pattern : $currentResult"
                $resultArr += $currentResult
                $CurrentTestResult.TestSummary += CreateResultSummary -testResult $currentResult -metaData $metaData `
                -checkValues "PASS,FAIL,ABORTED" -testName $CurrentTestData.testName
                #endregion

                #region Check MPI1 all nodes tests
                if ( $ImbMpiTestIterations -ge 1) {
                    $logFileName = "$LogDir\InfiniBand-Verification-$Iteration-$TempName\TestExecution.log"
                    $pattern = "INFINIBAND_VERIFICATION_SUCCESS_MPI1_ALLNODES"
                    LogMsg "Analysing $logFileName"
                    $metaData = "InfiniBand-Verification-$Iteration-$TempName : IMB-MPI1"
                    $SucessLogs = Select-String -Path $logFileName -Pattern $pattern
                    if ($SucessLogs.Count -eq 1) {
                        $currentResult = "PASS"
                    }
                    else {
                        $currentResult = "FAIL"
                    }
                    LogMsg "$pattern : $currentResult"
                    $resultArr += $currentResult
                    $CurrentTestResult.TestSummary += CreateResultSummary -testResult $currentResult -metaData $metaData -checkValues "PASS,FAIL,ABORTED" -testName $CurrentTestData.testName
                }
                #endregion

                #region Check RMA all nodes tests
                if ( $ImbRmaTestIterations -ge 1) {
                    $logFileName = "$LogDir\InfiniBand-Verification-$Iteration-$TempName\TestExecution.log"
                    $pattern = "INFINIBAND_VERIFICATION_SUCCESS_RMA_ALLNODES"
                    LogMsg "Analysing $logFileName"
                    $metaData = "InfiniBand-Verification-$Iteration-$TempName : IMB-RMA"
                    $SucessLogs = Select-String -Path $logFileName -Pattern $pattern
                    if ($SucessLogs.Count -eq 1) {
                        $currentResult = "PASS"
                    }
                    else {
                        $currentResult = "FAIL"
                    }
                    LogMsg "$pattern : $currentResult"
                    $resultArr += $currentResult
                    $CurrentTestResult.TestSummary += CreateResultSummary -testResult $currentResult -metaData $metaData -checkValues "PASS,FAIL,ABORTED" -testName $CurrentTestData.testName
                }
                #endregion

                #region Check NBC all nodes tests
                if ( $ImbNbcTestIterations -ge 1) {
                    $logFileName = "$LogDir\InfiniBand-Verification-$Iteration-$TempName\TestExecution.log"
                    $pattern = "INFINIBAND_VERIFICATION_SUCCESS_RMA_ALLNODES"
                    LogMsg "Analysing $logFileName"
                    $metaData = "InfiniBand-Verification-$Iteration-$TempName : IMB-NBC"
                    $SucessLogs = Select-String -Path $logFileName -Pattern $pattern
                    if ($SucessLogs.Count -eq 1) {
                        $currentResult = "PASS"
                    }
                    else {
                        $currentResult = "FAIL"
                    }
                    LogMsg "$pattern : $currentResult"
                    $resultArr += $currentResult
                    $CurrentTestResult.TestSummary += CreateResultSummary -testResult $currentResult -metaData $metaData -checkValues "PASS,FAIL,ABORTED" -testName $CurrentTestData.testName
                }
                #endregion

                if ($FinalStatus -imatch "TestCompleted") {
                    LogMsg "Test finished successfully."
                    LogMsg $ConsoleOutput
                }
                else {
                    LogErr "Test failed."
                    LogErr $ConsoleOutput
                }
                #endregion
            }
            else {
                $FinalStatus = "TestFailed"
            }

            if ( $FinalStatus -imatch "TestFailed") {
                LogErr "Test failed. Last known status : $CurrentStatus."
                $testResult = "FAIL"
            }
            elseif ( $FinalStatus -imatch "TestAborted") {
                LogErr "Test ABORTED. Last known status : $CurrentStatus."
                $testResult = "ABORTED"
            }
            elseif ( $FinalStatus -imatch "TestCompleted") {
                LogMsg "Test Completed. Result : $FinalStatus."
                $testResult = "PASS"
                $TotalSuccessCount += 1
            }
            elseif ( $FinalStatus -imatch "TestRunning") {
                LogMsg "Powershell backgroud job for test is completed but VM is reporting that test is still running. Please check $LogDir\mdConsoleLogs.txt"
                LogMsg "Contests of state.txt : $FinalStatus"
                $testResult = "FAIL"
            }
            LogMsg "**********************************************"
            if ($RemainingRebootIterations -gt 0) {
                if ($testResult -eq "PASS") {
                    $RestartStatus = RestartAllDeployments -AllVMData $AllVMData
                    $RemainingRebootIterations -= 1
                }
                else {
                    LogErr "Stopping the test due to failures."
                }
            }
        }
        while (($ExpectedSuccessCount -ne $Iteration) -and ($RestartStatus -eq "True") `
        -and ($testResult -eq "PASS"))
        if ( $ExpectedSuccessCount -eq $TotalSuccessCount ) {
            $testResult = "PASS"
        }
        else {
            $testResult = "FAIL"
        }
        LogMsg "Test result : $testResult"
        LogMsg "Test Completed"
    }
    catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    }
    Finally {
        if (!$testResult) {
            $testResult = "ABORTED"
        }
        $resultArr += $testResult
    }
    $CurrentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}

Main