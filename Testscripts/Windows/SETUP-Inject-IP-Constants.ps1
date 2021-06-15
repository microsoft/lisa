# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Description
    This script sends the IP constants of a test the dependency VM to
    the test VM. It can be used as a pretest in case the main test
    consists of a remote-script. It can be used with the main Linux
    distributions. For the time being it is customized for use with
    the Networking tests.
#>

param([string] $TestParams, [object] $AllVMData)

function Main {
    param (
        $VMName,
        $HvServer,
        $VMPort,
        $VMUserName,
        $VMPassword
    )
    $nic = $False
    $switchType = $False
    $addressFamily = "IPv4"
    $testMAC = "no"
    $remoteServer = "8.8.4.4"

    $params = $TestParams.Split(";")
    foreach ($p in $params) {
        $fields = $p.Split("=")
        switch ($fields[0].Trim()) {
            "AddressFamily" {$addressFamily = $fields[1].Trim()}
            "SWITCH" {$switchType = $fields[1].Trim()}
            "TestMAC" {$testMAC= $fields[1].Trim()}
            "VM2Name" {$VM2Name = $fields[1].Trim()}
            default {}
        }
        if ($fields[0].Trim() -match "NIC_") {
            $nic = $fields[1].Trim()
        }
    }


    $ipv4 = Start-VMandGetIP $VMName $HvServer $VMPort $VMUserName $VMPassword
    if (-not $ipv4) {
        Write-LogErr "Could not retrieve test VM's test IP address"
        return $False
    }

    if (-not $addressFamily) {
        Write-LogErr "AddressFamily variable not defined"
        return $False
    }

    if ($nic){
        $testType = $nic.split(',')[1]
    }

    if ($switchType){
        $testType = $switchType.split(',')[1]
    }

    if ($addressFamily -eq "IPv4") {
        $externalIP = $remoteServer
        $privateIP = "10.10.10.5"
    } else {
        $externalIP = "2001:4860:4860::8888"
        $privateIP = "fd00::4:10"
    }

    $interfaces = (Invoke-Command -ComputerName $HvServer {Get-NetIPAddress -addressFamily $Using:addressFamily})
    foreach ($interface in $interfaces) {
        if ($interface.InterfaceAlias -like "*(Internal)*") {
            break
        }
    }
    $internalIP = $interface.IPAddress.split("%")[0]

    $cmd=""
    switch ($testType) {
        "Internal" {
            $PING_SUCC=$internalIP
            $PING_FAIL=$externalIP
            $PING_FAIL2=$privateIP
            $STATIC_IP = Generate-IPv4 $PING_SUCC
            $NETMASK = Convert-CIDRtoNetmask $interface.PrefixLength

        }
        "External" {
            $PING_SUCC=$externalIP
            $PING_FAIL=$internalIP
            $PING_FAIL2=$privateIP
        }
        "Private" {
            $PING_SUCC=$privateIP
            $PING_FAIL=$externalIP
            $PING_FAIL2=$internalIP

            if ($addressFamily -eq "IPv4") {
                $STATIC_IP= Generate-IPv4 $PING_SUCC
                $STATIC_IP2= Generate-IPv4 $PING_SUCC $STATIC_IP
                $NETMASK="255.255.255.0"
            } else {
                $STATIC_IP="fd00::4:10"
                $STATIC_IP2="fd00::4:100"
                $NETMASK=64
            }
        }
        {($_ -eq "Internal") -or ($_ -eq "Private")} {
            $cmd+="echo `'STATIC_IP=$($STATIC_IP)`' >> /home/$VMUserName/net_constants.sh;";
            $cmd+="echo `'STATIC_IP2=$($STATIC_IP2)`' >> /home/$VMUserName/net_constants.sh;";
            $cmd+="echo `'NETMASK=$($NETMASK)`' >> /home/$VMUserName/net_constants.sh;";
        }
        default {}
    }

    $cmd+="echo `'PING_SUCC=$($PING_SUCC)`' >> /home/$VMUserName/net_constants.sh;";
    $cmd+="echo `'PING_FAIL=$($PING_FAIL)`' >> /home/$VMUserName/net_constants.sh;";
    $cmd+="echo `'PING_FAIL2=$($PING_FAIL2)`' >> /home/$VMUserName/net_constants.sh;";
    $cmd+="echo `'ipv4=$($ipv4)`' >> /home/$VMUserName/net_constants.sh;";

    if ($testMAC -eq "yes") {
        # Get the MAC that was generated
        $CurrentDir= "$pwd\"
        $testfile = "macAddress.file"
        $pathToFile="$CurrentDir"+"$testfile"
        $streamReader = [System.IO.StreamReader] $pathToFile
        $macAddress = $streamReader.ReadLine()
        $streamReader.close()

        for ($i = 2 ; $i -le 14 ; $i += 3) {
            $macAddress = $macAddress.insert($i,':')
        }

        # Send the MAC address to the VM
        $cmd+="echo `'MAC=$($macAddress)`' >> /home/$VMUserName/net_constants.sh;";
    }

    Write-LogInfo "PING_SUCC=$PING_SUCC"
    Write-LogInfo "PING_FAIL=$PING_FAIL"
    Write-LogInfo "PING_FAIL2=$PING_FAIL2"

    if ($testType -eq "Internal") {
        "STATIC_IP=$STATIC_IP"
        "NETMASK=$NETMASK"
    }

    if ($testType -eq "Private") {
        "STATIC_IP=$STATIC_IP"
        "STATIC_IP2=$STATIC_IP2"
        "NETMASK=$NETMASK"
    }

    # If vm2name is present, set up ssh login
    if ($VM2Name) {
        $cmd+="echo `'SSH_PRIVATE_KEY=id_rsa`' >> /home/$VMUserName/net_constants.sh;";
        $vm2ipv4 = Get-IPv4ViaKVP $VM2Name $HvServer
        # Setup ssh on VM1
        Copy-RemoteFiles -uploadTo $Ipv4 -port $VMPort -files `
            ".\Testscripts\Linux\utils.sh,.\Testscripts\Linux\enable_passwordless_root.sh,.\Testscripts\Linux\enable_root.sh" `
            -username $VMUserName -password $VMPassword -upload
        Copy-RemoteFiles -uploadTo $vm2ipv4 -port $VMPort -files `
            ".\Testscripts\Linux\utils.sh,.\Testscripts\Linux\enable_passwordless_root.sh,.\Testscripts\Linux\enable_root.sh" `
            -username $VMUserName -password $VMPassword -upload
        Run-LinuxCmd -ip $Ipv4 -port $VMPort -username $VMUserName -password `
            $VMPassword -command "chmod +x /home/$VMUserName/*.sh" -runAsSudo
        Run-LinuxCmd -ip $vm2ipv4 -port $VMPort -username $VMUserName -password `
            $VMPassword -command "chmod +x /home/$VMUserName/*.sh" -runAsSudo
        $null = Run-LinuxCmd -ip $Ipv4 -port $VMPort -username $VMUserName -password `
            $VMPassword -command "/home/$VMUserName/enable_root.sh -password $VMPassword" -runAsSudo
        $null = Run-LinuxCmd -ip $vm2ipv4 -port $VMPort -username $VMUserName -password `
            $VMPassword -command "/home/$VMUserName/enable_root.sh -password $VMPassword" -runAsSudo
        $null = Run-LinuxCmd -ip $Ipv4 -port $VMPort -username $VMUserName -password `
            $VMPassword -command "./enable_passwordless_root.sh /home/$VMUserName ; cp -rf /root/.ssh /home/$VMUserName" -runAsSudo
        # Copy keys from VM1 and setup VM2
        Copy-RemoteFiles -download -downloadFrom $Ipv4 -port $VMPort -files `
            "/home/$VMUserName/sshFix.tar" -username $VMUserName -password $VMPassword -downloadTo $LogDir
        Copy-RemoteFiles -uploadTo $vm2ipv4 -port $VMPort -files "$LogDir\sshFix.tar" `
            -username $VMUserName -password $VMPassword -upload
        $null = Run-LinuxCmd -ip $vm2ipv4 -port $VMPort -username $VMUserName -password `
            $VMPassword -command "./enable_passwordless_root.sh /home/$VMUserName ; cp -rf /root/.ssh /home/$VMUserName" -runAsSudo
    }

    Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $ipv4 -port $VMPort `
        -command $cmd -runAsSudo
    if (-not $?) {
        Write-LogErr "Unable to submit ${cmd} to vm"
        return $False
    }
    Write-LogInfo "Test IP parameters successfully added to constants file"
    return $true
}

Main -VMName $AllVMData.RoleName -hvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
    -VMPort $AllVMData.SSHPort -VMUserName $user -VMPassword $password
