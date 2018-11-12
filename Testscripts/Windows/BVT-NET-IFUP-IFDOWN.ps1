# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
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
    $stateFile = "${LogDir}\state.txt"
    $bvtCmd = "echo '${VMPassword}' | sudo -S -s eval `"export HOME=``pwd``;bash ${remoteScript} > BVT-NET-IFUP-IFDOWN.log`""
    RunLinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort $bvtCmd -RunInBackground -runAsSudo
    # Wait for the test to finish running on VM
    do {
        if ($TestPlatform -eq "HyperV") {
            $newIp = Get-IPv4AndWaitForSSHStart -VMName $VMName -HvServer $HvServer `
                -VmPort $VmPort -User $VMUserName -Password $VMPassword -StepTimeout 30
        }
        else {
            $newIp = $allVmData.PublicIP
        }
        RemoteCopy -download -downloadFrom $newIp -files "/home/${VMUserName}/state.txt" `
            -downloadTo $LogDir -port $VMPort -username $VMUserName -password $VMPassword
        $contents = Get-Content -Path $stateFile
        Start-Sleep -Seconds 30
    } until (($contents -eq "TestCompleted") -or ($contents -eq "TestAborted") `
     -or ($contents -eq "TestFailed") -or ((Get-Date) -gt $expiration))
    RemoteCopy -download -downloadFrom $newIp -files "/home/${VMUserName}/BVT-NET-IFUP-IFDOWN.log" `
        -downloadTo $LogDir -port $VMPort -username $VMUserName -password $VMPassword
    if (($contents -eq "TestAborted") -or ($contents -eq "TestFailed") -or ((Get-Date) -gt $expiration)) {
        LogErr "Error: Running $remoteScript script failed on VM!"
        return "FAIL"
    }
    else {
        LogMsg "Test BVT-NET-IFUP-IFDOWN PASSED !"
    }
}
Main -VMName $AllVMData.RoleName -HvServer $TestLocation `
    -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
    -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory