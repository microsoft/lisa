############################################################################
#
# setupSshKeys.ps1
#
# Description: Script for copying and setting up ssh keys in the
# VM
############################################################################
#Script Parameters
#
#IP adress of the VM
#Password
#########################################################################
param([string] $vmname, [string] $ipAddress, [string] $passwd, [string] $LISTarball)

Import-Module .\TestLibs\RDFELibstemp.psm1 -Force

###########################################################################

if ($ipAddress -eq $null -or $ipAddress.Length -eq 0)
{
    LogMsg "Error:IP Address is null"
    return $false
}

if ($passwd -eq $null -or $passwd.Length -eq 0)
{
    LogMsg "Error:Incorrect password"
    return $false
}



################################################################

#Creating directory .ssh in VM. Do nothing if already exist.

function UnwantedCode1()
{

echo y|.\tools\plink -pw $passwd root@"$ipAddress" "mkdir -p .ssh"

if($?)
{
    
    LogMsg "Created directory .ssh"
    
}
else 
{  LogMsg "Error:Failed to create .ssh directory"
    return $false
}


#Copying all ssh keys in \ica\ssh folder in .ssh directory of VM


LogMsg "Copying ssh keys to /root/.ssh"
echo y|.\tools\pscp -pw $passwd .\ssh\* root@"$ipAddress":/root/.ssh/ > $null


if($?)
{
    LogMsg "ssh keys are copied to /root/.ssh"
}

else
{
    LogMsg "Error:Failed to copy ssh keys"
    return $false
}
#Adding all ssh keys in file .ssh/authorized_keys

LogMsg "Adding ssh keys to authorized_keys"
tools\plink -pw $passwd root@"$ipAddress" "cat .ssh/rhel5_id_rsa.pub >> .ssh/authorized_keys"
tools\plink -pw $passwd root@"$ipAddress" "cat .ssh/ica_repos_id_rsa >> .ssh/authorized_keys"


#Changing mode of all ssh keys in VM to 600

LogMsg "Changing mode of ssh keys to 600"
tools\plink -pw $passwd root@"$ipAddress" "chmod 600 .ssh/*"



#Copying VHD preparation scripts - ICA_VMSetup.sh, Install-LIS.sh, Install-waagent.sh in VM for installing all required packages

LogMsg "Copying VHD preparation scripts - ICA_VMSetup.sh, Install-LIS.sh, Install-waagent.sh to VM"
tools\pscp -pw $passwd .\remote-scripts\*.sh root@"$ipAddress":/root

if($?)
   { LogMsg "VHD preparation scripts - ICA_VMSetup.sh, Install-LIS.sh, Install-waagent.sh copied to VM"}
else
    { LogMsg "Error : Failed to copy VHD preparation scripts - ICA_VMSetup.sh, Install-LIS.sh, Install-waagent.sh" 
      return $false
    }




#Copying setup for git,lcov, icadaemon and LIS
LogMsg "Copying setup for git,lcov, icadaemon"
tools\pscp -pw $passwd .\tools\VMSetup\* root@"$ipAddress":/root
if($?)
    { LogMsg "setup for git,lcov, icadaemon copied to the VM" }
else
    { LogMsg "Error:Failed to copy setup for git,lcov, icadaemon"
      return $false
    }

#Setting execute bit on all the Bash scripts
LogMsg "Setting execute bit on all the Bash scripts"

tools\plink -pw $passwd root@"$ipAddress" chmod +x /root/dos2unix.py
tools\plink -pw $passwd root@"$ipAddress" chmod +x /root/*.sh

tools\plink -pw $passwd root@"$ipAddress" ./dos2unix.py
if(!$?)
{
    LogMsg "Error: Failed to install dos2unix"
    return $false
}
tools\plink -pw $passwd root@"$ipAddress"   dos2unix -q ./*.sh



#Copying LIS tarball
LogMsg "Copying LIS tarball..."
tools\pscp -pw $passwd .\LIS\$LISTarball root@"$ipAddress":/root

if($?)
    { LogMsg "LIS tarball copied to the VM" }
else
    { 
        LogMsg "Error:Failed to copy LIS tarball"
        
    }

#Copying waagent setup
LogMsg "Copying waagent setup..."
tools\pscp -pw $passwd .\waagent\agent.py root@"$ipAddress":/root

if($?)
    { LogMsg "waagent setup copied to the VM" }
else
    { LogMsg "Error:Failed to copy waagent setup"
        return $false
    }
    

}


#Running ICA_VMSetup.sh

LogMsg "Invoking VHD preparation scripts"

#v-shisav : applying changes here..

$isAllPackagesInstalled = InstallPackages -localVMIp $ipAddress
#Invoke-Expression $command


Function UnwantedCode2()
{
#Running Install-LIS.sh

LogMsg "LIS Installation : .\tools\plink -pw $passwd root@$ipAddress ./Install-LIS.sh"
tools\plink -pw $passwd root@$ipAddress "./Install-LIS.sh  >> ./VHD_Provision.log"
#Invoke-Expression $command
if(!$?)
{
    LogMsg "LIS Installation failed"
   
    return $false 
}

LogMsg "LIS Installation successfull..."


LogMsg "NextAction : waagent installation"



#Running Install-waagent.sh
tools\plink -pw $passwd root@$ipAddress "./Install-waagent.sh  >> ./VHD_Provision.log "
#Invoke-Expression $command

if(!$?)
{
    LogMsg "waagent Installation failed"
    return $false
}

LogMsg "waagent Installation successfull..."

}

<#LogMsg "NextAction : Verify waagent installation"

#Verification of waagent installation
tools\plink -pw $passwd root@"$ipAddress" ./Verify-waagent.sh
if(!$?)
{
    LogMsg "Error : waagent is not installed..!!"
    return $false
}
#>

