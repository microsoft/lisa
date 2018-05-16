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

param([string] $Setup, [string] $Distro)

$xmlConfig = [XML](Get-Content .\XML\Azure_ICA.xml)
Import-Module .\TestLibs\RDFELibs.psm1 -Force
<#$ExistingServices = Get-AzureService 
$i = 0
$setupType = $Setup
$setupTypeData = $xml.config.Azure.Deployment.$setupType


###############################################################################
# EXTRACT THE VM INFORMATION FROM XML FILE
###############################################################################

#...............................................
# LIST OUT THE TOTAL MACHINES TO BE DEPLOYED ...
#'''''''''''''''''''''''''''''''''''''''''''''''
$role = 1
<#
Function CreateAllDeployments($setupTypeData)
{
    $hostedServiceCount = 0
    $allsetupServices = $setupTypeData
    if ($allsetupServices.HostedService[0].Location -or $allsetupServices.HostedService[0].AffinityGroup)
    {
    $isMultiple = 'True'
    $hostedServiceCount = 0
    }
    else
    {
    $isMultiple = 'False'
    }

    foreach ($newDistro in $xml.config.Azure.Deployment.Data.Distro)
    {
    if ($newDistro.Name -eq $Distro)
        {
        $osImage = $newDistro.OsImage

        }
    }

    $curtime = Get-Date
    foreach ($HS in $setupTypeData.HostedService )
    {
        $isServiceDeployed = "False"
        $retryDeployment = 0
            $serviceName = "ICA-" + $setupType + "-" + $Distro + "-" + $curtime.Month + "-" +  $curtime.Day  + "-" + $curtime.Year
            if($isMultiple -eq "True")
            {
            $serviceName = $serviceName + "-" + $hostedServiceCount
            }
            $location = $HS.Location
            $AffinityGroup = $HS.AffinityGroup
        
        while (($isServiceDeployed -eq "False") -and ($retryDeployment -lt 20))
        {
            LogMsg "Deleting any previous services....$retryDeployment"
            $isServiceDeleted = DeleteService -serviceName $serviceName
            #isServiceDeleted = "True"
            if ($isServiceDeleted -eq "True")
                {
                $isServiceCreated = CreateService -serviceName $serviceName -location $location -AffinityGroup $AffinityGroup
                #$isServiceCreated = "True"
                if ($isServiceCreated -eq "True")
                    {
                    $isCertAdded = AddCertificate -serviceName $serviceName
                    #$isCertAdded = "True"
                    if ($isCertAdded -eq "True")
                        {
                        $DeploymentCommand = GenerateCommand -Setup $Setup -serviceName $serviceName -osImage $osImage -HSData $HS
                        LogMsg $DeploymentCommand
                        $isDeployed = CreateDeployment -DeploymentCommand $DeploymentCommand
                        #$isDeployed = "True"
                        if ( $isDeployed -eq "True" )
                            {
                            LogMsg "Deployment Created!" -ForegroundColor Green
                            $retValue = "True"
                            $isServiceDeployed = "True"
                            $hostedServiceCount = $hostedServiceCount + 1
                            if ($hostedServiceCount -eq 1)
                                {
                                $deployedServices = $serviceName
                                }
                            else
                                {
                                $deployedServices = $deployedServices + "^" + $serviceName
                                }

                            }
                        else
                            {
                            LogMsg "Unable to Deploy one or more VM's"
                            $retryDeployment = $retryDeployment + 1
                            $retValue = "False"
                            $isServiceDeployed = "False"
                            }
                        }
                    else
                        {
                        LogMsg "Unable to Add certificate to $serviceName"
                        $retryDeployment = $retryDeployment + 1
                        $retValue = "False"
                        $isServiceDeployed = "False"
                        }
                        
                    }
            else
                    {
                    LogMsg "Unable to create $serviceName"
                    $retryDeployment = $retryDeployment + 1
                    $retValue = "False"
                    $isServiceDeployed = "False"
                    }
                }    
            else
                {
                LogMsg "Unable to delete existing service - $serviceName"
                $retryDeployment = $retryDeployment + 1
                $retValue = "False"
                $isServiceDeployed = "False"
                }
            
        }
    }
    return $retValue, $deployedServices
}



Function VerifyAllDeployments([string]$servicesToVerify)
{
    
    $deployedServices = $servicesToVerify.Split('^')

    LogMsg "Sleeping 10 seconds to VM to start.." -ForegroundColor Yellow
    sleep(10)
    LogMsg "Waiting for VM(s) to become Ready." -ForegroundColor Yellow
    foreach ($service in  $deployedServices)
    {
        $serviceName = $service
        $isDeploymentReady = CheckVMsInService ($serviceName)
        if ($isDeploymentReady -eq "True")
            {
            LogMsg ""
            LogMsg "$serviceName is Ready.." -ForegroundColor Green
            $retValue = "True"
            }
            else
            {
            LogMsg "$serviceName Failed.." -ForegroundColor Red
            $retValue = "False"
            }
    }

    return $retValue
}

################################################################################################################################
#   Main program 
################################################################################################################################

#Function DeployVMs ($xmlConfig, $setupType, $distro)

    $isAllDeployed = CreateAllDeployments -xmlConfig $xmlConfig -setupType $Setup -Distro $Distro
    if($isAllDeployed[0] -eq "True")
    {
        $deployedServices = $isAllDeployed[1]
        $servicesToVerify = $deployedServices.Split('^')
        $isAllVerified = VerifyAllDeployments -servicesToVerify $servicesToVerify 
        if ($isAllVerified -eq "True")
            {
            	Set-Content .\temp\DeployedServicesFile.txt "$deployedServices"
            }
	    else
    	    {
            #futureUse
            }

    }
    else
    {
        LogMsg "One or More Deployments are Failed..!"
    }


#>

DeployVMs -xmlConfig $xmlConfig -setupType $Setup -Distro $Distro