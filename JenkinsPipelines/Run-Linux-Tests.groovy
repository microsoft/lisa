// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the Apache License.

def RunPowershellCommand(psCmd) {
    bat "powershell.exe -NonInteractive -ExecutionPolicy Bypass -Command \"[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;$psCmd;EXIT \$global:LastExitCode\""
    //powershell (psCmd)
}

def GetFinalVHDName (CustomVHD)
{
    def FinalVHDName = ""
    if (CustomVHD.endsWith("vhd.xz"))
    {
        FinalVHDName = UpstreamBuildNumber + "-" + CustomVHD.replace(".vhd.xz",".vhd")
    }
    else if (CustomVHD.endsWith("vhdx.xz"))
    {
        FinalVHDName = UpstreamBuildNumber + "-" + CustomVHD.replace(".vhdx.xz",".vhd")
    }
    else if (CustomVHD.endsWith("vhdx"))
    {
        FinalVHDName = UpstreamBuildNumber + "-" + CustomVHD.replace(".vhdx",".vhd")
    }
    else if (CustomVHD.endsWith("vhd"))
    {
        FinalVHDName = UpstreamBuildNumber + "-" + CustomVHD
    }
    return FinalVHDName
}

def ExecuteTest( JenkinsUser, UpstreamBuildNumber, ImageSource, CustomVHD, CustomVHDURL, Kernel, CustomKernelFile, CustomKernelURL, GitUrlForAutomation, GitBranchForAutomation, TestByTestname, TestByCategorisedTestname, TestByCategory, TestByTag, Email, debug )
{
    if( (TestByTestname != "" && TestByTestname != null) || (TestByCategorisedTestname != "" && TestByCategorisedTestname != null) || (TestByCategory != "" && TestByCategory != null) || (TestByTag != "" && TestByTag != null) )
    {
        node('azure') 
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

            if (TestByTestname != "" && TestByTestname != null)
            {
                def CurrentTests = [failFast: false]
                for ( i = 0; i < TestByTestname.split(",").length; i++)
                {
                    def CurrentCounter = i
                    def CurrentExecution = TestByTestname.split(",")[CurrentCounter]
                    def CurrentExecutionName = CurrentExecution.replace(">>"," ")
                    CurrentTests["${CurrentExecutionName}"] = 
                    {
                        try
                        {
                            timeout (10800)
                            {
                                stage ("${CurrentExecutionName}") 
                                {
                                    node('azure') 
                                    {
                                        println(CurrentExecution)
                                        def TestPlatform = CurrentExecution.split(">>")[0]
                                        def Testname = CurrentExecution.split(">>")[1]
                                        def TestRegion = CurrentExecution.split(">>")[2]
                                        Prepare()
                                        withCredentials([file(credentialsId: 'Azure_Secrets_File', variable: 'Azure_Secrets_File')]) 
                                        {
                                            RunPowershellCommand(".\\RunTests.ps1" +
                                            " -UpdateGlobalConfigurationFromSecretsFile" +
                                            " -UpdateXMLStringsFromSecretsFile" +                                              
                                            " -ExitWithZero" +
                                            " -XMLSecretFile '${Azure_Secrets_File}'" +
                                            " -TestLocation '${TestRegion}'" +
                                            " -RGIdentifier '${JenkinsUser}'" +
                                            " -TestPlatform '${TestPlatform}'" +
                                            FinalImageSource +
                                            " -TestNames '${Testname}'"
                                            )
                                            archiveArtifacts '*-buildlogs.zip'
                                            junit "report\\*-junit.xml"
                                            emailext body: '${SCRIPT, template="groovy-html.template"}', replyTo: '$DEFAULT_REPLYTO', subject: "${ImageSource}", to: "${Email}"
                                        }                                
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
            if (TestByCategorisedTestname != "" && TestByCategorisedTestname != null)
            {
                def CurrentTests = [failFast: false]
                for ( i = 0; i < TestByCategorisedTestname.split(",").length; i++)
                {
                    def CurrentCounter = i
                    def CurrentExecution = TestByCategorisedTestname.split(",")[CurrentCounter]
                    def CurrentExecutionName = CurrentExecution.replace(">>"," ")
                    CurrentTests["${CurrentExecutionName}"] = 
                    {
                        try
                        {
                            timeout (10800)
                            {
                                stage ("${CurrentExecutionName}") 
                                {
                                    node('azure') 
                                    {
                                        println(CurrentExecution)
                                        def TestPlatform = CurrentExecution.split(">>")[0]
                                        def TestCategory = CurrentExecution.split(">>")[1]
                                        def TestArea = CurrentExecution.split(">>")[2]
                                        def TestName = CurrentExecution.split(">>")[3]
                                        def TestRegion = CurrentExecution.split(">>")[4]
                                        Prepare()
                                        withCredentials([file(credentialsId: 'Azure_Secrets_File', variable: 'Azure_Secrets_File')]) 
                                        {
                                            RunPowershellCommand(".\\RunTests.ps1" +
                                            " -UpdateGlobalConfigurationFromSecretsFile" +
                                            " -UpdateXMLStringsFromSecretsFile" +                                            
                                            " -ExitWithZero" +
                                            " -XMLSecretFile '${Azure_Secrets_File}'" +
                                            " -TestLocation '${TestRegion}'" +
                                            " -RGIdentifier '${JenkinsUser}'" +
                                            " -TestPlatform '${TestPlatform}'" +
                                            FinalImageSource +
                                            " -TestNames '${TestName}'"
                                            )
                                            archiveArtifacts '*-buildlogs.zip'
                                            junit "report\\*-junit.xml"
                                            emailext body: '${SCRIPT, template="groovy-html.template"}', replyTo: '$DEFAULT_REPLYTO', subject: "${ImageSource}", to: "${Email}"
                                        }                                
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
            if (TestByCategory != "" && TestByCategory != null)
            {
                def CurrentTests = [failFast: false]
                for ( i = 0; i < TestByCategory.split(",").length; i++)
                {
                    def CurrentCounter = i
                    def CurrentExecution = TestByCategory.split(",")[CurrentCounter]
                    def CurrentExecutionName = CurrentExecution.replace(">>"," ")
                    CurrentTests["${CurrentExecutionName}"] = 
                    {
                        try
                        {
                            timeout (10800)
                            {
                                stage ("${CurrentExecutionName}") 
                                {
                                    node('azure') 
                                    {
                                        println(CurrentExecution)
                                        def TestPlatform = CurrentExecution.split(">>")[0]
                                        def TestCategory = CurrentExecution.split(">>")[1]
                                        def TestArea = CurrentExecution.split(">>")[2]
                                        def TestRegion = CurrentExecution.split(">>")[3]
                                        Prepare()
                                        withCredentials([file(credentialsId: 'Azure_Secrets_File', variable: 'Azure_Secrets_File')]) 
                                        {
                                            RunPowershellCommand(".\\RunTests.ps1" +
                                            " -UpdateGlobalConfigurationFromSecretsFile" +
                                            " -UpdateXMLStringsFromSecretsFile" +                                            
                                            " -ExitWithZero" +
                                            " -XMLSecretFile '${Azure_Secrets_File}'" +
                                            " -TestLocation '${TestRegion}'" +
                                            " -RGIdentifier '${JenkinsUser}'" +
                                            " -TestPlatform '${TestPlatform}'" +
                                            " -TestCategory '${TestCategory}'" +
                                            " -TestArea '${TestArea}'" +
                                            FinalImageSource
                                            )
                                            archiveArtifacts '*-buildlogs.zip'
                                            junit "report\\*-junit.xml"
                                            emailext body: '${SCRIPT, template="groovy-html.template"}', replyTo: '$DEFAULT_REPLYTO', subject: "${ImageSource}", to: "${Email}"
                                        }                                
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
            if (TestByTag != "" && TestByTag != null)
            {
                def CurrentTests = [failFast: false]
                for ( i = 0; i < TestByTag.split(",").length; i++)
                {
                    def CurrentCounter = i
                    def CurrentExecution = TestByTag.split(",")[CurrentCounter]
                    def CurrentExecutionName = CurrentExecution.replace(">>"," ")
                    CurrentTests["${CurrentExecutionName}"] = 
                    {
                        try
                        {
                            timeout (10800)
                            {
                                stage ("${CurrentExecutionName}") 
                                {
                                    node('azure') 
                                    {
                                        println(CurrentExecution)
                                        def TestPlatform = CurrentExecution.split(">>")[0]
                                        def TestTag = CurrentExecution.split(">>")[1]
                                        def TestRegion = CurrentExecution.split(">>")[2]
                                        Prepare()
                                        withCredentials([file(credentialsId: 'Azure_Secrets_File', variable: 'Azure_Secrets_File')]) 
                                        {
                                            RunPowershellCommand(".\\RunTests.ps1" +
                                            " -UpdateGlobalConfigurationFromSecretsFile" +
                                            " -UpdateXMLStringsFromSecretsFile" +                                            
                                            " -ExitWithZero" +
                                            " -XMLSecretFile '${Azure_Secrets_File}'" +
                                            " -TestLocation '${TestRegion}'" +
                                            " -RGIdentifier '${JenkinsUser}'" +
                                            " -TestPlatform '${TestPlatform}'" +
                                            " -TestTag '${TestTag}'" +
                                            FinalImageSource
                                            )
                                            archiveArtifacts '*-buildlogs.zip'
                                            junit "report\\*-junit.xml"
                                            emailext body: '${SCRIPT, template="groovy-html.template"}', replyTo: '$DEFAULT_REPLYTO', subject: "${ImageSource}", to: "${Email}"
                                        }                                
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
                RunPowershellCommand(".\\RunTests.ps1" +
                " -UpdateGlobalConfigurationFromSecretsFile" +
                " -UpdateXMLStringsFromSecretsFile" +                  
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
                RunPowershellCommand ( ".\\JenkinsPipelines\\Scripts\\DetectTestRegions.ps1 -TestByTestName '${TestByTestname}' -TestByCategorizedTestName '${TestByCategorisedTestname}' -TestByCategory '${TestByCategory}' -TestByTag '${TestByTag}'" )
                CurrentTestRegions = readFile 'CurrentTestRegions.azure.env'
                RunPowershellCommand (".\\Utilities\\AddAzureRmAccountFromSecretsFile.ps1;" +
                ".\\Utilities\\CopyVHDtoOtherStorageAccount.ps1 -SourceLocation westus2 -destinationLocations '${CurrentTestRegions}' -sourceVHDName '${FinalVHDName}' -DestinationAccountType Standard"
                )             
            }
        }
    }
}


stage("TestByTestname")
{
    ExecuteTest ( JenkinsUser, UpstreamBuildNumber, ImageSource, CustomVHD, CustomVHDURL, Kernel, CustomKernelFile, CustomKernelURL, GitUrlForAutomation, GitBranchForAutomation, TestByTestname, null, null, null, Email, debug )
}
stage("TestByCategorisedTestname")
{
    ExecuteTest ( JenkinsUser, UpstreamBuildNumber, ImageSource, CustomVHD, CustomVHDURL, Kernel, CustomKernelFile, CustomKernelURL, GitUrlForAutomation, GitBranchForAutomation, null, TestByCategorisedTestname, null, null, Email, debug )
}
stage("TestByCategory")
{
    ExecuteTest ( JenkinsUser, UpstreamBuildNumber, ImageSource, CustomVHD, CustomVHDURL, Kernel, CustomKernelFile, CustomKernelURL, GitUrlForAutomation, GitBranchForAutomation, null, null, TestByCategory, null, Email, debug )
}
stage("TestByTag")
{
    ExecuteTest ( JenkinsUser, UpstreamBuildNumber, ImageSource, CustomVHD, CustomVHDURL, Kernel, CustomKernelFile, CustomKernelURL, GitUrlForAutomation, GitBranchForAutomation, null, null, null, TestByTag, Email, debug )
}
