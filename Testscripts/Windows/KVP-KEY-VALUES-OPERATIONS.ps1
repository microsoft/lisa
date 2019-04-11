# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# This script handles the following KVP operations:
# - Add a KVP key and value on host
# - Modify the above entry with different values on host
# - Delete the modified KVP entry on host

param([object] $AllVmData, [object] $CurrentTestData, [object] $TestProvider, [string]$TestParams)

Function Confirm-KVPKey {
    param(
        [String] $VMUserName,
        [String] $VMPassword,
        [String] $Ipv4,
        [String] $VMPort,
        [String] $Pool,
        [String] $Key,
        [String] $Value
    )

    $CMDtoVM = @'
  #!/bin/bash
  # Verify OS architecture
  uname -a | grep x86_64
  if [ $? -eq 0 ]; then
      echo "64 bit architecture was detected"
      kvp_client="kvp_client64"
  else
      uname -a | grep i686
      if [ $? -eq 0 ]; then
          echo "32 bit architecture was detected"
          kvp_client="kvp_client32"
      else
          echo "Unable to detect OS architecture"
          exit 1
      fi
  fi
  # Make sure we have the kvp_client tool
  if [ ! -e ~/${kvp_client} ]; then
      echo "${kvp_client} tool is not on the system"
      exit 1
  fi
  chmod 755 ~/${kvp_client}
  # verify that the Key Value is present in the specified pool or not.
  if [[ $1 != '' ]]; then
      Pool=$1
  else
      echo "Please specify Pool"
      exit 1
    fi
  if [[ $2 != '' ]]; then
      Key=$2
  else
      echo "Please specify Key"
      exit 1
  fi
  if [[ $3 != '' ]]; then
      Value=$3
  else
      echo "Please specify Value"
      exit 1
  fi
  ~/${kvp_client} ${Pool} | grep "${Key}; Value: ${Value}"
  if [ $? -ne 0 ]; then
      echo "the KVP item is not in the pool"
      exit 1
  fi
  echo "KVP item found in the pool"
  exit 0
'@
    $remoteScript = "VerifyKVPEntries.sh"
    if (Test-Path ".\${remoteScript}") {
        Remove-Item ".\${remoteScript}"
    }
    Add-Content $remoteScript "$cmdToVM" | Out-Null
    Copy-RemoteFiles -uploadTo $Ipv4 -port $VMPort -files $remoteScript -username $VMUserName -password $VMPassword -upload
    $logfile = "KVP-Verify-${Pool}-${Key}-${Value}.log"
    $ConfirmKVPKey = "echo '${VMPassword}' | sudo -S -s eval `"export HOME=``pwd``;bash ${remoteScript} ${Pool} ${Key} ${Value} > $logfile`""
    $null = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort $ConfirmKVPKey -runAsSudo
    Copy-RemoteFiles -download -downloadFrom $Ipv4 -files "/home/${VMUserName}/$logfile" `
        -downloadTo $LogDir -port $VMPort -username $VMUserName -password $VMPassword
    $contents = Get-Content -Path "${LogDir}\$logfile"
    if ($contents -contains "Key: ${Key}; Value: ${Value}") {
        Write-LogInfo "Found:Pool=${Pool};Key=${Key};Value=${Value}"
        return $True
    }
    else {
        Write-LogErr "Fail to find Pool=${Pool};Key=${Key};Value=${Value}"
        return $False
    }

    Copy-RemoteFiles -download -downloadFrom $Ipv4 -files "/home/${VMUserName}/$logfile" `
        -downloadTo $LogDir -port $VMPort -username $VMUserName -password $VMPassword
}

function Invoke-KVPAction {
    param (
        [String] $VMName,
        [String] $HvServer,
        [String] $Key,
        [String] $Value,
        [String] $Action
    )

    Write-LogInfo "Creating VM Management Service object"
    $vmManagementService = Get-WmiObject -ComputerName $HvServer -class "Msvm_VirtualSystemManagementService" `
        -namespace "root\virtualization\v2"
    if (-not $vmManagementService) {
        Write-LogErr "Unable to create a VMManagementService object"
        return $False
    }

    $vmGuest = Get-WmiObject -ComputerName $HvServer -Namespace root\virtualization\v2 `
        -Query "Select * From Msvm_ComputerSystem Where ElementName='$VMName'"
    if (-not $vmGuest) {
        Write-LogErr "Unable to create VMGuest object"
        return $False
    }

    Write-LogInfo "Creating Msvm_KvpExchangeDataItem object"
    $msvmKvpExchangeDataItemPath = "\\$HvServer\root\virtualization\v2:Msvm_KvpExchangeDataItem"
    $msvmKvpExchangeDataItem = ([WmiClass]$msvmKvpExchangeDataItemPath).CreateInstance()
    if (-not $msvmKvpExchangeDataItem) {
        Write-LogErr "Error: Unable to create Msvm_KvpExchangeDataItem object"
        return $False
    }

    Write-LogInfo "Performing ${Action} action with Key ${Key} / Value ${Value} from Pool ${Pool}"
    $msvmKvpExchangeDataItem.Source = 0
    $msvmKvpExchangeDataItem.Name = $Key
    $msvmKvpExchangeDataItem.Data = $Value
    $result =  $vmManagementService.$Action($vmGuest, $msvmKvpExchangeDataItem.PSBase.GetText(1))
    $job = [wmi]$result.Job
    while ($job.jobstate -lt 7) {
        $job.get()
    }
    if ($job.ErrorCode -ne 0) {
        Write-LogErr "${Action} the key value pair"
        Write-LogErr "Job error code = $($Job.ErrorCode)"

        if ($job.ErrorCode -eq 32773) {
            Write-LogErr "Key does not exist.  Key = '${key}'"
            return $False
        }
        else {
            Write-LogErr "Unable to ${Action} KVP key '${key}'"
            return $False
        }
    }
    if ($job.Status -ne "OK") {
        Write-LogErr "${Action} job did not complete with status OK"
        return $False
    }
    Write-LogInfo "${Action} perfomed successfully "
    return $True
}
# Define KVP operations in functions
function Add-KVPKey {
    param (
        $VMName,
        $HvServer,
        $Ipv4,
        $VMPort,
        $VMUserName,
        $VMPassword,
        $Key,
        $Pool,
        $AddValue
    )

    $KVPAddAction = Invoke-KVPAction -VMName $VMName -HvServer $HvServer -Key $Key -Value $AddValue -Action "AddKvpItems"
    if (-not $KVPAddAction) {
        Write-LogErr "Failed to Add KVP item"
        $retValue = $False
    }
    else {
        Write-LogInfo "KVP item successfully Added"
        $retValue = $True
    }

    $KVPAddKeyValues = Confirm-KVPKey -VMUserName $VMUserName -VMPassword $VMPassword -Ipv4 $Ipv4 -VMPort $VMPort `
        -Key $Key -Pool $Pool -Value $AddValue
    if (-not $KVPAddKeyValues) {
        Write-LogErr "Failed to verify Added KVP item"
        $retValue = $False
    }
    else {
        Write-LogInfo "Added KVP item successfully verified"
        $retValue = $True
    }
   return $retValue
}
function Switch-KVPKey {
    param (
        $VMName,
        $HvServer,
        $Ipv4,
        $VMPort,
        $VMUserName,
        $VMPassword,
        $Key,
        $Pool,
        $ModValue
    )

    $KVPModifyAction = Invoke-KVPAction -VMName $VMName -HvServer $HvServer -Key $Key -Value $ModValue -Action "ModifyKvpItems"
    if (-not $KVPModifyAction) {
        Write-LogErr "Failed to Modify KVP item"
        $retValue = $False
    }
    else {
        Write-LogInfo "KVP item successfully modified"
        $retValue = $True
    }

    $KVPModifyKeyValues = Confirm-KVPKey -VMUserName $VMUserName -VMPassword $VMPassword -Ipv4 $Ipv4 -VMPort $VMPort `
        -Key $Key -Pool $Pool -Value $ModValue
    if (-not $KVPModifyKeyValues) {
        Write-LogErr "Failed to verify modified KVP item"
        $retValue = $False
    }
    else {
        Write-LogInfo "Modified KVP item successfully verified"
        $retValue = $True
    }
   return $retValue
}

function Remove-KVPkey {
    param (
        $VMName,
        $HvServer,
        $Key,
        $Pool,
        $DelValue
    )

    $KVPRemoveKeyValues = Invoke-KVPAction -VMName $VMName -HvServer $HvServer -Key $Key -Value $DelValue -Pool $Pool -Action "RemoveKvpItems"
    if (-not $KVPRemoveKeyValues) {
        Write-LogErr "Failed to deleted KVP item"
        return $False
    }
    else {
        Write-LogInfo "KVP item successfully deleted"
        return $True
    }

}

function Main {
    param([object] $allVMData, [object] $CurrentTestData, [object] $TestProvider, [string]$TestParams)

    if (-not $TestParams) {
        Write-LogErr "No TestParams provided"
        Write-LogErr "This script requires the Key & value test parameters"
        return "Aborted"
    }
    # Find the TestParams required.  Complain if not found
    $params = $TestParams.Split(";")
    foreach ($p in $params) {
        $fields = $p.Split("=")
        switch ($fields[0].Trim()) {
            "Pool" {$Pool = $fields[1].Trim() }
            "Key" { $Key = $fields[1].Trim() }
            "AddValue" { $AddValue = $fields[1].Trim() }
            "ModValue" { $ModValue = $fields[1].Trim() }
            "DelValue" { $DelValue = $fields[1].Trim() }
            default {}  # unknown param - just ignore it
        }
    }

    if (-not $Pool) {
        Write-LogErr "Missing testParam Pool to be added"
        return "FAIL"
    }
    if (-not $Key) {
        Write-LogErr "Missing testParam Key to be added"
        return "FAIL"
    }
    if (-not $AddValue) {
        Write-LogErr "Missing testParam AddValue to be added"
        return "FAIL"
    }
    if (-not $ModValue) {
        Write-LogErr "Missing testParam ModValue to be added"
        return "FAIL"
    }
    if (-not $DelValue) {
        Write-LogErr "Missing testParam DelValue to be added"
        return "FAIL"
    }

    try {
        $CurrentTestResult = Create-TestResultObject
        $addkvpkey = Add-KVPKey -VMName $AllVMData.RoleName -HvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
            -Ipv4 $AllVMData.PublicIP -VMUserName $username -VMPassword $password -VMPort $AllVMData.SSHPort `
            -Key $Key -Pool $Pool -AddValue $AddValue
        if (!$addkvpkey) {
            $CurrentTestResult.TestSummary += New-ResultSummary -testResult "FAIL" -metaData "ADD KVP VALUE" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
            $testResult = "FAIL"
        }
        else {
            $testResult = "PASS"
            $CurrentTestResult.TestSummary += New-ResultSummary -testResult "PASS" -metaData "ADD KVP VALUE" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
        }
        $modifykvpkey = Switch-KVPKey -VMName $AllVMData.RoleName -HvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
            -Ipv4 $AllVMData.PublicIP -VMUserName $username -VMPassword $password -VMPort $AllVMData.SSHPort `
            -Key $Key -Pool $Pool -ModValue $ModValue
        if (!$modifykvpkey) {
            $CurrentTestResult.TestSummary += New-ResultSummary -testResult "FAIL" -metaData "MODIFY KVP VALUE" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
            $testResult = "FAIL"
        }
        else {
            $CurrentTestResult.TestSummary += New-ResultSummary -testResult "PASS" -metaData "MODIFY KVP VALUE" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
            $testResult = "PASS"
        }
        $removekvpkey = Remove-KVPkey -VMName $AllVMData.RoleName -HvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
            -Key $Key - Pool $Pool -DelValue $DelValue
        if (!$removekvpkey) {
            $CurrentTestResult.TestSummary += New-ResultSummary -testResult "FAIL" -metaData "REMOVE KVP VALUE" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
            $testResult = "FAIL"
        }
        else {
            $CurrentTestResult.TestSummary += New-ResultSummary -testResult "PASS" -metaData "REMOVE KVP VALUE" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
            $testResult = "PASS"
        }
    }
    catch {
        $ErrorMessage = $_.Exception.Message
        Write-LogInfo "EXCEPTION : $ErrorMessage"
    }
    Finally {
        if (!$testResult) {
            $testResult = "ABORTED"
        }
        if ((!$addkvpkey) -or (!$modifykvpkey) -or (!$removekvpkey)) {
            $testResult = "FAIL"
        }
        $resultArr += $testResult
    }

    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult
}
Main -allVMData $AllVmData -CurrentTestData $CurrentTestData -TestProvider $TestProvider -TestParams $TestParams
