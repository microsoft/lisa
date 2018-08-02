// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the Apache License.

def RunPowershellCommand(psCmd) {
    bat "powershell.exe -NonInteractive -ExecutionPolicy Bypass -Command \"[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;$psCmd;EXIT \$global:LastExitCode\""
    //powershell (psCmd)
}

def ExecuteTest( JenkinsUser, UpstreamBuildNumber, ImageSource, CustomVHD, CustomVHDURL, Kernel, CustomKernelFile, CustomKernelURL, GitUrlForAutomation, GitBranchForAutomation, RegionAndVMSize, TestIterations, Networking, Email, debug )
{
    node('master') 
    {
        //Define Varialbles
        def FinalVHDName = ""
        def FinalImageSource = ""
        def EmailSubject = ""

        //Select ARM Image / Custom VHD
        if ((CustomVHD != "" && CustomVHD != null) || (CustomVHDURL != "" && CustomVHDURL != null))
        {
            unstash 'CustomVHD'
            FinalVHDName = readFile 'CustomVHD.azure.env'
            FinalImageSource = " -OsVHD '${FinalVHDName}'"
            EmailSubject = FinalVHDName
        }
        else
        {
            FinalImageSource = " -ARMImageName '${ImageSource}'"
            EmailSubject = ImageSource
        }

        if ( (CustomKernelFile != "" && CustomKernelFile != null) || (CustomKernelURL != "" && CustomKernelURL != null) || (Kernel != "default") )
        {
            unstash "CapturedVHD.azure.env"
            FinalImageSource = readFile "CapturedVHD.azure.env"
            FinalImageSource = " -OsVHD ${FinalImageSource}"
        }

        def CurrentTests = [failFast: false]
        def TestRegion = RegionAndVMSize.split(" ")[0]
        def VMSize = RegionAndVMSize.split(" ")[1]            
        if ( Networking.contains("SRIOV"))
        {
            CurrentTests["SRIOV"] = 
            {
                try
                {
                    stage ("SRIOV") 
                    {
                        node('azure') 
                        {
                            Prepare()
                            withCredentials([file(credentialsId: 'Azure_Secrets_File', variable: 'Azure_Secrets_File')]) 
                            {
                                RunPowershellCommand(".\\RunTests.ps1" +
                                " -UpdateGlobalConfigurationFromSecretsFile" +
                                " -UpdateXMLStringsFromSecretsFile" +
                                " -RGIdentifier '${JenkinsUser}'" +
                                " -ExitWithZero" +
                                FinalImageSource +                                    
                                " -XMLSecretFile '${Azure_Secrets_File}'" + 
                                " -TestPlatform 'Azure'" +
                                " -TestNames 'VERIFY-DEPLOYMENT-PROVISION'" +
                                " -TestLocation '${TestRegion}'" +
                                " -OverrideVMSize '${VMSize}'" +
                                " -TestIterations ${TestIterations}" +
                                " -EnableAcceleratedNetworking"
                                )
                                archiveArtifacts '*-buildlogs.zip'
                                junit "report\\*-junit.xml"
                                emailext body: '${SCRIPT, template="groovy-html.template"}', replyTo: '$DEFAULT_REPLYTO', subject: "${ImageSource}", to: "${Email}"
                            }                                
                        }
                    }

                }
                catch (exc)
                {
                    currentBuild.result = 'FAILURE'
                    println "STAGE_FAILED_EXCEPTION."
                }
                finally
                {
                
                }    			
            }
        }
        if ( Networking.contains("Synthetic"))
        {
            CurrentTests["Synthetic"] = 
            {
                try
                {
                    stage ("Synthetic") 
                    {
                        node('azure') 
                        {
                            Prepare()                                
                            withCredentials([file(credentialsId: 'Azure_Secrets_File', variable: 'Azure_Secrets_File')]) 
                            {
                                RunPowershellCommand(".\\RunTests.ps1" +
                                " -UpdateGlobalConfigurationFromSecretsFile" +
                                " -UpdateXMLStringsFromSecretsFile" +                                
                                " -RGIdentifier '${JenkinsUser}'" +                                    
                                " -ExitWithZero" +
                                FinalImageSource +                                    
                                " -XMLSecretFile '${Azure_Secrets_File}'" +
                                " -TestPlatform 'Azure'" +
                                " -TestNames 'VERIFY-DEPLOYMENT-PROVISION'" +
                                " -TestLocation '${TestRegion}'" +
                                " -TestIterations ${TestIterations}" +                                    
                                " -OverrideVMSize '${VMSize}'"
                                )
                                archiveArtifacts '*-buildlogs.zip'
                                junit "report\\*-junit.xml"
                                emailext body: '${SCRIPT, template="groovy-html.template"}', replyTo: '$DEFAULT_REPLYTO', subject: "${ImageSource}", to: "${Email}"
                            }                                
                        }
                    }
                }
                catch (exc)
                {
                    currentBuild.result = 'FAILURE'
                    println "STAGE_FAILED_EXCEPTION."
                }
                finally
                {
                
                }    			
            }                 
        }
        parallel CurrentTests
    }  
}

def Prepare()
{
    retry(5)
    {
        cleanWs()
        unstash 'LISAv2'
    }
}

stage ("Prerequisite")
{
    node ("azure")
    {
        cleanWs()
        git branch: GitBranchForAutomation, url: GitUrlForAutomation
        stash includes: '**', name: 'LISAv2'
        cleanWs()
    }
}

