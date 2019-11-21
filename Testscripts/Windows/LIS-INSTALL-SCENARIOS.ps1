# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
param(
        [String] $TestParams,
        [object] $AllVmData,
        [object] $CurrentTestData,
        [object] $TestProvider
)
$ErrorActionPreference = "Stop"
[xml]$configfile = Get-Content ".\XML\Other\ignorable-test-warnings.xml"
$IgnorableWarnings = @($configfile.messages.warnings.keywords.Trim())

# Minor version like 4.3.3.1 doesn't require source code change so the modinfo version will be same as the major version like 4.3.3
# Hence we are comparing to check whether it is a minor LIS version upgrade
Function Check-MinorLISVersionUpgrade ($LISTarballUrlOld, $LISTarballUrlCurrent) {
    $oldversion = (($LISTarballUrlOld -split ".*rpms?-")[1] -split ".tar.gz" -split "-")[0]
    $oldversion = $oldversion.Split(".")
    Write-LogInfo "LISTarballUrlOld version - $oldversion"
    $currentversion = (($LISTarballUrlCurrent -split ".*rpms?-")[1] -split ".tar.gz" -split "-")[0]
    $currentversion = $currentversion.Split(".")
    Write-LogInfo "LISTarballUrlCurrent version - $currentversion"
    $minorupgrade = $true
    for ($index = 0; $index -lt 3; $index++) {
        if ($oldversion[$index] -ne $currentversion[$index]) {
            $minorupgrade = $false
            break
        }
    }
    return $minorupgrade
}

