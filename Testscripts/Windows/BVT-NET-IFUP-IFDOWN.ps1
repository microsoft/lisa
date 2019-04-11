# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

param([String] $TestParams,
      [object] $AllVmData)

function Main {
    param (
        $VMName,
        $HvServer,
        $Ipv4,
        $VMPort,
        $VMUserName,
        $VMPassword,
        $RootDir
    )

    $remoteScript = "BVT-NET-IFUP-IFDOWN.sh"
    $expiration = (Get-Date).AddMinutes(15)
    Set-Location $RootDir
    #
    # Run the guest VM side script to verify  BVT-NET-IFUP-IFDOWN
    #
    $bvtCmd = "echo '${VMPassword}' | sudo -S -s eval `"export HOME=``pwd``;bash ${remoteScript} > BVT-NET-IFUP-IFDOWN.log`""
    Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort $bvtCmd -RunInBackground -runAsSudo | Out-Null
    # Wait for the test to finish running on VM
    do {
        if ($TestPlatform -eq "HyperV") {
            $newIp = Get-IPv4AndWaitForSSHStart -VMName $VMName -HvServer $HvServer `
                -VmPort $VmPort -User $VMUserName -Password $VMPassword -StepTimeout 30
            $allVmData.PublicIP = $newIp
        }
        else {
            $newIp = $allVmData.PublicIP
        }
        $state = Run-LinuxCmd -ip $newIp -port $VMPort -username $VMUserName -password $VMPassword "cat state.txt" -ignoreLinuxExitCode:$true
        Write-LogInfo "Current status:$state"
        Start-Sleep -Seconds 30
    } until (($state -eq "TestCompleted") -or ($state -eq "TestAborted") `
     -or ($state -eq "TestFailed") -or ($state -eq "TestSkipped") -or ((Get-Date) -gt $expiration))
    Copy-RemoteFiles -download -downloadFrom $newIp -files "/home/${VMUserName}/BVT-NET-IFUP-IFDOWN.log" `
        -downloadTo $LogDir -port $VMPort -username $VMUserName -password $VMPassword
    if (($state -eq "TestAborted") -or ($state -eq "TestFailed") -or ((Get-Date) -gt $expiration)) {
        Write-LogErr "Running $remoteScript script failed on VM!"
        return "FAIL"
    } elseif ($state -eq "TestSkipped") {
        Write-LogInfo "Test BVT-NET-IFUP-IFDOWN SKIPPED!"
        return "SKIPPED"
    } else {
        Write-LogInfo "Test BVT-NET-IFUP-IFDOWN PASSED!"
        return "PASS"
    }
}
Main -VMName $AllVMData.RoleName -HvServer $TestLocation `
    -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
    -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory
