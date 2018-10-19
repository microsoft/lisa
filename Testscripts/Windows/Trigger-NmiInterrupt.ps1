# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
 <#
.Synopsis
 Trigger an NMI on a target VM
#>
param([String] $TestParams)

$ErrorActionPreference = "Stop"

function Trigger-NmiInterrupt {
    param(
        $VMName,
        $Ipv4,
        $VMPassword,
        $HvServer="localhost",
        $VMPort=22,
        $VMUsername="root",
        $RootDir="/root/"
    )

    $remoteScript = "check_triggered_nmi.sh"
    $buildNumber = Get-HostBuildNumber $hvServer
    if (!$buildNumber) {
        return "FAIL"
    }
    if ($BuildNumber -lt 9600) {
        return "ABORTED"
    }

    try {
        Debug-VM -Name $VMName -InjectNonMaskableInterrupt `
                 -ComputerName $HvServer -Confirm:$False -Force `
                 -ErrorAction "Stop"
        LogMsg "Successfully triggered an NMI on VM ${vmName}"

        $nmiCheckScript = "echo '${VMPassword}' | sudo -S -s eval `"export HOME=``pwd``;bash ${remoteScript} > nmicheck.log`""
        $includeBuildNumberScript = "echo '${VMPassword}' | sudo -S -s eval `"export HOME=``pwd``;echo 'BuildNumber=${buildNumber}' >> `$HOME/constants.sh`""
        $nmiCheckLog = "/home/${VMUserName}/nmicheck.log"
        $nmiCheckState = "/home/${VMUserName}/state.txt"

        RunLinuxCmd -username $VMUserName -password $VMPassword `
                    -ip $Ipv4 -port $VMPort $includeBuildNumberScript

        RunLinuxCmd -username $VMUserName -password $VMPassword `
                    -ip $Ipv4 -port $VMPort $nmiCheckScript -runAsSudo

        RemoteCopy -download -downloadFrom $Ipv4 -files $nmiCheckLog `
                   -downloadTo $LogDir -port $VMPort -username $VMUserName `
                   -password $VMPassword
        RemoteCopy -download -downloadFrom $Ipv4 -files $nmiCheckState `
                   -downloadTo $LogDir -port $VMPort -username $VMUserName `
                   -password $VMPassword
        $stateFile = "${LogDir}\state.txt"
        $contents = Get-Content -Path $stateFile
        if (($contents -eq "TestAborted") -or ($contents -eq "TestFailed")) {
            LogErr "Running ${remoteScript} script failed."
            return "FAIL"
        }
        return "PASS"
    } catch {
        LogErr "Failed to trigger an NMI on VM ${VMName}"
        LogErr "Internal error message: $_"
        return "FAIL"
    }
}

Trigger-NmiInterrupt -VMName $AllVMData.RoleName `
     -HvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
     -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
     -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory

