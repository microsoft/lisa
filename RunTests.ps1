##############################################################################################
# RunTests.ps1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
	<Description>

.PARAMETER
	This script launches AutomationManager.ps1 remotely.

.INPUTS
    Set all ENV parameters
    $xmlFile is constructed
    Start AutomationManager.ps1
    Read report_test.xml file.

.NOTES
    Creation Date:  
    Purpose/Change: 

.EXAMPLE


#>
###############################################################################################

[CmdletBinding()]
Param(
    #Do not use. Reserved for Jenkins use.
    $BuildNumber=$env:BUILD_NUMBER,

    #[Required]
    [ValidateSet('Azure','HyperV')]
    [string] $TestPlatform = "",

    #[Required] for Azure.
    [string] $TestLocation="",
    [string] $RGIdentifier = "",
    [string] $ARMImageName = "",
    [string] $StorageAccount="",

    #[Required] for HyperV

    #[Required] Common for HyperV and Azure.
    [string] $OsVHD = "",   #... [Azure: Required only if -ARMImageName is not provied.]
                            #... [HyperV: Mandatory]
    [string] $TestCategory = "",
    [string] $TestArea = "",
    [string] $TestTag = "",
    [string] $TestNames="",

    #[Optional] Parameters for Image preparation before running tests.
    [string] $CustomKernel = "",
    [string] $CustomLIS,

    #[Optional] Parameters for changing framework behaviour.
    [string] $CoreCountExceededTimeout,
    [int]    $TestIterations,
    [string] $TiPSessionId,
    [string] $TiPCluster,
    [string] $XMLSecretFile = "",
    [switch] $EnableTelemetry,

    #[Optional] Parameters for dynamically updating XML files
    [switch] $UpdateGlobalConfigurationFromSecretsFile,
    [switch] $UpdateXMLStringsFromSecretsFile,

    #[Optional] Parameters for Overriding VM Configuration in Azure.
    [string] $OverrideVMSize = "",
    [switch] $EnableAcceleratedNetworking,
    [string] $OverrideHyperVDiskMode = "",
    [switch] $ForceDeleteResources,
    [switch] $UseManagedDisks,
    [switch] $DoNotDeleteVMs,

    [string] $ResultDBTable = "",
    [string] $ResultDBTestTag = "",

    [switch] $ExitWithZero
)

#Import the Functinos from Library Files.
Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global }