Function Check-Modules() {
    Write-LogInfo "Check if module are loaded after LIS installation"
    $remoteScript = "LIS-MODULES-CHECK.py"
    # Run the remote script
    Run-LinuxCmd -username $user -password $password -ip $allVMData.PublicIP -port $allVMData.SSHPort -command "python ${remoteScript}" -runAsSudo
    Run-LinuxCmd -username $user -password $password -ip $allVMData.PublicIP -port $allVMData.SSHPort -command "mv Runtime.log ${remoteScript}.log" -runAsSudo
    Copy-RemoteFiles -download -downloadFrom $allVMData.PublicIP -files "/home/$user/state.txt,/home/${user}/${remoteScript}.log" `
        -downloadTo $LogDir -port $allVMData.SSHPort -username $user -password $password
    $testStatus = Get-Content $LogDir\state.txt
    if ($testStatus -ne "TestCompleted") {
        Write-LogErr "Running $remoteScript script failed on VM!"
        return $false
    }
    Write-LogInfo "Check if module version matches with the expected LIS version"
    $remoteScript = "VERIFY-LIS-MODULES-VERSION.sh"
    # Run the remote script
    $sts = Invoke-RemoteScriptAndCheckStateFile $remoteScript $user $password $allVMData.PublicIP $allVMData.SSHPort -runAsSudo
    if (-not $sts[-1]) {
        Write-LogErr "Running $remoteScript script failed on VM!"
        return $false
    }
    return $true
}


Function Install-LIS ($LISTarballUrl, $allVMData) {
    # Removing LISISO folder to avoid conflicts
    Run-LinuxCmd -username "root" -password $password -ip $allVMData.PublicIP -port $allVMData.SSHPort -command "rm -rf LISISO build-CustomLIS.txt"
    $LISInstallStatus = Install-CustomLIS -CustomLIS $LISTarballUrl -allVMData $allVMData -customLISBranch $customLISBranch -RestartAfterUpgrade -TestProvider $TestProvider
    if (-not $LISInstallStatus) {
        Write-LogErr "Custom LIS installation FAILED. Aborting tests."
        return $false
    }
    $sts = Check-Modules
    if (-not $sts[-1]) {
        Write-LogErr "Failed due to either modules not loaded or version mismatch"
        return $false
    }
    return $true
}

Function Upgrade-LIS ($LISTarballUrlOld, $LISTarballUrlCurrent, $allVMData , $TestProvider, [switch]$RestartAfterUpgrade) {
    try {
        Write-LogInfo "Upgrading LIS"
        $OldLISInstallStatus = Install-LIS -LISTarballUrl $LISTarballUrlOld -allVMData $AllVMData
        if (-not $OldLISInstallStatus[-1]) {
            Write-LogErr "OLD LIS installation FAILED. Aborting tests."
            return $false
        }
        $OldLISVersion = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "modinfo hv_vmbus"
        $OldLISmoduleVersion = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "modinfo hv_vmbus|grep -w `"version:`""
        Write-LogInfo "LIS version with previous LIS drivers: $OldLISVersion"
        Write-LogInfo "Upgrading LIS to $LISTarballUrlCurrent"
        $CurrentLISExtractCommand = "rm -rf LISISO^wget $($LISTarballUrlCurrent)^tar -xzf $($LISTarballUrlCurrent | Split-Path -Leaf)^cp -ar LISISO/* ."
        $LISExtractCommands = $CurrentLISExtractCommand.Split("^")
        foreach ($LISExtractCommand in $LISExtractCommands) {
            Run-LinuxCmd -username "root" -password $password -ip $allVMData.PublicIP -port $allVMData.SSHPort -command $LISExtractCommand -runMaxAllowedTime 2000 -maxRetryCount 3
        }
        $UpgradelLISConsoleOutput = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "./upgrade.sh"
        Write-LogInfo $UpgradelLISConsoleOutput
        if ($UpgradelLISConsoleOutput -imatch "is already installed") {
            Write-LogInfo "Latest LIS version is already installed."
            return $true
        } else {
            if ($UpgradelLISConsoleOutput -imatch "error" -or ($UpgradelLISConsoleOutput -imatch "warning" -and ($null -eq ($IgnorableWarnings | ? {$UpgradelLISConsoleOutput -match $_ }))) -or $UpgradelLISConsoleOutput -imatch "abort") {
                Write-LogErr "Latest LIS install is failed due to found errors or warnings or aborted."
                return $false
            }
            if ($RestartAfterUpgrade) {
                Write-LogInfo "Now restarting VMs..."
                if ($TestProvider.RestartAllDeployments($allVMData)) {
                    $upgradedLISVersion = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "modinfo hv_vmbus"
                    $upgradedLISmoduleVersion = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "modinfo hv_vmbus|grep -w `"version:`""
                    if (Check-MinorLISVersionUpgrade -LISTarballUrlOld $LISTarballUrlOld -LISTarballUrlCurrent $LISTarballUrlCurrent) {
                        if ($OldLISmoduleVersion -eq $upgradedLISmoduleVersion) {
                            Write-LogInfo "LIS upgraded to `"$LISTarballUrlCurrent`" successfully"
                            Write-LogInfo "Old LIS: $OldLISVersion"
                            Write-LogInfo "New LIS: $upgradedLISVersion"
                            Add-Content -Value "Old LIS: $OldLISVersion" -Path ".\Report\AdditionalInfo-$TestID.html" -Force
                            Add-Content -Value "New LIS: $upgradedLISVersion" -Path ".\Report\AdditionalInfo-$TestID.html" -Force
                            $sts = Check-Modules
                            if (-not $sts[-1]) {
                                Write-LogErr "Failed due to either modules not loaded or version mismatch"
                                return $false
                            }
                            return $true
                        } else {
                            Write-LogErr "LIS upgradation failed"
                            Write-LogInfo $OldLISVersion
                            Write-LogInfo $upgradedLISVersion
                            Add-Content -Value "Old LIS: $OldLISVersion" -Path ".\Report\AdditionalInfo-$TestID.html" -Force
                            Add-Content -Value "New LIS: $upgradedLISVersion" -Path ".\Report\AdditionalInfo-$TestID.html" -Force
                            return $false
                        }
                    } else {
                        if ($OldLISVersion -ne $upgradedLISVersion) {
                            Write-LogInfo "LIS upgraded to `"$LISTarballUrlCurrent`" successfully"
                            Write-LogInfo "Old LIS: $OldLISVersion"
                            Write-LogInfo "New LIS: $upgradedLISVersion"
                            Add-Content -Value "Old LIS: $OldLISVersion" -Path ".\Report\AdditionalInfo-$TestID.html" -Force
                            Add-Content -Value "New LIS: $upgradedLISVersion" -Path ".\Report\AdditionalInfo-$TestID.html" -Force
                            $sts = Check-Modules
                            if (-not $sts[-1]) {
                                Write-LogErr "Failed due to either modules not loaded or version mismatch"
                                return $false
                            }
                            return $true
                        } else {
                            Write-LogErr "LIS upgradation failed inside else"
                            Write-LogInfo $OldLISVersion
                            Write-LogInfo $upgradedLISVersion
                            Add-Content -Value "Old LIS: $OldLISVersion" -Path ".\Report\AdditionalInfo-$TestID.html" -Force
                            Add-Content -Value "New LIS: $upgradedLISVersion" -Path ".\Report\AdditionalInfo-$TestID.html" -Force
                            return $false
                        }
                    }
                } else {
                    Write-LogErr "Failed while restarting VM"
                    return $false
                }
            }
        }
    } catch {
        Write-LogErr "Exception in Upgrade-LIS."
        return $false
    }
}

Function Downgrade-LIS ($LISTarballUrlOld, $LISTarballUrlCurrent, $allVMData , $TestProvider) {
    try {
        $LIS_version_before_downgrade = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "modinfo hv_vmbus"
        $LIS_module_version_before_downgrade = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "modinfo hv_vmbus|grep -w `"version:`""
        Write-LogInfo "LIS version before Downgrade: $LIS_version_before_downgrade"
        $UninstallLISStatus = Uninstall-LIS -LISTarballUrlCurrent $LISTarballUrlCurrent -allVMData $AllVMData -TestProvider $TestProvider
        if (-not $UninstallLISStatus[-1]) {
            return $false
        }
        Write-LogInfo "Downgrade to OLD LIS : $LISTarballUrlOld"
        $OLDLISInstallStatus = Install-LIS -LISTarballUrl $LISTarballUrlOld -allVMData $AllVMData
        if (-not $OLDLISInstallStatus[-1]) {
            return $false
        }
        $LIS_version_after_downgraded = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "modinfo hv_vmbus"
        $LIS_module_version_after_downgraded = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "modinfo hv_vmbus|grep -w `"version:`""
        Write-LogInfo "LIS version after Downgrade: $LIS_version_after_downgraded"
        if (Check-MinorLISVersionUpgrade -LISTarballUrlOld $LISTarballUrlOld -LISTarballUrlCurrent $LISTarballUrlCurrent) {
            if ($LIS_module_version_before_downgrade -eq $LIS_module_version_after_downgraded) {
                Write-LogInfo "Downgraded LIS Successfully"
                return $true
            } else {
                Write-LogErr "LIS version has changed after downgrading"
                return $false
            }
        } else {
            if ($LIS_version_before_downgrade -ne $LIS_version_after_downgraded) {
                Write-LogInfo "Downgraded LIS Successfully"
                return $true
            } else {
                Write-LogErr "LIS version has not changed after downgrading"
                return $false
            }
        }
    } catch {
        Write-LogErr "Exception in Downgrade-LIS."
        return $false
    }
}

Function Uninstall-LIS ($LISTarballUrlCurrent, $allVMData , $TestProvider) {
    try {
        $LIS_version_before_uninstalling = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "modinfo hv_vmbus"
        Write-LogInfo "LIS version before uninstalling: $LIS_version_before_uninstalling"
        Write-LogInfo "Uninstalling LIS $LISTarballUrlCurrent"
        $CurrentLISExtractCommand = "rm  -rf LISISO^wget $($LISTarballUrlCurrent)^tar -xzf $($LISTarballUrlCurrent | Split-Path -Leaf)^cp -ar LISISO/* ."
        $LISExtractCommands = $CurrentLISExtractCommand.Split("^")
        foreach ($LISExtractCommand in $LISExtractCommands) {
            Run-LinuxCmd -username "root" -password $password -ip $allVMData.PublicIP -port $allVMData.SSHPort -command $LISExtractCommand -runMaxAllowedTime 2000 -maxRetryCount 3
        }
        $UninstallLISConsoleOutput = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "./uninstall.sh"
        Write-LogInfo $UninstallLISConsoleOutput
        if ($UninstallLISConsoleOutput -imatch "No LIS RPM's are present") {
            Write-LogInfo "LIS already uninstalled and it has built-in LIS drivers"
            return $true
        } else {
            if ($UninstallLISConsoleOutput -imatch "error" -or ($UninstallLISConsoleOutput -imatch "warning" -and ($null -eq ($IgnorableWarnings | ? {$UninstallLISConsoleOutput -match $_ }))) -or $UninstallLISConsoleOutput -imatch "abort") {
                Write-LogErr "Latest LIS install is failed due to found errors or warnings or aborted."
                return $false
            } else {
                if ($TestProvider.RestartAllDeployments($allVMData)) {
                    $LIS_version_after_uninstalling = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "modinfo hv_vmbus"
                    Write-LogInfo "LIS version after uninstalling: $LIS_version_after_uninstalling"
                    if ($LIS_version_after_uninstalling -ne $LIS_version_before_uninstalling) {
                        Write-LogInfo "Successfully uninstalled $LISTarballUrlCurrent."
                        return $true
                    } else {
                        Write-LogErr "Uninstall LIS failed"
                        return $false
                    }
                } else {
                    Write-LogErr "Failed while restarting VM"
                    return $false
                }
            }
        }
    } catch {
        Write-LogErr "Exception in Uninstall-LIS."
        return $false
    }
}

Function Upgrade-Kernel ($allVMData, $TestProvider, [switch]$RestartAfterUpgrade){
    try {
        Write-LogInfo "Upgrading kernel"
        Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password `
            -command "yum install -y kernel >> ~/kernel_install_scenario.log" -runMaxAllowedTime 2000 -maxRetryCount 3
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
        } else {
            Write-LogInfo "Warn: Cannot find upgraded kernel version"
        }
        $kernel_version_before_upgrade = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "uname -r"
        Write-LogInfo "kernel version before upgrade: $kernel_version_before_upgrade"
        Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "sync"
        Write-LogInfo "Getting kernel upgrade status"
        $kernelUpgradeStatus = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "cat kernel_install_scenario.log | grep 'Complete!'"
        if (-not $kernelUpgradeStatus) {
            Write-LogErr "Kernel upgrade failed"
            return $false
        } else {
            Write-LogInfo "Successfully upgraded kernel"
            if ($RestartAfterUpgrade) {
                if ($TestProvider.RestartAllDeployments($allVMData)) {
                    Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "echo `"---kernel version after upgrade:`$(uname -r)---`" >> kernel_install_scenario.log"
                } else {
                    Write-LogErr "Failed while restarting VM"
                    return $false
                }
            }
        }
        Copy-RemoteFiles -download -downloadFrom $allVMData.PublicIP -port $allVMData.SSHPort -files "kernel_install_scenario.log" -username "root" -password $password -downloadTo $LogDir
        return $true
    } catch {
        Write-LogErr "Exception in Upgrade-Kernel"
        return $false
    }
}

### Scenarios ###############################

# Scenario Information : Installs the Current LIS using given LIS source file (.tar.gz)
# Expected result : Verify that Current LIS Installs successfully
Function  Install-LIS-Scenario-1 ($PreviousTestResult, $LISTarballUrlOld, $LISTarballUrlCurrent) {
    if ($PreviousTestResult -eq "PASS") {
        $LISInstallStatus = Install-LIS -LISTarballUrl $LISTarballUrlCurrent -allVMData $AllVMData
        if (-not $LISInstallStatus[-1]) {
            $sts = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "cat build-CustomLIS.txt | grep -E 'Unsupported kernel version|Kernel version not supported'" -ignoreLinuxExitCode:$true
            if ($sts) {
                Write-LogInfo "Unsupported kernel version, skip test.."
                return "SKIPPED"
            } else {
                return "FAIL"
            }
        }
        if ($TestPlatform -eq "HyperV") {
            #Take Snapshot with name
            Create-HyperVCheckpoint -VMData $AllVMData -CheckpointName "CURRENT_LIS_INSTALLED"
        }
        $global:NeedUninstallLIS = $true
        Write-Debug "NeedUninstallLIS value is $global:NeedUninstallLIS"
        return "PASS"
    } else {
        return "ABORTED"
    }
}

# Scenario Information : Upgrade to current LIS
# (Installs Previous LIS version -> Upgrade to Current LIS version)
# Expected result : Verify that LIS has upgraded to Current LIS successfully
Function Install-LIS-Scenario-2 ($PreviousTestResult, $LISTarballUrlOld, $LISTarballUrlCurrent) {
    if ($PreviousTestResult -eq "PASS") {
        $UpgradeStatus = Upgrade-LIS -LISTarballUrlOld $LISTarballUrlOld -LISTarballUrlCurrent $LISTarballUrlCurrent -allVMData $AllVMData -TestProvider $TestProvider -RestartAfterUpgrade
        if (-not $UpgradeStatus[-1]) {
            $sts = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "cat build-CustomLIS.txt | grep -E 'Unsupported kernel version|Kernel version not supported'" -ignoreLinuxExitCode:$true
            if ($sts) {
                Write-LogInfo "Unsupported kernel version, skip test.."
                return "SKIPPED"
            } else {
                return "FAIL"
            }
        }
        if ($TestPlatform -eq "HyperV") {
            #Take Snapshot with name
            Create-HyperVCheckpoint -VMData $AllVMData -CheckpointName "CURRENT_LIS_UPGRADED"
        }
        $global:NeedUninstallLIS = $true
        Write-Debug "NeedUninstallLIS value is $global:NeedUninstallLIS"
        return "PASS"
    } else {
        return "ABORTED"
    }
}

# Scenario Information : Downgrade LIS to old LIS.
# (Installs Previous LIS version -> Upgrade to Current LIS version -> UnInstall to Current LIS version -> ReInstall Previous LIS version)
# Expected result : Verify that LIS has Downgraded to old LIS successfully
Function Install-LIS-Scenario-3 ($PreviousTestResult, $LISTarballUrlOld, $LISTarballUrlCurrent) {
    if ($PreviousTestResult -eq "PASS") {
        if ($TestPlatform -eq "HyperV") {
            $sts = Apply-HyperVCheckpoint -VMData $AllVMData -CheckpointName "CURRENT_LIS_UPGRADED"
            if (-not $sts) {
                return "ABORTED"
            }
        } elseif ($TestPlatform -eq "Azure") {
            $UpgradeStatus = Upgrade-LIS -LISTarballUrlOld $LISTarballUrlOld -LISTarballUrlCurrent $LISTarballUrlCurrent -allVMData $AllVMData -TestProvider $TestProvider -RestartAfterUpgrade
            if (-not $UpgradeStatus[-1]) {
                $sts = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "cat build-CustomLIS.txt | grep -E 'Unsupported kernel version|Kernel version not supported'" -ignoreLinuxExitCode:$true
                if ($sts) {
                    Write-LogInfo "Unsupported kernel version, skip test.."
                    return "SKIPPED"
                } else {
                    return "FAIL"
                }
            }
        }
        $DowgradeStatus = Downgrade-LIS -LISTarballUrlOld $LISTarballUrlOld -LISTarballUrlCurrent $LISTarballUrlCurrent -allVMData $AllVMData -TestProvider $TestProvider
        if (-not $DowgradeStatus[-1]) {
            $global:NeedUninstallLIS = $true
            Write-Debug "NeedUninstallLIS value is $global:NeedUninstallLIS"
            return "FAIL"
        }
        return "PASS"
    } else {
        return "ABORTED"
    }
}

#Scenario Information : Upgrade kernel without reboot and install Current LIS
#Expected result : Verify that LIS should abort install (LIS negative scenario test)
Function Install-LIS-Scenario-4 ($PreviousTestResult, $LISTarballUrlOld, $LISTarballUrlCurrent) {
    if ($PreviousTestResult -eq "PASS") {
        $UpgradekernelStatus = Upgrade-Kernel -allVMData $AllVMData -TestProvider $TestProvider
        if (-not $UpgradekernelStatus[-1]) {
            return "SKIPPED"
        }
        $LISInstallStatus = Install-LIS -LISTarballUrl $LISTarballUrlCurrent -allVMData $AllVMData
        if ($LISInstallStatus[-1] -ne $false) {
            Write-LogErr "LIS installation should fail but succeeded"
            return "FAIL"
        }
        Write-LogInfo "Installation failed as expected."
        if ($TestProvider.RestartAllDeployments($AllVMData)) {
            $null = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "rm -rf build-CustomLIS.txt" -ignoreLinuxExitCode:$true
            Write-LogInfo "Restart VM for new kernel takes effect, to avoid impact on following cases."
            return "PASS"
        } else {
            return "FAIL"
        }
    } else {
        return "ABORTED"
    }
}

# Scenario Information : Installs Current LIS then upgrade kernel with reboot
# Expected result : Verify that LIS built-in drivers are detected after kernel upgrade
Function Install-LIS-Scenario-5 ($PreviousTestResult, $LISTarballUrlOld, $LISTarballUrlCurrent) {
    if ($PreviousTestResult -eq "PASS") {
        if ($TestPlatform -eq "HyperV") {
            $sts = Apply-HyperVCheckpoint -VMData $AllVMData -CheckpointName "CURRENT_LIS_INSTALLED"
            if (-not $sts) {
                return "ABORTED"
            }
        } elseif ($TestPlatform -eq "Azure") {
            $LISInstallStatus = Install-LIS -LISTarballUrl $LISTarballUrlCurrent -allVMData $AllVMData
            if (-not $LISInstallStatus[-1]) {
                $sts = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "cat build-CustomLIS.txt | grep -E 'Unsupported kernel version|Kernel version not supported'" -ignoreLinuxExitCode:$true
                if ($sts) {
                    Write-LogInfo "Unsupported kernel version, skip test.."
                    return "SKIPPED"
                } else {
                    return "FAIL"
                }
            }
        }
        $LIS_version_before_upgrade_kernel = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "modinfo hv_vmbus"
        Write-LogInfo "LIS version before upgrading kernel: $LIS_version_before_upgrade_kernel"
        $UpgradekernelStatus = Upgrade-Kernel -allVMData $AllVMData -TestProvider $TestProvider -RestartAfterUpgrade
        if (-not $UpgradekernelStatus[-1]) {
            $global:NeedUninstallLIS = $true
            Write-Debug "NeedUninstallLIS value is $global:NeedUninstallLIS"
            return "SKIPPED"
        }
        $LIS_version_after_upgrade_kernel = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "modinfo hv_vmbus"
        Write-LogInfo "LIS version after upgrading kernel: $LIS_version_after_upgrade_kernel"
        if ($LIS_version_before_upgrade_kernel -ne $LIS_version_after_upgrade_kernel) {
            Write-LogInfo "LIS built-in drivers are detected.. after kernel upgrade."
        } else {
            Write-LogErr "New LIS version NOT detected"
            return "FAIL"
        }
        $global:NeedUninstallLIS = $true
        Write-Debug "NeedUninstallLIS value is $global:NeedUninstallLIS"
        return "PASS"
    } else {
        return "ABORTED"
    }
}

# Scenario Information : Upgrade LIS, upgrade kernel.
# (Install Previous LIS -> Upgrade to Current LIS -> Upgrade Kernel with reboot)
# Expected result : Verify that LIS built-in drivers are detected after Kernel Upgrade
Function Install-LIS-Scenario-6 ($PreviousTestResult, $LISTarballUrlOld, $LISTarballUrlCurrent) {
    if ($PreviousTestResult -eq "PASS") {
        if ($TestPlatform -eq "HyperV") {
            $sts = Apply-HyperVCheckpoint -VMData $AllVMData -CheckpointName "CURRENT_LIS_UPGRADED"
            if (-not $sts) {
                return "ABORTED"
            }
        } elseif ($TestPlatform -eq "Azure") {
            $UpgradeStatus = Upgrade-LIS -LISTarballUrlOld $LISTarballUrlOld -LISTarballUrlCurrent $LISTarballUrlCurrent -allVMData $AllVMData -TestProvider $TestProvider -RestartAfterUpgrade
            if (-not $UpgradeStatus[-1]) {
                $sts = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "cat build-CustomLIS.txt | grep -E 'Unsupported kernel version|Kernel version not supported'" -ignoreLinuxExitCode:$true
                if ($sts) {
                    Write-LogInfo "Unsupported kernel version, skip test.."
                    return "SKIPPED"
                } else {
                    return "FAIL"
                }
            }
        }
        $LIS_version_before_upgrade_kernel = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "modinfo hv_vmbus"
        Write-LogInfo "LIS version before upgrading kernel: $LIS_version_before_upgrade_kernel"
        $UpgradekernelStatus = Upgrade-Kernel -allVMData $AllVMData -TestProvider $TestProvider -RestartAfterUpgrade
        if (-not $UpgradekernelStatus[-1]) {
            $global:NeedUninstallLIS = $true
            Write-Debug "NeedUninstallLIS value is $global:NeedUninstallLIS"
            return "SKIPPED"
        }
        $LIS_version_after_upgrade_kernel = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "modinfo hv_vmbus"
        Write-LogInfo "LIS version after upgrading kernel: $LIS_version_after_upgrade_kernel"
        if ($LIS_version_before_upgrade_kernel -ne $LIS_version_after_upgrade_kernel) {
            Write-LogInfo "LIS built-in drivers are detected.. after kernel upgrade."
        } else {
            Write-LogErr "New LIS version NOT detected"
            return "FAIL"
        }
        $global:NeedUninstallLIS = $true
        Write-Debug "NeedUninstallLIS value is $global:NeedUninstallLIS"
        return "PASS"
    } else {
        return "ABORTED"
    }
}

# Scenario Information : Upgrade minor kernel, Upgrade LIS
# (Upgrade minor kernel -> Install Previous LIS -> Upgrade to Current LIS)
# If it's an Oracle distro, skip the test
# Expected result : Verify that LIS has upgraded to Current LIS successfully after kernel upgrade
Function Install-LIS-Scenario-7 ($PreviousTestResult, $LISTarballUrlOld, $LISTarballUrlCurrent) {
    if ($PreviousTestResult -eq "PASS") {
        if ($detectedDistro -imatch "ORACLELINUX") {
            Write-LogErr "Skipped: Oracle not supported on this TC"
            return "SKIPPED"
        }
        Write-LogInfo "Upgrading minor kernel"
        $kernel_version_before_upgrade = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "uname -r"
        Write-LogInfo "kernel version before upgrade: $kernel_version_before_upgrade"
        $UpgradeKernelConsoleOutput = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username $user -password $password -command ". utils.sh && UpgradeMinorKernel" -runMaxAllowedTime 2000 -maxRetryCount 3 -runAsSudo
        Write-LogInfo $UpgradeKernelConsoleOutput
        Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "sync"
        if ($TestProvider.RestartAllDeployments($allVMData)) {
            $kernel_version_after_upgrade = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "uname -r"
            Write-LogInfo "kernel version after upgrade: $kernel_version_after_upgrade"
            if ($kernel_version_after_upgrade -eq $kernel_version_before_upgrade) {
                Write-LogErr "Failed to Upgrade Minor kernel"
                return "SKIPPED"
            }
            Write-LogInfo "Sucessfully Upgraded Minor Kernel"
            $UpgradeStatus = Upgrade-LIS -LISTarballUrlOld $LISTarballUrlOld -LISTarballUrlCurrent $LISTarballUrlCurrent -allVMData $AllVMData -TestProvider $TestProvider -RestartAfterUpgrade
            if (-not $UpgradeStatus[-1]) {
                $sts = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "cat build-CustomLIS.txt | grep -E 'Unsupported kernel version|Kernel version not supported'" -ignoreLinuxExitCode:$true
                if ($sts) {
                    Write-LogInfo "Unsupported kernel version, skip test.."
                    return "SKIPPED"
                } else {
                    return "FAIL"
                }
            }
            $global:NeedUninstallLIS = $true
            Write-Debug "NeedUninstallLIS value is $global:NeedUninstallLIS"
            return "PASS"
        } else {
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
            $sts = Apply-HyperVCheckpoint -VMData $AllVMData -CheckpointName "CURRENT_LIS_INSTALLED"
            if (-not $sts) {
                return "ABORTED"
            }
        } elseif ($TestPlatform -eq "Azure") {
            $LISInstallStatus = Install-LIS -LISTarballUrl $LISTarballUrlCurrent -allVMData $AllVMData
            if (-not $LISInstallStatus[-1]) {
                $sts = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "cat build-CustomLIS.txt | grep -E 'Unsupported kernel version|Kernel version not supported'" -ignoreLinuxExitCode:$true
                if ($sts) {
                    Write-LogInfo "Unsupported kernel version, skip test.."
                    return "SKIPPED"
                } else {
                    return "FAIL"
                }
            }
        }
        $UninstallLISStatus = Uninstall-LIS -LISTarballUrlCurrent $LISTarballUrlCurrent -allVMData $AllVMData -TestProvider $TestProvider
        if (-not $UninstallLISStatus[-1]) {
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
        if (!@("REDHAT", "ORACLELINUX", "CENTOS").contains($global:detectedDistro)) {
                Write-LogInfo "Skip case for UNSUPPORTED distro - $global:detectedDistro"
                return "SKIPPED"
        }
        $PreviousTestResult = "PASS"
        foreach ($param in $CurrentTestData.TestParameters.param) {
            if ($param -imatch "LIS_TARBALL_URL_CURRENT") {
                $LISTarballUrlCurrent = $param.Replace("LIS_TARBALL_URL_CURRENT=","")
            }
            if ($param -imatch "LIS_TARBALL_URL_OLD") {
                $LISTarballUrlOld = $param.Replace("LIS_TARBALL_URL_OLD=","")
            }
        }
        if ($LISTarballUrlCurrent -eq "LatestLIS") {
            $LISTarballUrlCurrent = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "echo ``curl -Ls -o /dev/null -w %{url_effective} http://aka.ms/lis``"
        }
        if ($LISTarballUrlOld -eq "LatestLIS") {
            $LISTarballUrlOld = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "echo ``curl -Ls -o /dev/null -w %{url_effective} http://aka.ms/lis``"
        }
        #PROVISION VMS FOR LISA WILL ENABLE ROOT USER AND WILL MAKE ENABLE PASSWORDLESS AUTHENTICATION ACROSS ALL VMS IN SAME HOSTED SERVICE.
        Provision-VMsForLisa -allVMData $AllVMData -installPackagesOnRoleNames "none"
        Check-Modules | Out-Null
        $isHv_vmbusModule = $False
        $context = Get-Content $LogDir\LIS-MODULES-CHECK.py.log
        foreach ($line in $context) {
            if ($line -imatch "Module *hv_vmbus *: *Present") {
                $isHv_vmbusModule = $True
            }
        }
        if (-not $isHv_vmbusModule) {
            Write-LogInfo "The hv_vmbus is built-in, so skip the test"
            return "SKIPPED"
        }
        #endregion
        foreach ($Scenario in $CurrentTestData.TestParameters.param) {
            $global:NeedUninstallLIS = $false
            switch ($Scenario) {
                "Install-LIS-Scenario-1" {
                    $testResult = Install-LIS-Scenario-1 -PreviousTestResult $PreviousTestResult -LISTarballUrlOld $LISTarballUrlOld -LISTarballUrlCurrent $LISTarballUrlCurrent
                    $CurrentTestResult.TestSummary += New-ResultSummary -testResult $testResult -metaData "$Scenario" `
                    -checkValues "PASS,FAIL,ABORTED,SKIPPED" -testName $currentTestData.testName
                    break;
                }
                "Install-LIS-Scenario-2" {
                    $testResult = Install-LIS-Scenario-2 -PreviousTestResult $PreviousTestResult -LISTarballUrlOld $LISTarballUrlOld -LISTarballUrlCurrent $LISTarballUrlCurrent
                    $CurrentTestResult.TestSummary += New-ResultSummary -testResult $testResult -metaData "$Scenario" `
                    -checkValues "PASS,FAIL,ABORTED,SKIPPED" -testName $currentTestData.testName
                    break;
                }
                "Install-LIS-Scenario-3" {
                    $testResult = Install-LIS-Scenario-3 -PreviousTestResult $PreviousTestResult -LISTarballUrlOld $LISTarballUrlOld -LISTarballUrlCurrent $LISTarballUrlCurrent
                    $CurrentTestResult.TestSummary += New-ResultSummary -testResult $testResult -metaData "$Scenario" `
                    -checkValues "PASS,FAIL,ABORTED,SKIPPED" -testName $currentTestData.testName
                    break;
                }
                "Install-LIS-Scenario-4" {
                    $testResult = Install-LIS-Scenario-4 -PreviousTestResult $PreviousTestResult -LISTarballUrlOld $LISTarballUrlOld -LISTarballUrlCurrent $LISTarballUrlCurrent
                    $CurrentTestResult.TestSummary += New-ResultSummary -testResult $testResult -metaData "$Scenario" `
                    -checkValues "PASS,FAIL,ABORTED,SKIPPED" -testName $currentTestData.testName
                    break;
                }
                "Install-LIS-Scenario-5" {
                    $testResult = Install-LIS-Scenario-5 -PreviousTestResult $PreviousTestResult -LISTarballUrlOld $LISTarballUrlOld -LISTarballUrlCurrent $LISTarballUrlCurrent
                    $CurrentTestResult.TestSummary += New-ResultSummary -testResult $testResult -metaData "$Scenario" `
                    -checkValues "PASS,FAIL,ABORTED,SKIPPED" -testName $currentTestData.testName
                    break;
                }
                "Install-LIS-Scenario-6" {
                    $testResult = Install-LIS-Scenario-6 -PreviousTestResult $PreviousTestResult -LISTarballUrlOld $LISTarballUrlOld -LISTarballUrlCurrent $LISTarballUrlCurrent
                    $CurrentTestResult.TestSummary += New-ResultSummary -testResult $testResult -metaData "$Scenario" `
                    -checkValues "PASS,FAIL,ABORTED,SKIPPED" -testName $currentTestData.testName
                    break;
                }
                "Install-LIS-Scenario-7" {
                    $testResult = Install-LIS-Scenario-7 -PreviousTestResult $PreviousTestResult -LISTarballUrlOld $LISTarballUrlOld -LISTarballUrlCurrent $LISTarballUrlCurrent
                    $CurrentTestResult.TestSummary += New-ResultSummary -testResult $testResult -metaData "$Scenario" `
                    -checkValues "PASS,FAIL,ABORTED,SKIPPED" -testName $currentTestData.testName
                    break;
                }
                "Install-LIS-Scenario-8" {
                    $testResult = Install-LIS-Scenario-8 -PreviousTestResult $PreviousTestResult -LISTarballUrlOld $LISTarballUrlOld -LISTarballUrlCurrent $LISTarballUrlCurrent
                    $CurrentTestResult.TestSummary += New-ResultSummary -testResult $testResult -metaData "$Scenario" `
                    -checkValues "PASS,FAIL,ABORTED,SKIPPED" -testName $currentTestData.testName
                    break;
                }
                default {
                    #Do nothing.
                }
            }
            if ($global:NeedUninstallLIS) {
                Write-Debug "NeedUninstallLIS value is $global:NeedUninstallLIS"
                Write-LogInfo "In case $Scenario - uninstall LIS $LISTarballUrlCurrent start"
                Uninstall-LIS -LISTarballUrlCurrent $LISTarballUrlCurrent -allVMData $AllVMData -TestProvider $TestProvider | out-null
                Write-LogInfo "In case $Scenario - uninstall LIS $LISTarballUrlCurrent end"
            }
            $PreviousTestResult = $testResult
        }
    } catch {
        $ErrorMessage = $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = "ABORTED"
            $CurrentTestResult.TestSummary += New-ResultSummary -testResult $testResult -metaData "LIS-INSTALL-SCENARIOS" `
                -checkValues "PASS,FAIL,ABORTED,SKIPPED" -testName $currentTestData.testName
        }
        $resultArr += $testResult
    }
    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult
}

Main
