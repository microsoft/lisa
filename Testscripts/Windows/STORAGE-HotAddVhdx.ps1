# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

param([String] $TestParams,
      [object] $AllVmData,
      [object] $CurrentTestData)

$SETUP_SCRIPT = ".\TestScripts\Windows\AddVhdxHardDisk.ps1"
$TEST_SCRIPT = "STOR-Lis-Disk.sh"

function Main {
    param (
        $VMname,
        $HvServer,
        $Ipv4,
        $VMPort,
        $VMUserName,
        $VMPassword,
        $RootDir,
        $TestParams,
        $CurrentTestData
    )

    $testName = $currentTestData.testName
    $params = ConvertFrom-StringData -StringData $TestParams.replace(";", "`n")

    Run-SetupScript -Script $SETUP_SCRIPT -Parameters $params -VMData $AllVMData -CurrentTestData $CurrentTestData

    Run-LinuxCmd -Command "echo '${VMPassword}' | sudo -S -s eval `"export HOME=``pwd``;bash ${TEST_SCRIPT} > ${testName}_summary.log 2>&1`"" `
        -Username $VMUserName -password $VMPassword -ip $Ipv4 -Port $VMPort `

    $testResult = Collect-TestLogs -LogsDestination $LogDir -ScriptName "STOR-Lis-Disk" -TestType "sh" `
        -PublicIP $Ipv4 -SSHPort $VMPort -Username $VMUserName -password $VMPassword `
        -TestName $currentTestData.testName

    return $testResult
}

Main -VMname $AllVMData.RoleName -HvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
    -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
    -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory `
    -TestParams $TestParams -CurrentTestData $CurrentTestData