try
{
    #region Prepare / Clean the powershell console.
    $MaxDirLength = 32
    $WorkingDirectory = Split-Path -parent $MyInvocation.MyCommand.Definition
    Set-Variable -Name shortRandomNumber -Value $(Get-Random -Maximum 99999 -Minimum 11111) -Scope Global
    Set-Variable -Name shortRandomWord -Value $(-join ((65..90) | Get-Random -Count 4 | ForEach-Object {[char]$_})) -Scope Global
    if ( $WorkingDirectory.Length -gt $MaxDirLength)
    {
        $OriginalWorkingDirectory = $WorkingDirectory
        Write-Host "Current working directory '$WorkingDirectory' length is greather than $MaxDirLength."
        $TempWorkspace = "$(Split-Path $OriginalWorkingDirectory -Qualifier)"
        New-Item -ItemType Directory -Path "$TempWorkspace\LISAv2" -Force -ErrorAction SilentlyContinue | Out-Null
        New-Item -ItemType Directory -Path "$TempWorkspace\LISAv2\$shortRandomWord$shortRandomNumber" -Force -ErrorAction SilentlyContinue | Out-Null
        $finalWorkingDirectory = "$TempWorkspace\LISAv2\$shortRandomWord$shortRandomNumber"
        $tmpSource = '\\?\' + "$OriginalWorkingDirectory\*"
        Write-Host "Copying current workspace to $finalWorkingDirectory"
        Copy-Item -Path $tmpSource -Destination $finalWorkingDirectory -Recurse -Force | Out-Null
        Set-Location -Path $finalWorkingDirectory | Out-Null
        Write-Host "Working directory has been changed to $finalWorkingDirectory"
        $WorkingDirectory = $finalWorkingDirectory
    }
     
    $ParameterList = (Get-Command -Name $PSCmdlet.MyInvocation.InvocationName).Parameters;
    foreach ($key in $ParameterList.keys)
    {
        $var = Get-Variable -Name $key -ErrorAction SilentlyContinue;
        if($var)
        {
            Set-Variable -Name $($var.name) -Value $($var.value) -Scope Global -Force
        }
    }
	$LogDir = ".\TestResults\$(Get-Date -Format 'yyyy-dd-MM-HH-mm-ss-ffff')"
	Set-Variable -Name LogDir -Value $LogDir -Scope Global -Force
	Set-Variable -Name RootLogDir -Value $LogDir -Scope Global -Force
	New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
	New-Item -ItemType Directory -Path Temp -Force -ErrorAction SilentlyContinue | Out-Null
	LogMsg "Created LogDir: $LogDir"
    #endregion

    #region Static Global Variables
    Set-Variable -Name WorkingDirectory -Value $WorkingDirectory  -Scope Global
    #endregion

    #region Runtime Global Variables
    if ( $Verbose )
    {
        $VerboseCommand = "-Verbose"
        Set-Variable -Name VerboseCommand -Value "-Verbose" -Scope Global
    }
    else
    {
        Set-Variable -Name VerboseCommand -Value "" -Scope Global
    }
    #endregion

    #Validate the test parameters.
    ValidateParameters

    ValiateXMLs -ParentFolder $WorkingDirectory

    UpdateGlobalConfigurationXML

    UpdateXMLStringsFromSecretsFile

    #region Local Variables
    $TestXMLs = Get-ChildItem -Path "$WorkingDirectory\XML\TestCases\*.xml"
    $SetupTypeXMLs = Get-ChildItem -Path "$WorkingDirectory\XML\VMConfigurations\*.xml"
    $allTests = @()
    $ARMImage = $ARMImageName.Split(" ")
    $xmlFile = "$WorkingDirectory\TestConfiguration.xml"
    if ( $TestCategory -eq "All")
    {
        $TestCategory = ""
    }
    if ( $TestArea -eq "All")
    {
        $TestArea = ""
    }
    if ( $TestNames -eq "All")
    {
        $TestNames = ""
    }
    if ( $TestTag -eq "All")
    {
        $TestTag = ""
    }
    #endregion

    #Validate all XML files in working directory.
    $allTests = CollectTestCases -TestXMLs $TestXMLs
    
    #region Create Test XML
    $SetupTypes = $allTests.SetupType | Sort-Object | Get-Unique

    $tab = CreateArrayOfTabs

    $TestCycle = "TC-$shortRandomNumber"

    $GlobalConfiguration = [xml](Get-content .\XML\GlobalConfigurations.xml)
    <##########################################################################
    We're following the Indentation of the XML file to make XML creation easier.
    ##########################################################################>
    $xmlContent =  ("$($tab[0])" + '<?xml version="1.0" encoding="utf-8"?>')
    $xmlContent += ("$($tab[0])" + "<config>`n") 
    $xmlContent += ("$($tab[0])" + "<CurrentTestPlatform>$TestPlatform</CurrentTestPlatform>`n") 
    if ($TestPlatform -eq "Azure")
    {
        $xmlContent += ("$($tab[1])" + "<Azure>`n") 

            #region Add Subscription Details
            $xmlContent += ("$($tab[2])" + "<General>`n")
            
            foreach ( $line in $GlobalConfiguration.Global.$TestPlatform.Subscription.InnerXml.Replace("><",">`n<").Split("`n"))
            {
                $xmlContent += ("$($tab[3])" + "$line`n")
            }
            $xmlContent += ("$($tab[2])" + "<Location>$TestLocation</Location>`n") 
            $xmlContent += ("$($tab[2])" + "</General>`n")
            #endregion

            #region Database details
            $xmlContent += ("$($tab[2])" + "<database>`n")
                foreach ( $line in $GlobalConfiguration.Global.$TestPlatform.ResultsDatabase.InnerXml.Replace("><",">`n<").Split("`n"))
                {
                    $xmlContent += ("$($tab[3])" + "$line`n")
                }
            $xmlContent += ("$($tab[2])" + "</database>`n")
            #endregion

            #region Deployment details
            $xmlContent += ("$($tab[2])" + "<Deployment>`n")
                $xmlContent += ("$($tab[3])" + "<Data>`n")
                    $xmlContent += ("$($tab[4])" + "<Distro>`n")
                        $xmlContent += ("$($tab[5])" + "<Name>$RGIdentifier</Name>`n")
                        $xmlContent += ("$($tab[5])" + "<ARMImage>`n")
                            $xmlContent += ("$($tab[6])" + "<Publisher>" + "$($ARMImage[0])" + "</Publisher>`n")
                            $xmlContent += ("$($tab[6])" + "<Offer>" + "$($ARMImage[1])" + "</Offer>`n")
                            $xmlContent += ("$($tab[6])" + "<Sku>" + "$($ARMImage[2])" + "</Sku>`n")
                            $xmlContent += ("$($tab[6])" + "<Version>" + "$($ARMImage[3])" + "</Version>`n")
                        $xmlContent += ("$($tab[5])" + "</ARMImage>`n")
                        $xmlContent += ("$($tab[5])" + "<OsVHD>" + "$OsVHD" + "</OsVHD>`n")
                    $xmlContent += ("$($tab[4])" + "</Distro>`n")
                    $xmlContent += ("$($tab[4])" + "<UserName>" + "$($GlobalConfiguration.Global.$TestPlatform.TestCredentials.LinuxUsername)" + "</UserName>`n")
                    $xmlContent += ("$($tab[4])" + "<Password>" + "$($GlobalConfiguration.Global.$TestPlatform.TestCredentials.LinuxPassword)" + "</Password>`n")
                $xmlContent += ("$($tab[3])" + "</Data>`n")
                
                foreach ( $file in $SetupTypeXMLs.FullName)
                {
                    foreach ( $SetupType in $SetupTypes )
                    {                    
                        $CurrentSetupType = ([xml]( Get-Content -Path $file)).TestSetup
                        if ( $CurrentSetupType.$SetupType -ne $null)
                        {
                            $SetupTypeElement = $CurrentSetupType.$SetupType
                            $xmlContent += ("$($tab[3])" + "<$SetupType>`n")
                                #$xmlContent += ("$($tab[4])" + "$($SetupTypeElement.InnerXml)`n")
                                foreach ( $line in $SetupTypeElement.InnerXml.Replace("><",">`n<").Split("`n"))
                                {
                                    $xmlContent += ("$($tab[4])" + "$line`n")
                                }
                                                
                            $xmlContent += ("$($tab[3])" + "</$SetupType>`n")
                        }
                    }
                }
            $xmlContent += ("$($tab[2])" + "</Deployment>`n")
            #endregion        
        $xmlContent += ("$($tab[1])" + "</Azure>`n")
    }   
    elseif ($TestPlatform -eq "Hyperv")
    {
        $xmlContent += ("$($tab[1])" + "<Hyperv>`n") 

            #region Add Subscription Details
            $xmlContent += ("$($tab[2])" + "<Host>`n")
            
            foreach ( $line in $GlobalConfiguration.Global.HyperV.Host.InnerXml.Replace("><",">`n<").Split("`n"))
            {
                $xmlContent += ("$($tab[3])" + "$line`n")
            }
            $xmlContent += ("$($tab[2])" + "</Host>`n")
            #endregion

            #region Database details
            $xmlContent += ("$($tab[2])" + "<database>`n")
                foreach ( $line in $GlobalConfiguration.Global.HyperV.ResultsDatabase.InnerXml.Replace("><",">`n<").Split("`n"))
                {
                    $xmlContent += ("$($tab[3])" + "$line`n")
                }
            $xmlContent += ("$($tab[2])" + "</database>`n")
            #endregion

            #region Deployment details
            $xmlContent += ("$($tab[2])" + "<Deployment>`n")
                $xmlContent += ("$($tab[3])" + "<Data>`n")
                    $xmlContent += ("$($tab[4])" + "<Distro>`n")
                        $xmlContent += ("$($tab[5])" + "<Name>$RGIdentifier</Name>`n")
                        $xmlContent += ("$($tab[5])" + "<ARMImage>`n")
                            $xmlContent += ("$($tab[6])" + "<Publisher>" + "$($ARMImage[0])" + "</Publisher>`n")
                            $xmlContent += ("$($tab[6])" + "<Offer>" + "$($ARMImage[1])" + "</Offer>`n")
                            $xmlContent += ("$($tab[6])" + "<Sku>" + "$($ARMImage[2])" + "</Sku>`n")
                            $xmlContent += ("$($tab[6])" + "<Version>" + "$($ARMImage[3])" + "</Version>`n")
                        $xmlContent += ("$($tab[5])" + "</ARMImage>`n")
                        $xmlContent += ("$($tab[5])" + "<OsVHD>" + "$OsVHD" + "</OsVHD>`n")
                    $xmlContent += ("$($tab[4])" + "</Distro>`n")
                    $xmlContent += ("$($tab[4])" + "<UserName>" + "$($GlobalConfiguration.Global.$TestPlatform.TestCredentials.LinuxUsername)" + "</UserName>`n")
                    $xmlContent += ("$($tab[4])" + "<Password>" + "$($GlobalConfiguration.Global.$TestPlatform.TestCredentials.LinuxPassword)" + "</Password>`n")
                $xmlContent += ("$($tab[3])" + "</Data>`n")
                
                foreach ( $file in $SetupTypeXMLs.FullName)
                {
                    foreach ( $SetupType in $SetupTypes )
                    {                    
                        $CurrentSetupType = ([xml]( Get-Content -Path $file)).TestSetup
                        if ( $CurrentSetupType.$SetupType -ne $null)
                        {
                            $SetupTypeElement = $CurrentSetupType.$SetupType
                            $xmlContent += ("$($tab[3])" + "<$SetupType>`n")
                                #$xmlContent += ("$($tab[4])" + "$($SetupTypeElement.InnerXml)`n")
                                foreach ( $line in $SetupTypeElement.InnerXml.Replace("><",">`n<").Split("`n"))
                                {
                                    $xmlContent += ("$($tab[4])" + "$line`n")
                                }
                                                
                            $xmlContent += ("$($tab[3])" + "</$SetupType>`n")
                        }
                    }
                }
            $xmlContent += ("$($tab[2])" + "</Deployment>`n")
            #endregion        
        $xmlContent += ("$($tab[1])" + "</Hyperv>`n")
    }    
        #region TestDefinition
        $xmlContent += ("$($tab[1])" + "<testsDefinition>`n")
        foreach ( $currentTest in $allTests)
        {
            if ($currentTest.Platform.Contains($TestPlatform))
            {
                $xmlContent += ("$($tab[2])" + "<test>`n")
                foreach ( $line in $currentTest.InnerXml.Replace("><",">`n<").Split("`n"))
                {
                    $xmlContent += ("$($tab[3])" + "$line`n")
                } 
                $xmlContent += ("$($tab[2])" + "</test>`n")
            }
            else 
            {
                LogErr "*** UNSUPPORTED TEST *** : $currentTest. Skipped."
            }
        }
        $xmlContent += ("$($tab[1])" + "</testsDefinition>`n")
        #endregion

        #region TestCycle
        $xmlContent += ("$($tab[1])" + "<testCycles>`n")
            $xmlContent += ("$($tab[2])" + "<Cycle>`n")
                $xmlContent += ("$($tab[3])" + "<cycleName>$TestCycle</cycleName>`n")
                foreach ( $currentTest in $allTests)
                {
                    $line = $currentTest.TestName
                    $xmlContent += ("$($tab[3])" + "<test>`n")
                        $xmlContent += ("$($tab[4])" + "<Name>$line</Name>`n")
                    $xmlContent += ("$($tab[3])" + "</test>`n")
                }
            $xmlContent += ("$($tab[2])" + "</Cycle>`n")
        $xmlContent += ("$($tab[1])" + "</testCycles>`n")
        #endregion
    $xmlContent += ("$($tab[0])" + "</config>`n") 
    Set-Content -Value $xmlContent -Path $xmlFile -Force

    try
    {
        $xmlConfig = [xml](Get-Content $xmlFile)
        $xmlConfig.Save("$xmlFile")
        LogMsg "Auto created $xmlFile validated successfully."
    }
    catch
    {
        Throw "Framework error: $xmlFile is not valid. Please report to lisasupport@microsoft.com"
    }

    #endregion

    #region Prepare execution command

    $command = ".\AutomationManager.ps1 -xmlConfigFile '$xmlFile' -cycleName 'TC-$shortRandomNumber' -RGIdentifier '$RGIdentifier' -runtests -UseAzureResourceManager"

    if ( $CustomKernel)
    {
        $command += " -CustomKernel '$CustomKernel'"
    }
    if ( $OverrideVMSize )
    {
        $command += " -OverrideVMSize $OverrideVMSize"
    }
    if ( $EnableAcceleratedNetworking )
    {
        $command += " -EnableAcceleratedNetworking"
    }
    if ( $ForceDeleteResources )
    {
        $command += " -ForceDeleteResources"
    }
    if ( $DoNotDeleteVMs )
    {
        $command += " -DoNotDeleteVMs"
    }
    if ( $CustomLIS)
    {
        $command += " -CustomLIS $CustomLIS"
    }
    if ( $CoreCountExceededTimeout )
    {
        $command += " -CoreCountExceededTimeout $CoreCountExceededTimeout"
    }
    if ( $TestIterations -gt 1 )
    {
        $command += " -TestIterations $TestIterations"
    }
    if ( $TiPSessionId)
    {
        $command += " -TiPSessionId $TiPSessionId"
    }
    if ( $TiPCluster)
    {
        $command += " -TiPCluster $TiPCluster"
    }
    if ($UseManagedDisks)
    {
        $command += " -UseManagedDisks"
    }
    if ($XMLSecretFile)
    {
        $command += " -XMLSecretFile '$XMLSecretFile'"
    }

    LogMsg $command
    Invoke-Expression -Command $command
    #$out = Remove-Item *.json -Force
    #$out = Remove-Item *.xml -Force
    $zipFile = "$TestPlatform"
    if ( $TestCategory )
    {
        $zipFile += "-$TestCategory"
    }
    if ( $TestArea )
    {
        $zipFile += "-$TestArea"
    }
    if ( $TestTag )
    {
        $zipFile += "-$($TestTag)"
    }
    $zipFile += "-$shortRandomNumber-buildlogs.zip"
    $out = ZipFiles -zipfilename $zipFile -sourcedir $LogDir

    try
    {
        if (Test-Path -Path ".\report\report_$(($TestCycle).Trim()).xml" )
        {
            $resultXML = [xml](Get-Content ".\report\report_$(($TestCycle).Trim()).xml" -ErrorAction SilentlyContinue)
            Copy-Item -Path ".\report\report_$(($TestCycle).Trim()).xml" -Destination ".\report\report_$(($TestCycle).Trim())-junit.xml" -Force -ErrorAction SilentlyContinue
            LogMsg "Copied : .\report\report_$(($TestCycle).Trim()).xml --> .\report\report_$(($TestCycle).Trim())-junit.xml"
            LogMsg "Analysing results.."
            LogMsg "PASS  : $($resultXML.testsuites.testsuite.tests - $resultXML.testsuites.testsuite.errors - $resultXML.testsuites.testsuite.failures)"
            LogMsg "FAIL  : $($resultXML.testsuites.testsuite.failures)"
            LogMsg "ABORT : $($resultXML.testsuites.testsuite.errors)"
            if ( ( $resultXML.testsuites.testsuite.failures -eq 0 ) -and ( $resultXML.testsuites.testsuite.errors -eq 0 ) -and ( $resultXML.testsuites.testsuite.tests -gt 0 ))
            {
                $ExitCode = 0
            }
            else
            {
                $ExitCode = 1
            }
        }
        else
        {
            LogMsg "Summary file: .\report\report_$(($TestCycle).Trim()).xml does not exist. Exiting with 1."
            $ExitCode = 1
        }
    }
    catch
    {
        LogMsg "$($_.Exception.GetType().FullName, " : ",$_.Exception.Message)"
        $ExitCode = 1
    }
    finally
    {
        if ( $ExitWithZero -and ($ExitCode -ne 0) )
        {
            LogMsg "Changed exit code from 1 --> 0. (-ExitWithZero mentioned.)"
            $ExitCode = 0
        }
    }
}
catch 
{
    $line = $_.InvocationInfo.ScriptLineNumber
    $script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
    $ErrorMessage =  $_.Exception.Message
    LogMsg "EXCEPTION : $ErrorMessage"
    LogMsg "Source : Line $line in script $script_name."
    $ExitCode = 1
}
finally 
{
    if ( $finalWorkingDirectory )
    {
        Write-Host "Copying all files back to original working directory: $originalWorkingDirectory."
        $tmpDest = '\\?\' + $originalWorkingDirectory
        Copy-Item -Path "$finalWorkingDirectory\*" -Destination $tmpDest -Force -Recurse | Out-Null
        cd ..
        Write-Host "Cleaning up $finalWorkingDirectory"
        Remove-Item -Path $finalWorkingDirectory -Force -Recurse -ErrorAction SilentlyContinue
        Write-Host "Setting workspace back to original location: $originalWorkingDirectory"
        cd $originalWorkingDirectory
    }
    Get-Variable -Scope Global | Remove-Variable -Force -ErrorAction SilentlyContinue
    LogMsg "LISAv2 exits with code: $ExitCode"
    exit $ExitCode}