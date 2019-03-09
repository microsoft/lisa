# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
param(
        [String] $TestParams,
        [object] $AllVmData,
        [object] $CurrentTestData,
        [object] $TestProvider
)
$ErrorActionPreference = "Stop"

Function Install-LIS ($LISTarballUrl, $allVMData) {
    # Removing LISISO folder to avoid conflicts
    Run-LinuxCmd -username "root" -password $password -ip $allVMData.PublicIP -port $allVMData.SSHPort -command "rm -rf LISISO build-CustomLIS.txt"
    $LISInstallStatus = Install-CustomLIS -CustomLIS $LISTarballUrl -allVMData $allVMData -customLISBranch $customLISBranch -RestartAfterUpgrade -TestProvider $TestProvider
    if (-not $LISInstallStatus) {
        Write-LogErr "Custom LIS installation FAILED. Aborting tests."
        return $false
    }
    return $true
}

Function Upgrade-LIS ($LISTarballUrlOld, $LISTarballUrlCurrent, $allVMData , $TestProvider, [switch]$RestartAfterUpgrade) {
    try {
        Write-LogInfo "Upgrading LIS"
        $OldLISInstallStatus=Install-LIS -LISTarballUrl $LISTarballUrlOld -allVMData $AllVMData
        if (-not $OldLISInstallStatus[-1]) {
            Write-LogErr "OLD LIS installation FAILED. Aborting tests."
            return $false
        }
        $OldlisVersion = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "modinfo hv_vmbus"
        Write-LogInfo "LIS version with previous LIS drivers: $OldlisVersion"
        Write-LogInfo "Ugrading LIS to $LISTarballUrlCurrent"
        $CurrentLISExtractCommand = "rm -rf LISISO^wget $($LISTarballUrlCurrent)^tar -xzf $($LISTarballUrlCurrent | Split-Path -Leaf)^cp -ar LISISO/* ."
        $LISExtractCommands = $CurrentLISExtractCommand.Split("^")
        foreach ( $LISExtractCommand in $LISExtractCommands ) {
            Run-LinuxCmd -username "root" -password $password -ip $allVMData.PublicIP -port $allVMData.SSHPort -command $LISExtractCommand
        }
        $UpgradelLISConsoleOutput=Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "./upgrade.sh"
        Write-LogInfo $UpgradelLISConsoleOutput
        if ($UpgradelLISConsoleOutput -imatch "is already installed") {
            Write-LogInfo "Latest LIS version is already installed."
            return $true
        }
        else {
            if ($UpgradelLISConsoleOutput -imatch "error" -or $UpgradelLISConsoleOutput -imatch "warning" -or $UpgradelLISConsoleOutput -imatch "abort") {
                Write-LogErr "Latest LIS install is failed due found errors or warnings or aborted."
                return $false
            }
            if ( $RestartAfterUpgrade ) {
                Write-LogInfo "Now restarting VMs..."
                if ( $TestProvider.RestartAllDeployments($allVMData) ) {
                    $upgradedlisVersion = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "modinfo hv_vmbus"
                    if ($OldlisVersion -ne $upgradedlisVersion) {
                        Write-LogInfo "LIS upgraded to `"$LISTarballUrlCurrent`" successfully"
                        Write-LogInfo "Old lis: $OldlisVersion"
                        Write-LogInfo "New lis: $upgradedlisVersion"
                        Add-Content -Value "Old lis: $OldlisVersion" -Path ".\Report\AdditionalInfo-$TestID.html" -Force
                        Add-Content -Value "New lis: $upgradedlisVersion" -Path ".\Report\AdditionalInfo-$TestID.html" -Force
                        return $true
                    }
                    else {
                        Write-LogErr "LIS upgradation failed"
                        Add-Content -Value "Old lis: $OldlisVersion" -Path ".\Report\AdditionalInfo-$TestID.html" -Force
                        Add-Content -Value "New lis: $upgradedlisVersion" -Path ".\Report\AdditionalInfo-$TestID.html" -Force
                        return $false
                    }
                }
                else {
                    Write-LogErr "Failed while restarting VM"
                    return $false
                }
            }
        }
    }
    catch {
        Write-LogErr "Exception in Upgrade-LIS."
        return $false
    }
}

Function Downgrade-LIS ($LISTarballUrlOld, $LISTarballUrlCurrent, $allVMData , $TestProvider) {
    try {
        $LIS_version_before_downgrade = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "modinfo hv_vmbus"
        Write-LogInfo "LIS version before Downgrade: $LIS_version_before_downgrade"
        $UninstallLISStatus=Uninstall-LIS -LISTarballUrlCurrent $LISTarballUrlCurrent -allVMData $AllVMData -TestProvider $TestProvider
        if (-not $UninstallLISStatus) {
            return $false
        }
        Write-LogInfo "Downgrade to OLD LIS : $LISTarballUrlOld"
        $OLDLisInstallStatus=Install-LIS -LISTarballUrl $LISTarballUrlOld -allVMData $AllVMData
        if (-not $OLDLisInstallStatus[-1]) {
            return $true
        }
        $LIS_version_after_downgraded = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "modinfo hv_vmbus"
        Write-LogInfo "LIS version after Downgrade: $LIS_version_after_downgraded"
        if ( $LIS_version_before_downgrade -ne $LIS_version_after_downgraded) {
            Write-LogInfo "Downgraded LIS Successfully"
            return $true
        }
        else {
            Write-LogErr "LIS version has not changed after downgrading"
            return $false
        }
    }
    catch {
        Write-LogErr "Exception in Downgrade-LIS."
        return $false
    }
}

Function Uninstall-LIS ( $LISTarballUrlCurrent, $allVMData , $TestProvider) {
    try {
        $LIS_version_before_uninstalling = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "modinfo hv_vmbus"
        Write-LogInfo "LIS version before uninstalling: $LIS_version_before_uninstalling"
        Write-LogInfo "Uninstalling LIS $LISTarballUrlCurrent"
        $CurrentLISExtractCommand = "rm  -rf LISISO^wget $($LISTarballUrlCurrent)^tar -xzf $($LISTarballUrlCurrent | Split-Path -Leaf)^cp -ar LISISO/* ."
        $LISExtractCommands = $CurrentLISExtractCommand.Split("^")
        foreach ( $LISExtractCommand in $LISExtractCommands ) {
            Run-LinuxCmd -username "root" -password $password -ip $allVMData.PublicIP -port $allVMData.SSHPort -command $LISExtractCommand
        }
        $UninstallLISConsoleOutput=Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "./uninstall.sh"
        Write-LogInfo $UninstallLISConsoleOutput
        if ($UninstallLISConsoleOutput -imatch "No LIS RPM's are present") {
            Write-LogInfo "LIS already uninstalled and it has built-in LIS drivers"
            return $true
        }
        else {
            if ($UninstallLISConsoleOutput -imatch "error" -or $UninstallLISConsoleOutput -imatch "warning" -or $UninstallLISConsoleOutput -imatch "abort") {
                Write-LogErr "Latest LIS install is failed due to found errors or warnings or aborted."
                return $false
            }
            else {
                if ( $TestProvider.RestartAllDeployments($allVMData) ) {
                    $LIS_version_after_uninstalling = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "modinfo hv_vmbus"
                    Write-LogInfo "LIS version after uninstalling: $LIS_version_after_uninstalling"
                    if ( $LIS_version_after_uninstalling -ne $LIS_version_before_uninstalling) {
                        Write-LogInfo "Successfully uninstalled $LISTarballUrlCurrent."
                        return $true
                    }
                    else {
                        Write-LogErr "Uninstall LIS failed"
                        return $false
                    }
                }
                else {
                    Write-LogErr "Failed while restarting VM"
                    return $false
                }
            }
        }
    }
    catch {
        Write-LogErr "Exception in Uninstall-LIS."
        return $false
    }
}

Function Upgrade-Kernel ($allVMData, $TestProvider, [switch]$RestartAfterUpgrade){
    try {
        Write-LogInfo "Upgrading kernel"
        Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "yum install -y kernel >> ~/kernel_install_scenario.log" -runMaxAllowedTime 20000
        # Checking if latest kernel is already installed
        $sts = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "cat kernel_install_scenario.log | grep 'already installed'" -ignoreLinuxExitCode:$true
        if ($sts) {
            Write-LogErr "VM has latest kernel already installed, So LIS scenario test is skipped.."
            return $false
        }
        Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "echo `"---kernel version before upgrade:`$(uname -r)---`" >> kernel_install_scenario.log"
        Write-LogInfo "Check if kernel is upgraded or not"
        $upgraded_kernel = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "cat kernel_install_scenario.log | grep 'Installed' -A 1 | tail -1 | cut -d \: -f 2"
        if ($upgraded_kernel) {
            Write-LogInfo "Kernel version after upgrade: ${upgraded_kernel}"
        }
        else {
            Write-LogInfo "Warn: Cannot find upgraded kernel version"
        }
        $kernel_version_before_upgrade = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "uname -r"
        Write-LogInfo "kernel version before upgrade: $kernel_version_before_upgrade"
        Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "sync"
        Write-LogInfo "Getting kernel upgrade status"
        $kernelUpgradeStatus=Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "cat kernel_install_scenario.log | grep 'Complete!'"
        if (-not $kernelUpgradeStatus) {
            Write-LogErr "Kernel upgrade failed"
            return $false
        }
        else {
            Write-LogInfo "Successfully upgraded kernel"
            if ($RestartAfterUpgrade) {
                if ($TestProvider.RestartAllDeployments($allVMData)) {
                    Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "echo `"---kernel version after upgrade:`$(uname -r)---`" >> kernel_install_scenario.log"
                }
                else {
                    Write-LogErr "Failed while restarting VM"
                    return $false
                }
            }
        }
        Copy-RemoteFiles -download -downloadFrom $allVMData.PublicIP -port $allVMData.SSHPort -files "kernel_install_scenario.log" -username "root" -password $password -downloadTo $LogDir
        return $true
    }
    catch {
        Write-LogErr "Exception in Upgrade-Kernel"
        return $false
    }
}

### Scenarios ###############################

# Scenario Information : Installs the Current LIS using given LIS source file (.tar.gz )
# Expected result : Verify that Current LIS Installs successfully
Function  Install-LIS-Scenario-1 ($PreviousTestResult, $LISTarballUrlOld, $LISTarballUrlCurrent) {
    if ($PreviousTestResult -eq "PASS") {
        $LISInstallStatus=Install-LIS -LISTarballUrl $LISTarballUrlCurrent -allVMData $AllVMData
        if (-not $LISInstallStatus[-1]) {
            return "FAIL"
        }
        if ($TestPlatform -eq "HyperV") {
            #Take Snapshot with name
            Create-HyperVCheckpoint -VMData $AllVMData -CheckpointName "CURRENT_LIS_INSTALLED"
        }
        return "PASS"
    }
    else {
        return "ABORTED"
    }
}

# Scenario Information : Upgrade to current LIS
# (Installs Previous LIS version -> Upgrade to Current LIS version)
# Expected result : Verify that LIS has upgraded to Current LIS successfully
Function Install-LIS-Scenario-2 ($PreviousTestResult, $LISTarballUrlOld, $LISTarballUrlCurrent) {
    if ($PreviousTestResult -eq "PASS") {
        $UpgradeStatus=Upgrade-LIS -LISTarballUrlOld $LISTarballUrlOld -LISTarballUrlCurrent $LISTarballUrlCurrent -allVMData $AllVMData -TestProvider $TestProvider -RestartAfterUpgrade
        if (-not $UpgradeStatus) {
            return "FAIL"
        }
        if ($TestPlatform -eq "HyperV") {
            #Take Snapshot with name
            Create-HyperVCheckpoint -VMData $AllVMData -CheckpointName "CURRENT_LIS_UPGRADED"
        }
        return "PASS"
    }
    else {
        return "ABORTED"
    }
}

# Scenario Information : Downgrade LIS to old LIS.
# (Installs Previous LIS version -> Upgrade to Current LIS version -> UnInstall to Current LIS version -> ReInstall Previous LIS version)
# Expected result : Verify that LIS has Downgraded to old LIS successfully
Function Install-LIS-Scenario-3 ($PreviousTestResult, $LISTarballUrlOld, $LISTarballUrlCurrent) {
    if ($PreviousTestResult -eq "PASS") {
        if ($TestPlatform -eq "HyperV") {
            Apply-HyperVCheckpoint -VMData $AllVMData -CheckpointName "CURRENT_LIS_UPGRADED"
        }
        elseif ($TestPlatform -eq "Azure") {
            $UpgradeStatus=Upgrade-LIS -LISTarballUrlOld $LISTarballUrlOld -LISTarballUrlCurrent $LISTarballUrlCurrent -allVMData $AllVMData -TestProvider $TestProvider -RestartAfterUpgrade
            if (-not $UpgradeStatus) {
                return "FAIL"
            }
        }
        $DowgradeStatus=Downgrade-LIS -LISTarballUrlOld $LISTarballUrlOld -LISTarballUrlCurrent $LISTarballUrlCurrent -allVMData $AllVMData -TestProvider $TestProvider
        if (-not $DowgradeStatus) {
            return "FAIL"
        }
        return "PASS"
    }
    else {
        return "ABORTED"
    }
}

#Scenario Information : Upgrade kernel without reboot and install Current LIS
#Expected result : Verify that LIS should abort install (LIS negative scenario test)
Function Install-LIS-Scenario-4 ($PreviousTestResult, $LISTarballUrlOld, $LISTarballUrlCurrent) {
    if ($PreviousTestResult -eq "PASS") {
        $UpgradekernelStatus=Upgrade-Kernel -allVMData $AllVMData -TestProvider $TestProvider
        if (-not $UpgradekernelStatus) {
            return "FAIL"
        }
        $LISInstallStatus=Install-LIS -LISTarballUrl $LISTarballUrlCurrent -allVMData $AllVMData
        if ($LISInstallStatus -ne $false) {
            Write-LogErr "LIS installation should fail but succeded"
            return "FAIL"
        }
        Write-LogInfo "Installation failed as expected."
        return "PASS"
    }
    else {
        return "ABORTED"
    }
}
# Scenario Information : Installs Current LIS then upgrade kernel with reboot
# Expected result : Verify that LIS built-in drivers are detected after kernel upgrade
Function Install-LIS-Scenario-5 ($PreviousTestResult, $LISTarballUrlOld, $LISTarballUrlCurrent) {
    if ($PreviousTestResult -eq "PASS") {
        if ($TestPlatform -eq "HyperV") {
            Apply-HyperVCheckpoint -VMData $AllVMData -CheckpointName "CURRENT_LIS_INSTALLED"
        } elseif ($TestPlatform -eq "Azure") {
            $LISInstallStatus=Install-LIS -LISTarballUrl $LISTarballUrlCurrent -allVMData $AllVMData
            if (-not $LISInstallStatus[-1]) {
                return "FAIL"
            }
        }
        $LIS_version_before_upgrade_kernel = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "modinfo hv_vmbus"
        Write-LogInfo "LIS version before upgrading kernel: $LIS_version_before_upgrade_kernel"
        $UpgradekernelStatus=Upgrade-Kernel -allVMData $AllVMData -TestProvider $TestProvider -RestartAfterUpgrade
        if (-not $UpgradekernelStatus) {
            return "FAIL"
        }
        $LIS_version_after_upgrade_kernel = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "modinfo hv_vmbus"
        Write-LogInfo "LIS version after upgrading kernel: $LIS_version_after_upgrade_kernel"
        if ( $LIS_version_before_upgrade_kernel -ne $LIS_version_after_upgrade_kernel) {
            Write-LogInfo "LIS built-in drivers are detected.. after kernel upgrade."
        }
        else {
            Write-LogErr "New LIS version NOT detected"
            return "FAIL"
        }
        return "PASS"
    }
    else {
        return "ABORTED"
    }
}

# Scenario Information : Upgrade LIS, upgrade kernel.
# (Install Previous LIS -> Upgrade to Current LIS -> Upgrade Kernel with reboot)
# Expected result : Verify that LIS built-in drivers are detected after Kernel Upgrade
Function Install-LIS-Scenario-6 ($PreviousTestResult, $LISTarballUrlOld, $LISTarballUrlCurrent) {
    if ($PreviousTestResult -eq "PASS") {
        if ($TestPlatform -eq "HyperV") {
            Apply-HyperVCheckpoint -VMData $AllVMData -CheckpointName "CURRENT_LIS_UPGRADED"
        } elseif ($TestPlatform -eq "Azure") {
            $UpgradeStatus=Upgrade-LIS -LISTarballUrlOld $LISTarballUrlOld -LISTarballUrlCurrent $LISTarballUrlCurrent -allVMData $AllVMData -TestProvider $TestProvider -RestartAfterUpgrade
            if (-not $UpgradeStatus) {
                return "FAIL"
            }
        }
        $LIS_version_before_upgrade_kernel = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "modinfo hv_vmbus"
        Write-LogInfo "LIS version before upgrading kernel: $LIS_version_before_upgrade_kernel"
        $UpgradekernelStatus=Upgrade-Kernel -allVMData $AllVMData -TestProvider $TestProvider -RestartAfterUpgrade
        if (-not $UpgradekernelStatus) {
            return "FAIL"
        }
        $LIS_version_after_upgrade_kernel = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "modinfo hv_vmbus"
        Write-LogInfo "LIS version after upgrading kernel: $LIS_version_after_upgrade_kernel"
        if( $LIS_version_before_upgrade_kernel -ne $LIS_version_after_upgrade_kernel) {
            Write-LogInfo "LIS built-in drivers are detected.. after kernel upgrade."
        }
        else {
            Write-LogErr "New LIS version NOT detected"
            return "FAIL"
        }
        return "PASS"
    }
    else {
        return "ABORTED"
    }
}

# Scenario Information : Upgrade minor kernel, Upgrade LIS
# (Upgrade minor kernel -> Install Previous LIS -> Upgrade to Current LIS)
# If it's an Oracle distro, skip the test
# Expected result : Verify that LIS has upgraded to Current LIS successfully after kernel upgrade
Function Install-LIS-Scenario-7 ($PreviousTestResult, $LISTarballUrlOld, $LISTarballUrlCurrent) {
    if ($PreviousTestResult -eq "PASS") {
        $is_oracle = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "cat /etc/os-release | grep -i oracle" -ignoreLinuxExitCode:$true
        if ($is_oracle) {
            Write-LogErr "Skipped: Oracle not suported on this TC"
            return "ABORTED"
        }
        Write-LogInfo "Upgrading minor kernel"
        $kernel_version_before_upgrade = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "uname -r"
        Write-LogInfo "kernel version before upgrade: $kernel_version_before_upgrade"
        $UpgradeKernelConsoleOutput=Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username $user -password $password -command ". utils.sh && UpgradeMinorKernel" -runMaxAllowedTime 20000 -runAsSudo
        Write-LogInfo $UpgradeKernelConsoleOutput
        Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "sync"
        if ($TestProvider.RestartAllDeployments($allVMData)) {
            $kernel_version_after_upgrade = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "uname -r"
            Write-LogInfo "kernel version after upgrade: $kernel_version_after_upgrade"
            if ( $kernel_version_after_upgrade -eq $kernel_version_before_upgrade) {
                Write-LogErr "Failed to Upgrade Minor kernel"
                return "FAIL"
            }
            Write-LogInfo "Sucessfully Upgraded Minor Kernel"
            $UpgradeStatus=Upgrade-LIS -LISTarballUrlOld $LISTarballUrlOld -LISTarballUrlCurrent $LISTarballUrlCurrent -allVMData $AllVMData -TestProvider $TestProvider -RestartAfterUpgrade
            if (-not $UpgradeStatus) {
                return "FAIL"
            }
            return "PASS"
        }
        else {
            Write-LogErr "Failed while restarting VM"
            return "FAIL"
        }
    } else {
        return "ABORTED"
    }
}

# Scenario Information : Uninstall LIS.
# (Install Current LIS -> Uninstall LIS)
# Expected result : Verify that LIS Uninstalls successfully
Function Install-LIS-Scenario-8 ($PreviousTestResult, $LISTarballUrlOld, $LISTarballUrlCurrent) {
    if ($PreviousTestResult -eq "PASS") {
        if ($TestPlatform -eq "HyperV") {
            Apply-HyperVCheckpoint -VMData $AllVMData -CheckpointName "CURRENT_LIS_INSTALLED"
        } elseif ($TestPlatform -eq "Azure") {
            $LISInstallStatus=Install-LIS -LISTarballUrl $LISTarballUrlCurrent -allVMData $AllVMData
            if (-not $LISInstallStatus[-1]) {
                return "FAIL"
            }
        }
        $UninstallLISStatus=Uninstall-LIS -LISTarballUrlCurrent $LISTarballUrlCurrent -allVMData $AllVMData -TestProvider $TestProvider
        if (-not $UninstallLISStatus) {
            return "FAIL"
        }
        return "PASS"
    } else {
        return "ABORTED"
    }
}

Function Main {
    $currentTestResult = Create-TestResultObject
    $resultArr = @()
    try {
        $PreviousTestResult="PASS"
        foreach ($param in $CurrentTestData.TestParameters.param) {
            if ($param -imatch "LIS_TARBALL_URL_CURRENT") {
                $LISTarballUrlCurrent = $param.Replace("LIS_TARBALL_URL_CURRENT=","")
            }
            if ($param -imatch "LIS_TARBALL_URL_OLD") {
                $LISTarballUrlOld = $param.Replace("LIS_TARBALL_URL_OLD=","")
            }
        }
        #PROVISION VMS FOR LISA WILL ENABLE ROOT USER AND WILL MAKE ENABLE PASSWORDLESS AUTHENTICATION ACROSS ALL VMS IN SAME HOSTED SERVICE.
        Provision-VMsForLisa -allVMData $AllVMData -installPackagesOnRoleNames "none"
        #endregion
        foreach ($Scenario in $CurrentTestData.TestParameters.param) {
            switch ($Scenario) {
                "Install-LIS-Scenario-1" {
                    $testResult = Install-LIS-Scenario-1 -PreviousTestResult $PreviousTestResult -LISTarballUrlOld $LISTarballUrlOld -LISTarballUrlCurrent $LISTarballUrlCurrent
                    $CurrentTestResult.TestSummary += New-ResultSummary -testResult $testResult -metaData "$Scenario" `
                    -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                    break;
                }
                "Install-LIS-Scenario-2" {
                    $testResult = Install-LIS-Scenario-2 -PreviousTestResult $PreviousTestResult -LISTarballUrlOld $LISTarballUrlOld -LISTarballUrlCurrent $LISTarballUrlCurrent
                    $CurrentTestResult.TestSummary += New-ResultSummary -testResult $testResult -metaData "$Scenario" `
                    -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                    break;
                }
                "Install-LIS-Scenario-3" {
                    $testResult = Install-LIS-Scenario-3 -PreviousTestResult $PreviousTestResult -LISTarballUrlOld $LISTarballUrlOld -LISTarballUrlCurrent $LISTarballUrlCurrent
                    $CurrentTestResult.TestSummary += New-ResultSummary -testResult $testResult -metaData "$Scenario" `
                    -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                    break;
                }
                "Install-LIS-Scenario-4" {
                    $testResult = Install-LIS-Scenario-4 -PreviousTestResult $PreviousTestResult -LISTarballUrlOld $LISTarballUrlOld -LISTarballUrlCurrent $LISTarballUrlCurrent
                    $CurrentTestResult.TestSummary += New-ResultSummary -testResult $testResult -metaData "$Scenario" `
                    -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                    break;
                }
                "Install-LIS-Scenario-5" {
                    $testResult = Install-LIS-Scenario-5 -PreviousTestResult $PreviousTestResult -LISTarballUrlOld $LISTarballUrlOld -LISTarballUrlCurrent $LISTarballUrlCurrent
                    $CurrentTestResult.TestSummary += New-ResultSummary -testResult $testResult -metaData "$Scenario" `
                    -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                    break;
                }
                "Install-LIS-Scenario-6" {
                    $testResult = Install-LIS-Scenario-6 -PreviousTestResult $PreviousTestResult -LISTarballUrlOld $LISTarballUrlOld -LISTarballUrlCurrent $LISTarballUrlCurrent
                    $CurrentTestResult.TestSummary += New-ResultSummary -testResult $testResult -metaData "$Scenario" `
                    -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                    break;
                }
                "Install-LIS-Scenario-7" {
                    $testResult = Install-LIS-Scenario-7 -PreviousTestResult $PreviousTestResult -LISTarballUrlOld $LISTarballUrlOld -LISTarballUrlCurrent $LISTarballUrlCurrent
                    $CurrentTestResult.TestSummary += New-ResultSummary -testResult $testResult -metaData "$Scenario" `
                    -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                    break;
                }
                "Install-LIS-Scenario-8" {
                    $testResult = Install-LIS-Scenario-8 -PreviousTestResult $PreviousTestResult -LISTarballUrlOld $LISTarballUrlOld -LISTarballUrlCurrent $LISTarballUrlCurrent
                    $CurrentTestResult.TestSummary += New-ResultSummary -testResult $testResult -metaData "$Scenario" `
                    -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                    break;
                }
                default {
                    #Do nothing.
                }
            }
            $PreviousTestResult = $testResult
        }
    }
    catch {
        $ErrorMessage = $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    }
    finally {
        if (!$testResult) {
            $testResult = "ABORTED"
            $CurrentTestResult.TestSummary += New-ResultSummary -testResult $testResult -metaData "LIS-INSTALL-SCENARIOS" `
                -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
        }
        $resultArr += $testResult
    }
    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult
}

Main
