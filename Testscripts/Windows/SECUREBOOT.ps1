# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    This script tests Secure Boot features.
.Description
    This script will test Secure Boot features on a Generation 2 VM.
    It also test the feature after performing a Live Migration of the VM or
    after a kernel update.
#>
param([String] $TestParams)
$ErrorActionPreference = "Stop"
function MigrateVM([String] $vmName)
{
    #
    # Load the cluster commandlet module
    #
    $sts = Import-module FailoverClusters
    if (-not $sts) {
        LogErr "Unable to load FailoverClusters module"
        return $False
    }
    #
    # Have migration networks been configured?
    #
    $migrationNetworks = Get-ClusterNetwork
    if (-not $migrationNetworks) {
        LogErr "$vmName - There are no Live Migration Networks configured"
        return $False
    }
    LogMsg "Get the VMs current node"
    $vmResource =  Get-ClusterResource | where-object {$_.OwnerGroup.name -eq "$vmName" -and $_.ResourceType.Name -eq "Virtual Machine"}
    if (-not $vmResource) {
        LogErr "$vmName - Unable to find cluster resource for current node"
        return $False
    }
    $currentNode = $vmResource.OwnerNode.Name
    if (-not $currentNode) {
        LogErr "$vmName - Unable to set currentNode"
        return $False
    }
    #
    # Get nodes the VM can be migrated to
    #
    $clusterNodes = Get-ClusterNode
    if (-not $clusterNodes -and $clusterNodes -isnot [array]) {
        LogErr "$vmName - There is only one cluster node in the cluster."
        return $False
    }
    #
    # For the initial implementation, just pick a node that does not
    # match the current VMs node
    #
    $destinationNode = $clusterNodes[0].Name.ToLower()
    if ($currentNode -eq $clusterNodes[0].Name.ToLower()) {
        $destinationNode = $clusterNodes[1].Name.ToLower()
    }
    if (-not $destinationNode) {
        LogErr "$vmName - Unable to set destination node"
        return $False
    }
    LogMsg "Migrating VM $vmName from $currentNode to $destinationNode"
    $sts = Move-ClusterVirtualMachineRole -name $vmName -node $destinationNode
    if (-not $sts) {
        LogErr "$vmName - Unable to move the VM"
        return $False
    }
    #
    # Check if Secure Boot is enabled
    #
    $firmwareSettings = Get-VMFirmware -VMName $vmName
    if ($firmwareSettings.SecureBoot -ne "On") {
        LogErr "Secure boot settings changed"
        return $False
    }
    $sts = Move-ClusterVirtualMachineRole -name $vmName -node $currentNode
    if (-not $sts) {
        LogErr "$vmName - Unable to move the VM"
        return $False
    }
    return $True
}

function UpdateKernel([String]$conIpv4,[String]$SSHPort)
{
    $cmdToVM = @"

        #!/bin/bash

        LinuxRelease()
        {
            DISTRO=``grep -ihs "buntu\|Suse\|Fedora\|Debian\|CentOS\|Red Hat Enterprise Linux" /etc/{issue,*release,*version}``
            case `$DISTRO in
                *buntu*)
                    echo "UBUNTU";;
                Fedora*)
                    echo "FEDORA";;
                CentOS*)
                    echo "CENTOS";;
                *SUSE*)
                    echo "SLES";;
                *Red*Hat*)
                    echo "RHEL";;
                Debian*)
                    echo "DEBIAN";;
            esac
        }
        retVal=1
        distro=``LinuxRelease``
        case `$distro in
            "SLES")
                zypper ar -f http://download.opensuse.org/repositories/Kernel:/stable/standard/ kernel
                zypper --gpg-auto-import-keys --non-interactive dup -r kernel
                retVal=`$?
            ;;
            "UBUNTU")
                apt-get update -y
                apt-get dist-upgrade -y
                retVal=`$?
            ;;
            "RHEL" | "CENTOS")
                yum install -y kernel
                retVal=`$?
            ;;
            *)
            ;;
        esac
        exit `$retVal