stage ("Inspect VHD")
{
    if ((CustomVHD != "" && CustomVHD != null) || (CustomVHDURL != "" && CustomVHDURL != null))
    {
        node ("vhd")
        {
            Prepare()
            println "Running Inspect file"
            RunPowershellCommand (".\\JenkinsPipelines\\Scripts\\InspectVHD.ps1")
            stash includes: 'CustomVHD.azure.env', name: 'CustomVHD'
        }
    }
}

stage('Upload VHD to Azure')
{
    def FinalVHDName = ""
    if ((CustomVHD != "" && CustomVHD != null) || (CustomVHDURL != "" && CustomVHDURL != null))
    {
        node ("vhd")
        {
            Prepare()
            unstash 'CustomVHD'
            FinalVHDName = readFile 'CustomVHD.azure.env'
            withCredentials([file(credentialsId: 'Azure_Secrets_File', variable: 'Azure_Secrets_File')])
            {
                RunPowershellCommand (".\\Utilities\\AddAzureRmAccountFromSecretsFile.ps1;" +
                ".\\Utilities\\UploadVHDtoAzureStorage.ps1 -Region westus2 -VHDPath 'Q:\\Temp\\${FinalVHDName}' -DeleteVHDAfterUpload -NumberOfUploaderThreads 64"
                )
            }    
        }
    }
}

stage('Capture VHD with Custom Kernel')
{

    def KernelFile = ""
    def FinalImageSource = ""
    //Inspect the kernel
    if ( (CustomKernelFile != "" && CustomKernelFile != null) || (CustomKernelURL != "" && CustomKernelURL != null) )
    {
        node("azure")
        {        
            if ((CustomVHD != "" && CustomVHD != null) || (CustomVHDURL != "" && CustomVHDURL != null))
            {
                unstash 'CustomVHD'
                FinalVHDName = readFile 'CustomVHD.azure.env'
                FinalImageSource = " -OsVHD '${FinalVHDName}'"
            }
            else
            {
                FinalImageSource = " -ARMImageName '${ImageSource}'"
            }    
            Prepare()
            withCredentials([file(credentialsId: 'Azure_Secrets_File', variable: 'Azure_Secrets_File')])
            {
                RunPowershellCommand (".\\Utilities\\AddAzureRmAccountFromSecretsFile.ps1;" +
                ".\\JenkinsPipelines\\Scripts\\InspectCustomKernel.ps1 -RemoteFolder 'J:\\ReceivedFiles' -LocalFolder '.'" 
                )
                KernelFile = readFile 'CustomKernel.azure.env'
                stash includes: KernelFile, name: 'CustomKernelStash'
                powershell(".\\Utilities\\UpdateXMLs.ps1 -SubscriptionID '2cd20493-fe97-42ef-9ace-ab95b63d82c4' -LinuxUsername '${LinuxUsername}' -LinuxPassword '${LinuxPassword}'")
                RunPowershellCommand(".\\RunTests.ps1" +
                " -XMLSecretFile '${Azure_Secrets_File}'" +
                " -TestLocation 'westus2'" +
                " -RGIdentifier '${JenkinsUser}'" +
                " -TestPlatform 'Azure'" +
                " -CustomKernel 'localfile:${KernelFile}'" +
                FinalImageSource +
                " -TestNames 'CAPTURE-VHD-BEFORE-TEST'"
                )
                CapturedVHD = readFile 'CapturedVHD.azure.env'
                stash includes: 'CapturedVHD.azure.env', name: 'CapturedVHD.azure.env'           
            }
            println("Captured VHD : ${CapturedVHD}")
        }
    }
}

stage('Copy VHD to other regions')
{
    def CurrentTestRegions = ""
    if ((CustomVHDURL != "" && CustomVHDURL != null)  || (CustomVHD != "" && CustomVHD != null) || (CustomKernelFile != "" && CustomKernelFile != null) || (CustomKernelURL != "" && CustomKernelURL != null) || (Kernel != "default"))
    {
        node ("vhd")
        {
            Prepare()
            def FinalVHDName = ""
            if ((CustomKernelFile != "" && CustomKernelFile != null) || (CustomKernelURL != "" && CustomKernelURL != null) || (Kernel != "default"))
            {
                unstash "CapturedVHD.azure.env"
                FinalVHDName = readFile "CapturedVHD.azure.env"
            }
            else
            {
                unstash 'CustomVHD'
                FinalVHDName = readFile 'CustomVHD.azure.env'
            }
            withCredentials([file(credentialsId: 'Azure_Secrets_File', variable: 'Azure_Secrets_File')])
            {
                CurrentTestRegions = RegionAndVMSize.split(" ")[0]
                RunPowershellCommand (".\\Utilities\\AddAzureRmAccountFromSecretsFile.ps1;" +
                ".\\Utilities\\CopyVHDtoOtherStorageAccount.ps1 -SourceLocation westus2 -destinationLocations '${CurrentTestRegions}' -sourceVHDName '${FinalVHDName}' -DestinationAccountType Standard"
                )             
            }
        }
    }
}
stage("Boot Stress")
{
    ExecuteTest( JenkinsUser, UpstreamBuildNumber, ImageSource, CustomVHD, CustomVHDURL, Kernel, CustomKernelFile, CustomKernelURL, GitUrlForAutomation, GitBranchForAutomation, RegionAndVMSize, TestIterations, Networking, Email, debug )
}