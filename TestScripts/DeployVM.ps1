# FileName: DeployVM.ps1
# =============================================================================
# CREATE DEPLOYMENTS
# =============================================================================
# Created: [31/OCT/2012]
# Author: 
# Arguments:
# Contact - v-shisav@microsoft.com
# =============================================================================
# Purpose: Creates Virtual Machines According to test bed setup
#
#
# =============================================================================
# =============================================================================
# ToBeDone: 
# # Add - Load Balanced port to system
# =============================================================================



###############################################################################
# REMOVE HOSTED SERVICE IF ALREADY EXISTS
###############################################################################

$xml=[xml](get-content .\XML\Azure_ICA.xml )
$ExistingServices = Get-AzureService 
$location = "West US"
$i = 0

foreach( $object1 in $xml.config.Azure.Deployment.PublicEndpoint)
{
    $serviceName = $xml.config.Azure.Deployment.PublicEndpoint.HostedService.Name
    $j = 0
    foreach ( $object2 in $ExistingServices )
    {
        if( $ExistingServices[$j].ServiceName -eq $serviceName )
        {
            Write-Host $serviceName '..service Already Exists!'
            Write-Host 'Warning : Deleting All Virtual Machines in service in 10 seconds. Interrupt to break..' -ForegroundColor Red
            $counter = 10
            while ($counter -ge 0 )
            {
                Write-Host "$counter " -NoNewline
                $counter = $counter - 1
                sleep(1)
            }
            Remove-AzureService -ServiceName $ExistingServices[$j].ServiceName -Force
        }
    $j = $j + 1
    }

$i = $i + 1
}

    #...............................................
    # NOW FIRST CREATE THE HOSTED SERVICE
    #'''''''''''''''''''''''''''''''''''''''''''''''
    Write-Host 'Creating new Hosted Service ' $serviceName ' ...'
    New-AzureService -ServiceName $serviceName -Location $location

###############################################################################
# EXTRACT THE VM INFORMATION FROM XML FILE
###############################################################################



    #...............................................
    # LIST OUT THE TOTAL MACHINES TO BE DEPLOYED ...
    #'''''''''''''''''''''''''''''''''''''''''''''''
    $role = 1

    $defaultuser = $xml.config.Azure.Deployment.PublicEndpoint.HostedService.VirtualMachine.UserName
    $defaultPassword = $xml.config.Azure.Deployment.PublicEndpoint.HostedService.VirtualMachine.Password
    $location = "West US"
    $osImage = $xml.config.Azure.Deployment.PublicEndpoint.HostedService.VirtualMachine.OsImage
    
    $instanceSize = $xml.config.Azure.Deployment.PublicEndpoint.HostedService.VirtualMachine.InstanceSize
    $portCommand = ""
    
    $portNo = 0

    #...............................................
    # LIST OUT THE TOTAL PORTS TO BE OPENED AND ADD THEM ACCORDINGLY...
    #'''''''''''''''''''''''''''''''''''''''''''''''
    foreach ( $object2 in $xml.config.Azure.Deployment.PublicEndpoint.HostedService.VirtualMachine.EndPoints)
    {
        if($xml.config.Azure.Deployment.PublicEndpoint.HostedService.VirtualMachine.EndPoints[$portNo].Name -eq "SSH")
        {
            $Name = $xml.config.Azure.Deployment.PublicEndpoint.HostedService.VirtualMachine.EndPoints[$portNo].Name
            $Protocol = $xml.config.Azure.Deployment.PublicEndpoint.HostedService.VirtualMachine.EndPoints[$portNo].Protocol
            $LocalPort = $xml.config.Azure.Deployment.PublicEndpoint.HostedService.VirtualMachine.EndPoints[$portNo].LocalPort
            $PublicPort =  $xml.config.Azure.Deployment.PublicEndpoint.HostedService.VirtualMachine.EndPoints[$portNo].PublicPort
            $portCommand =  $portCommand + "Set-AzureEndpoint -Name `"$Name`" -LocalPort $LocalPort -PublicPort $PublicPort -Protocol `"$Protocol`"" + " | "
            
        }
        else
        {
            $Name = $xml.config.Azure.Deployment.PublicEndpoint.HostedService.VirtualMachine.EndPoints[$portNo].Name
            $Protocol = $xml.config.Azure.Deployment.PublicEndpoint.HostedService.VirtualMachine.EndPoints[$portNo].Protocol
            $LocalPort = $xml.config.Azure.Deployment.PublicEndpoint.HostedService.VirtualMachine.EndPoints[$portNo].LocalPort
            $PublicPort =  $xml.config.Azure.Deployment.PublicEndpoint.HostedService.VirtualMachine.EndPoints[$portNo].PublicPort
            $portCommand =  $portCommand + "Add-AzureEndpoint -Name `"$Name`" -LocalPort $LocalPort -PublicPort $PublicPort -Protocol `"$Protocol`"" + " | "
        }
    $portNo = $portNo + 1
    }
    #...............................................
    # NOW ADD DEPLOYMENT TO HOSTED SERVICE
    #'''''''''''''''''''''''''''''''''''''''''''''''
    $vmName = $serviceName +"-role-"+$role
    $sshPath = '/home/' + $defaultuser + '/.ssh/authorized_keys'
    Add-AzureCertificate -CertToDeploy '.\ssh\myCert.cer' -ServiceName $serviceName
    sleep(3)
    LogMsg "Adding Deployment $vmName"
    LogMsg "New-AzureVMConfig -Name $vmName -InstanceSize $instanceSize -ImageName $osImage | Add-AzureProvisioningConfig –Linux –LinuxUser $defaultuser -Password $defaultPassword -SSHPublicKeys (New-AzureSSHKey -PublicKey -Fingerprint 690076D4C41C1DE677CD464EA63B44AE94C2E621 -Path $sshPath) | " + $portCommand + "New-AzureVM -ServiceName $serviceName"
    $finalCommand = "New-AzureVMConfig -Name $vmName -InstanceSize $instanceSize -ImageName $osImage | Add-AzureProvisioningConfig –Linux –LinuxUser $defaultuser -Password $defaultPassword -SSHPublicKeys (New-AzureSSHKey -PublicKey -Fingerprint 690076D4C41C1DE677CD464EA63B44AE94C2E621 -Path $sshPath) | " + $portCommand + "New-AzureVM -ServiceName $serviceName"
    Invoke-Expression $finalCommand
    if(!$?)
    {
        LogMsg "Error:Failed to create Azure VM"
        LogMsg "Error : Deployment failed"
    }

    LogMsg "Deployment Created Successfully"
    
    
    sleep(10)