"@

    $filename="UpdateKernel.sh"
    # check for file
    if (Test-Path ".\${filename}") {
        Remove-Item ".\${filename}"
    }
    Add-Content $filename "$cmdToVM"
    # send file
    RemoteCopy -uploadTo $conIpv4 -port $SSHPort -files $filename -username $user -password $password -upload
    # execute command
    $retVal = RunLinuxCmd -username $user -password $password -ip $conIpv4 -port $SSHPort `
        -command "echo $password | sudo chmod u+x ${filename} && sed -i 's/\r//g' ${filename} && ./${filename}" -runAsSudo
    return $retVal
}

##########################################################################
#
# Main script body
#
##########################################################################
function Main {
    param (
        $TestParams
    )
    try {
        $testResult = $null
        $captureVMData = $allVMData
        $VMName = $captureVMData.RoleName
        $HvServer= $captureVMData.HyperVhost
        $Ipv4 = $captureVMData.PublicIP
        $VMPort= $captureVMData.SSHPort
        # Change the working directory to where we need to be
        Set-Location $WorkingDirectory
        # Check if the VM VHD in not on the same drive as the backup destination
        $vm = Get-VM -Name $VMName -ComputerName $HvServer
        #
        # Check heartbeat
        #
        $heartbeat = Get-VMIntegrationService -VMName $VMName -Name "HeartBeat"
        if ($heartbeat.Enabled) {
            LogMsg "$VMName heartbeat detected"
        }
        else {
            throw "$VMName heartbeat not detected"
        }
        #
        # Test network conectivity
        #
        $pingObject = New-Object System.Net.NetworkInformation.Ping
        if (-not $pingObject) {
            throw "Unable to create a ping object"
        }
        $pingReply = $pingObject.Send($Ipv4)
        if ($pingReply.Status -ne "Success") {
            throw "Cannot ping $VMName. Status = $($pingReply.Status)"
        }
        LogMsg "Ping reply - $($pingReply.Status)"
        #
        # Waiting for the VM to run again and respond to SSH - port 22
        #
        $timeout = 500
        while ($timeout -gt 0) {
            if ( (Test-TCP $Ipv4 $VMPort) -eq "True" ) {
                break
            }
            Start-Sleep -seconds 2
            $timeout -= 2
        }
        if ($timeout -eq 0) {
            throw "Test case timed out waiting for VM to boot"
        }
        LogMsg "SSH port opened"
        if ($TestParams.Migrate) {
            $migrateResult= MigrateVM $VMName
            if (-not $migrateResult) {
                $testResult = $resultFail
                throw "Migration failed"
            }
            #
            # Check if Secure boot settings are in place after migration
            #
            $firmwareSettings = Get-VMFirmware -VMName $VMName
            if ($firmwareSettings.SecureBoot -ne "On") {
                $testResult = $resultFail
                throw "Secure boot settings changed"
            }
            #
            # Test network connectivity after migration ends
            #
            $pingObject = New-Object System.Net.NetworkInformation.Ping
            if (-not $pingObject) {
                throw "Unable to create a ping object"
            }
            $pingReply = $pingObject.Send($Ipv4)
            if ($pingReply.Status -ne "Success") {
                throw "Cannot ping $VMName. Status = $($pingReply.Status)"
            }
            LogMsg "Ping reply after migration - $($pingReply.Status)"

        }
        if ($TestParams.updateKernel) {
            $updateResult = UpdateKernel $Ipv4 $VMPort
            if (-not $updateResult) {
                $testResult = $resultFail
                throw "UpdateKernel failed"
            }
            else {
                LogMsg "Success: Update kernel"
            }
            LogMsg "Shutdown VM ${VMName}"
            $vm | Stop-VM
            if (-not $?) {
                throw "Unable to Shut Down VM"
            }
            $timeout = 180
            $sts = Wait-ForVMToStop $VMName $HvServer $timeout
            if (-not $sts) {
                throw "WaitForVMToStop fail"
            }
            LogMsg "Starting VM ${VMName}"
            Start-VM -Name $VMName -ComputerName $HvServer -ErrorAction SilentlyContinue
            if (-not $?) {
                throw "unable to start the VM"
            }
            $sleepPeriod = 60 #seconds
            Start-Sleep -s $sleepPeriod
            #
            # Check heartbeat
            #
            $heartbeat = Get-VMIntegrationService -VMName $VMName -Name "HeartBeat"
            if ($heartbeat.Enabled) {
                LogMsg "$VMName heartbeat detected"
            }
            else {
                throw "$VMName heartbeat not detected"
            }
            #
            # Test network connectivity
            #
            $pingObject = New-Object System.Net.NetworkInformation.Ping
            if (-not $pingObject) {
                throw "Unable to create a ping object"
            }
            $pingReply = $pingObject.Send($Ipv4)
            if ($pingReply.Status -ne "Success") {
                throw "Cannot ping $VMName. Status = $($pingReply.Status)"
            }
            LogMsg "Ping reply - $($pingReply.Status)"
            #
            # Waiting for the VM to run again and respond to SSH - port 22
            #
            $timeout = 500
            while ($timeout -gt 0) {
                if ( (Test-TCP $Ipv4 $VMPort) -eq "True" ) {
                    break
                }
                Start-Sleep -seconds 2
                $timeout -= 2
            }
            if ($timeout -eq 0) {
                throw "Test case timed out waiting for VM to boot"
            }
            LogMsg "SSH port opened"
        }
        if( $testResult -ne $resultFail) {
            $testResult=$resultPass
        }
    } catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        LogErr "$ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = $resultAborted
        }
        $resultArr += $testResult
    }
    $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}
Main -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n"))
