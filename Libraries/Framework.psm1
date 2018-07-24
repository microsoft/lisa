##############################################################################################
# Framework.psm1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
    Pipeline framework modules.

.PARAMETER
    <Parameters>

.INPUTS


.NOTES
    Creation Date:  
    Purpose/Change: 

.EXAMPLE


#>
###############################################################################################

Function ValidateParameters()
{
	$ParameterErrors = @()
	if ($TestPlatform -eq "Azure")
	{
		#region Validate Parameters
		if ( !$ARMImageName -and !$OsVHD )
		{
			$ParameterErrors += "-ARMImageName <'Publisher Offer Sku Version'>, or -OsVHD <'VHD_Name.vhd'> is required."
		}
		if ($ARMImageName.Split(" ").Count -ne 4)
		{
			$ParameterErrors += "Invalid value for -ARMImageName <'Publisher Offer Sku Version'> provided. 'Publisher Offer Sku Version' should be separated by space ' ' char."
		}
		if ( !$TestLocation)
		{
			$ParameterErrors += "-TestLocation <AzureRegion> is required."
		}
		if ( !$RGIdentifier )
		{
			$ParameterErrors += "-RGIdentifier <ResourceGroupIdentifier> is required."
		}   
		#endregion
	}
	elseif ($TestPlatform -eq "HyperV")
	{
		#region Validate Parameters
		if (!$OsVHD )
		{
			$ParameterErrors += "-OsVHD <'VHD_Name.vhd'> is required."
		}
		if ( !$RGIdentifier )
		{
			$ParameterErrors += "-RGIdentifier <ResourceGroupIdentifier> is required."
		}
		#endregion
	}	
	elseif ($TestPlatform)
	{
		$ParameterErrors += "$TestPlatform is not yet supported."
	}
	else
	{
		$ParameterErrors += "'-TestPlatform' is not provided."
	}
	
	
	
	if ( $ParameterErrors.Count -gt 0)
	{
		$ParameterErrors | ForEach-Object { LogError $_ }
		Throw "Failed to validate the test parameters provided. Please fix above issues and retry."
	}
	else 
	{
		LogMsg "Test parameters have been validated successfully. Continue running the test."
	}	
}

Function UpdateGlobalConfigurationXML()
{
	#Region Update Global Configuration XML file as needed
	if ($UpdateGlobalConfigurationFromSecretsFile)
	{
		if ($XMLSecretFile)
		{
			if (Test-Path -Path $XMLSecretFile)
			{
				LogMsg "Updating .\XML\GlobalConfigurations.xml"
				.\Utilities\UpdateGlobalConfigurationFromXmlSecrets.ps1 -XmlSecretsFilePath $XMLSecretFile
			}
			else 
			{
				LogErr "Failed to update .\XML\GlobalConfigurations.xml. '$XMLSecretFile' not found."    
			}
		}
		else 
		{
			LogErr "Failed to update .\XML\GlobalConfigurations.xml. '-XMLSecretFile [FilePath]' not provided."    
		}
	}
	$RegionStorageMapping = [xml](Get-Content .\XML\RegionAndStorageAccounts.xml)
	$GlobalConfiguration = [xml](Get-Content .\XML\GlobalConfigurations.xml)

	if ($TestPlatform -eq "Azure")
	{
		if ( $StorageAccount -imatch "ExistingStorage_Standard" )
		{
			$GlobalConfiguration.Global.$TestPlatform.Subscription.ARMStorageAccount = $RegionStorageMapping.AllRegions.$TestLocation.StandardStorage
		}
		elseif ( $StorageAccount -imatch "ExistingStorage_Premium" )
		{
			$GlobalConfiguration.Global.$TestPlatform.Subscription.ARMStorageAccount = $RegionStorageMapping.AllRegions.$TestLocation.PremiumStorage
		}
		elseif ( $StorageAccount -imatch "NewStorage_Standard" )
		{
			$GlobalConfiguration.Global.$TestPlatform.Subscription.ARMStorageAccount = "NewStorage_Standard_LRS"
		}
		elseif ( $StorageAccount -imatch "NewStorage_Premium" )
		{
			$GlobalConfiguration.Global.$TestPlatform.Subscription.ARMStorageAccount = "NewStorage_Premium_LRS"
		}
		elseif ($StorageAccount -eq "")
		{
			$GlobalConfiguration.Global.$TestPlatform.Subscription.ARMStorageAccount = $RegionStorageMapping.AllRegions.$TestLocation.StandardStorage
			LogMsg "Auto selecting storage account : $($GlobalConfiguration.Global.$TestPlatform.Subscription.ARMStorageAccount) as per your test region."
		}
		elseif ($StorageAccount -ne "")
		{
			$GlobalConfiguration.Global.$TestPlatform.Subscription.ARMStorageAccount = $StorageAccount.Trim()
			Write-Host "Selecting custom storage account : $($GlobalConfiguration.Global.$TestPlatform.Subscription.ARMStorageAccount) as per your test region."
		}
	}
	if ($TestPlatform -eq "HyperV")
	{
		if ( $TestLocation)
		{
			$GlobalConfiguration.Global.$TestPlatform.Host.ServerName = $TestLocation
			$VMs = Get-VM -ComputerName $GlobalConfiguration.Global.$TestPlatform.Host.ServerName
			if ($?)
			{
				LogMsg "Set '$TestLocation' to As GlobalConfiguration.Global.HyperV.Host.ServerName"
			}
			else 
			{
				LogErr "Did you used -TestLocation XXXXXXX. In HyperV mode, -TestLocation can be used to Override HyperV server mentioned in GlobalConfiguration XML file."
				LogErr "In HyperV mode, -TestLocation can be used to Override HyperV server mentioned in GlobalConfiguration XML file."
				Throw "Unable to access HyperV server - $TestLocation"	
			}
		}
		else
		{
            $VMs = Get-VM -ComputerName $TestLocation
		}
        
		
	}
	#If user provides Result database / result table, then add it to the GlobalConfiguration.
	if( $ResultDBTable -or $ResultDBTestTag)
	{
		if( $ResultDBTable )
		{
			$GlobalConfiguration.Global.$TestPlatform.ResultsDatabase.dbtable = ($ResultDBTable).Trim()
			LogMsg "ResultDBTable : $ResultDBTable added to .\XML\GlobalConfigurations.xml"
		}
		if( $ResultDBTestTag )
		{
			$GlobalConfiguration.Global.$TestPlatform.ResultsDatabase.testTag = ($ResultDBTestTag).Trim()
			LogMsg "ResultDBTestTag: $ResultDBTestTag added to .\XML\GlobalConfigurations.xml"
		}                      
	}
	$GlobalConfiguration.Save("$WorkingDirectory\XML\GlobalConfigurations.xml")
	#endregion

	New-Item -ItemType Directory -Path "TestResults" -Force -ErrorAction SilentlyContinue | Out-Null

	$LogDir = ".\TestResults\$(Get-Date -Format 'yyyy-dd-MM-HH-mm-ss-ffff')"
	Set-Variable -Name LogDir -Value $LogDir -Scope Global -Force
	Set-Variable -Name RootLogDir -Value $LogDir -Scope Global -Force
	New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
	New-Item -ItemType Directory -Path Temp -Force -ErrorAction SilentlyContinue | Out-Null
	LogMsg "Created LogDir: $LogDir"

	if ($TestPlatform -eq "Azure")
	{
		if ($env:Azure_Secrets_File)
		{
			LogMsg "Detected Azure_Secrets_File in Jenkins environment."
			$XMLSecretFile = $env:Azure_Secrets_File
		}
		if ( $XMLSecretFile )
		{
			ValiateXMLs -ParentFolder $((Get-Item -Path $XMLSecretFile).FullName | Split-Path -Parent)
			.\Utilities\AddAzureRmAccountFromSecretsFile.ps1 -customSecretsFilePath $XMLSecretFile
			Set-Variable -Value ([xml](Get-Content $XMLSecretFile)) -Name XmlSecrets -Scope Global
			LogMsg "XmlSecrets set as global variable."
		}
		else 
		{
			LogMsg "XML secret file not provided." 
			LogMsg "Powershell session must be authenticated to manage the azure subscription."
		}
	}
}

Function UpdateXMLStringsFromSecretsFile()
{
	#region Replace strings in XML files
    if ($UpdateXMLStringsFromSecretsFile)
    {
        if ($XMLSecretFile)
        {
            if (Test-Path -Path $XMLSecretFile)
            {
                .\Utilities\UpdateXMLStringsFromXmlSecrets.ps1 -XmlSecretsFilePath $XMLSecretFile
            }
            else 
            {
                LogErr "Failed to update Strings in .\XML files. '$XMLSecretFile' not found."    
            }
        }
        else 
        {
            LogErr "Failed to update Strings in .\XML files. '-XMLSecretFile [FilePath]' not provided."    
        }
    }
}

Function CollectTestCases($TestXMLs)
{
	#region Collect Tests Data
	$allTests = @()
    if ( $TestPlatform -and !$TestCategory -and !$TestArea -and !$TestNames -and !$TestTag)
    {
        foreach ( $file in $TestXMLs.FullName)
        {
            $currentTests = ([xml]( Get-Content -Path $file)).TestCases
            if ( $TestPlatform )
            {
                foreach ( $test in $currentTests.test )
                {
                    if ($test.Platform.Split(",").Contains($TestPlatform) ) 
                    {
                        LogMsg "Collected $($test.TestName)"
                        $allTests += $test
                    }
                }
            }
        }         
    }
    elseif ( $TestPlatform -and $TestCategory -and (!$TestArea -or $TestArea -eq "default") -and !$TestNames -and !$TestTag)
    {
        foreach ( $file in $TestXMLs.FullName)
        {
            
            $currentTests = ([xml]( Get-Content -Path $file)).TestCases
            if ( $TestPlatform )
            {
                foreach ( $test in $currentTests.test )
                {
                    if ( ($test.Platform.Split(",").Contains($TestPlatform) ) -and $($TestCategory -eq $test.Category) )
                    {
                        LogMsg "Collected $($test.TestName)"
                        $allTests += $test
                    }
                }
            }
        }         
    }
    elseif ( $TestPlatform -and $TestCategory -and ($TestArea -and $TestArea -ne "default") -and !$TestNames -and !$TestTag)
    {
        foreach ( $file in $TestXMLs.FullName)
        {
            
            $currentTests = ([xml]( Get-Content -Path $file)).TestCases
            if ( $TestPlatform )
            {
                foreach ( $test in $currentTests.test )
                {
                    if ( ($test.Platform.Split(",").Contains($TestPlatform) ) -and $($TestCategory -eq $test.Category) -and $($TestArea -eq $test.Area) )
                    {
                        LogMsg "Collected $($test.TestName)"
                        $allTests += $test
                    }
                }
            }
        }         
    }
    elseif ( $TestPlatform -and $TestCategory  -and $TestNames -and !$TestTag)
    {
        foreach ( $file in $TestXMLs.FullName)
        {
            
            $currentTests = ([xml]( Get-Content -Path $file)).TestCases
            if ( $TestPlatform )
            {
                foreach ( $test in $currentTests.test )
                {
                    if ( ($test.Platform.Split(",").Contains($TestPlatform) ) -and $($TestCategory -eq $test.Category) -and $($TestArea -eq $test.Area) -and ($TestNames.Split(",").Contains($test.TestName) ) )
                    {
                        LogMsg "Collected $($test.TestName)"
                        $allTests += $test
                    }
                }
            }
        }         
    }
    elseif ( $TestPlatform -and !$TestCategory -and !$TestArea -and $TestNames -and !$TestTag)
    {
        foreach ( $file in $TestXMLs.FullName)
        {   
            $currentTests = ([xml]( Get-Content -Path $file)).TestCases
            if ( $TestPlatform )
            {
                foreach ( $test in $currentTests.test )
                {
                    if ( ($test.Platform.Split(",").Contains($TestPlatform) ) -and ($TestNames.Split(",").Contains($test.TestName) ) )
                    {
                        LogMsg "Collected $($test.TestName)"
                        $allTests += $test
                    }
                }
            }
        }         
    }    
    elseif ( $TestPlatform -and !$TestCategory -and !$TestArea -and !$TestNames -and $TestTag)
    {
        foreach ( $file in $TestXMLs.FullName)
        {
            
            $currentTests = ([xml]( Get-Content -Path $file)).TestCases
            if ( $TestPlatform )
            {
                foreach ( $test in $currentTests.test )
                {
                    if ( ($test.Platform.Split(",").Contains($TestPlatform) ) -and ( $test.Tags.Split(",").Contains($TestTag) ) )
                    {
                        LogMsg "Collected $($test.TestName)"
                        $allTests += $test
                    }
                }
            }
        }         
    }
    else 
    {
        LogError "TestPlatform : $TestPlatform"
        LogError "TestCategory : $TestCategory"
        LogError "TestArea : $TestArea"
        LogError "TestNames : $TestNames"
        LogError "TestTag : $TestTag"
        Throw "Invalid Test Selection"
	}
	return $allTests
    #endregion 	
}
function GetTestSummary($testCycle, [DateTime] $StartTime, [string] $xmlFilename, [string] $distro, $testSuiteResultDetails)
{
    <#
	.Synopsis
    	Append the summary text from each VM into a single string.
        
    .Description
        Append the summary text from each VM one long string. The
        string includes line breaks so it can be display on a 
        console or included in an e-mail message.
        
	.Parameter xmlConfig
    	The parsed xml from the $xmlFilename file.
        Type : [System.Xml]

    .Parameter startTime
        The date/time the ICA test run was started
        Type : [DateTime]

    .Parameter xmlFilename
        The name of the xml file for the current test run.
        Type : [String]
        
    .ReturnValue
        A string containing all the summary message from all
        VMs in the current test run.
        
    .Example
        GetTestSummary $testCycle $myStartTime $myXmlTestFile
	
#>
    
	$endTime = [Datetime]::Now.ToUniversalTime()
	$testSuiteRunDuration= $endTime - $StartTime    
	$testSuiteRunDuration=$testSuiteRunDuration.Days.ToString() + ":" +  $testSuiteRunDuration.hours.ToString() + ":" + $testSuiteRunDuration.minutes.ToString()
    $str = "<br />Test Results Summary<br />"
    $str += "ICA test run on " + $startTime
    if ( $BaseOsImage )
    {
        $str += "<br />Image under test " + $BaseOsImage
    }
    if ( $BaseOSVHD )
    {
        $str += "<br />VHD under test " + $BaseOSVHD
    }
    if ( $ARMImage )
    {
        $str += "<br />ARM Image under test " + "$($ARMImage.Publisher) : $($ARMImage.Offer) : $($ARMImage.Sku) : $($ARMImage.Version)"
    }
	$str += "<br />Total Executed TestCases " + $testSuiteResultDetails.totalTc + " (" + $testSuiteResultDetails.totalPassTc + " Pass" + ", " + $testSuiteResultDetails.totalFailTc + " Fail" + ", " + $testSuiteResultDetails.totalAbortedTc + " Abort)"
	$str += "<br />Total Execution Time(dd:hh:mm) " + $testSuiteRunDuration.ToString()
    $str += "<br />XML file: $xmlFilename<br /><br />"
	        
    # Add information about the host running ICA to the e-mail summary
    $str += "<pre>"
    $str += $testCycle.emailSummary + "<br />"
    $hostName = hostname
    $str += "<br />Logs can be found at $LogDir" + "<br /><br />"
    $str += "</pre>"
    $plainTextSummary = $str
    $strHtml =  "<style type='text/css'>" +
			".TFtable{width:1024px; border-collapse:collapse; }" +
			".TFtable td{ padding:7px; border:#4e95f4 1px solid;}" +
			".TFtable tr{ background: #b8d1f3;}" +
			".TFtable tr:nth-child(odd){ background: #dbe1e9;}" +
			".TFtable tr:nth-child(even){background: #ffffff;}</style>" +
            "<Html><head><title>Test Results Summary</title></head>" +
            "<body style = 'font-family:sans-serif;font-size:13px;color:#000000;margin:0px;padding:30px'>" +
            "<br/><h1 style='background-color:lightblue;width:1024'>Test Results Summary</h1>"
    $strHtml += "<h2 style='background-color:lightblue;width:1024'>ICA test run on - " + $startTime + "</h2><span style='font-size: medium'>"
    if ( $BaseOsImage )
    {
        $strHtml += '<p>Image under test - <span style="font-family:courier new,courier,monospace;">' + "$BaseOsImage</span></p>"
    }
    if ( $BaseOSVHD )
    {
        $strHtml += '<p>VHD under test - <span style="font-family:courier new,courier,monospace;">' + "$BaseOsVHD</span></p>"
    }
    if ( $ARMImage )
    {
        $strHtml += '<p>ARM Image under test - <span style="font-family:courier new,courier,monospace;">' + "$($ARMImage.Publisher) : $($ARMImage.Offer) : $($ARMImage.Sku) : $($ARMImage.Version)</span></p>"
    }

    $strHtml += '<p>Total Executed TestCases - <strong><span style="font-size:16px;">' + "$($testSuiteResultDetails.totalTc)" + '</span></strong><br />' + '[&nbsp;<span style="font-size:16px;"><span style="color:#008000;"><strong>' +  $testSuiteResultDetails.totalPassTc + ' </strong></span></span> - PASS, <span style="font-size:16px;"><span style="color:#ff0000;"><strong>' + "$($testSuiteResultDetails.totalFailTc)" + '</strong></span></span>- FAIL, <span style="font-size:16px;"><span style="color:#ff0000;"><strong><span style="background-color:#ffff00;">' + "$($testSuiteResultDetails.totalAbortedTc)" +'</span></strong></span></span> - ABORTED ]</p>'
    $strHtml += "<br /><br/>Total Execution Time(dd:hh:mm) " + $testSuiteRunDuration.ToString()
    $strHtml += "<br /><br/>XML file: $xmlFilename<br /><br /></span>"

    # Add information about the host running ICA to the e-mail summary
    $strHtml += "<table border='0' class='TFtable'>"
    $strHtml += $testCycle.htmlSummary
    $strHtml += "</table>"
    
    $strHtml += "</body></Html>"

    if (-not (Test-Path(".\temp\CI"))) {
        mkdir ".\temp\CI" | Out-Null 
    }

	Set-Content ".\temp\CI\index.html" $strHtml
	return $plainTextSummary, $strHtml
}

function SendEmail([XML] $xmlConfig, $body)
{
    <#
	.Synopsis
    	Send an e-mail message with test summary information.
        
    .Description
        Collect the test summary information from each testcycle.  Send an
        eMail message with this summary information to emailList defined
        in the xml config file.
        
	.Parameter xmlConfig
    	The parsed XML from the test xml file
        Type : [System.Xml]
        
    .ReturnValue
        none
        
    .Example
        SendEmail $myConfig
	#>

    $to = $xmlConfig.config.global.emailList.split(",")
    $from = $xmlConfig.config.global.emailSender
    $subject = $xmlConfig.config.global.emailSubject + " " + $testStartTime
    $smtpServer = $xmlConfig.config.global.smtpServer
    $fname = [System.IO.Path]::GetFilenameWithoutExtension($xmlConfigFile)
    # Highlight the failed tests 
    $body = $body.Replace("Aborted", '<em style="background:Yellow; color:Red">Aborted</em>')
    $body = $body.Replace("FAIL", '<em style="background:Yellow; color:Red">Failed</em>')
    
	Send-mailMessage -to $to -from $from -subject $subject -body $body -smtpserver $smtpServer -BodyAsHtml
}

function Usage()
{
    write-host
    write-host "  Start automation: AzureAutomationManager.ps1 -xmlConfigFile <xmlConfigFile> -runTests -email -Distro <DistroName> -cycleName <TestCycle>"
    write-host
    write-host "         xmlConfigFile : Specifies the configuration for the test environment."
    write-host "         DistroName    : Run tests on the distribution OS image defined in Azure->Deployment->Data->Distro"
    write-host "         -help         : Displays this help message."
    write-host
}
Function GetCurrentCycleData($xmlConfig, $cycleName)
{
    foreach ($Cycle in $xmlConfig.config.testCycles.Cycle )
    {
        if($cycle.cycleName -eq $cycleName)
        {
        return $cycle
        break
        }
    }
    
}

<#
JUnit XML Report Schema:
	http://windyroad.com.au/dl/Open%20Source/JUnit.xsd
Example:
	Import-Module .\UtilLibs.psm1 -Force

	StartLogReport("$pwd/report.xml")

	$testsuite = StartLogTestSuite "CloudTesting"

	$testcase = StartLogTestCase $testsuite "BVT" "CloudTesting.BVT"
	FinishLogTestCase $testcase

	$testcase = StartLogTestCase $testsuite "NETWORK" "CloudTesting.NETWORK"
	FinishLogTestCase $testcase "FAIL" "NETWORK fail" "Stack trace: XXX"

	$testcase = StartLogTestCase $testsuite "VNET" "CloudTesting.VNET"
	FinishLogTestCase $testcase "ERROR" "VNET error" "Stack trace: XXX"

	FinishLogTestSuite($testsuite)

	$testsuite = StartLogTestSuite "FCTesting"

	$testcase = StartLogTestCase $testsuite "BVT" "FCTesting.BVT"
	FinishLogTestCase $testcase

	$testcase = StartLogTestCase $testsuite "NEGATIVE" "FCTesting.NEGATIVE"
	FinishLogTestCase $testcase "FAIL" "NEGATIVE fail" "Stack trace: XXX"

	FinishLogTestSuite($testsuite)

	FinishLogReport

report.xml:
	<testsuites>
	  <testsuite name="CloudTesting" timestamp="2014-07-11T06:37:24" tests="3" failures="1" errors="1" time="0.04">
		<testcase name="BVT" classname="CloudTesting.BVT" time="0" />
		<testcase name="NETWORK" classname="CloudTesting.NETWORK" time="0">
		  <failure message="NETWORK fail">Stack trace: XXX</failure>
		</testcase>
		<testcase name="VNET" classname="CloudTesting.VNET" time="0">
		  <error message="VNET error">Stack trace: XXX</error>
		</testcase>
	  </testsuite>
	  <testsuite name="FCTesting" timestamp="2014-07-11T06:37:24" tests="2" failures="1" errors="0" time="0.03">
		<testcase name="BVT" classname="FCTesting.BVT" time="0" />
		<testcase name="NEGATIVE" classname="FCTesting.NEGATIVE" time="0">
		  <failure message="NEGATIVE fail">Stack trace: XXX</failure>
		</testcase>
	  </testsuite>
	</testsuites>
#>

[xml]$junitReport = $null
[object]$reportRootNode = $null
[string]$junitReportPath = ""
[bool]$isGenerateJunitReport=$False

Function StartLogReport([string]$reportPath)
{
	if(!$junitReport)
	{
		$global:junitReport = new-object System.Xml.XmlDocument
		$newElement = $global:junitReport.CreateElement("testsuites")
		$global:reportRootNode = $global:junitReport.AppendChild($newElement)
		
		$global:junitReportPath = $reportPath
		
		$global:isGenerateJunitReport = $True
	}
	else
	{
		throw "CI report has been created."
	}
	
	return $junitReport
}

Function FinishLogReport([bool]$isFinal=$True)
{
	if(!$global:isGenerateJunitReport)
	{
		return
	}
	
	$global:junitReport.Save($global:junitReportPath)
	if($isFinal)
	{
		$global:junitReport = $null
		$global:reportRootNode = $null
		$global:junitReportPath = ""
		$global:isGenerateJunitReport=$False
	}
}

Function StartLogTestSuite([string]$testsuiteName)
{
	if(!$global:isGenerateJunitReport)
	{
		return
	}
	
	$newElement = $global:junitReport.CreateElement("testsuite")
	$newElement.SetAttribute("name", $testsuiteName)
	$newElement.SetAttribute("timestamp", [Datetime]::Now.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss"))
	$newElement.SetAttribute("tests", 0)
	$newElement.SetAttribute("failures", 0)
	$newElement.SetAttribute("errors", 0)
	$newElement.SetAttribute("time", 0)
	$testsuiteNode = $global:reportRootNode.AppendChild($newElement)
	
	$timer = CIStartTimer
	$testsuite = New-Object -TypeName PSObject
	Add-Member -InputObject $testsuite -MemberType NoteProperty -Name testsuiteNode -Value $testsuiteNode -Force
	Add-Member -InputObject $testsuite -MemberType NoteProperty -Name timer -Value $timer -Force
	
	return $testsuite
}

Function FinishLogTestSuite([object]$testsuite)
{
	if(!$global:isGenerateJunitReport)
	{
		return
	}
	
	$testsuite.testsuiteNode.Attributes["time"].Value = CIStopTimer $testsuite.timer
	FinishLogReport $False
}

Function StartLogTestCase([object]$testsuite, [string]$caseName, [string]$className)
{
	if(!$global:isGenerateJunitReport)
	{
		return
	}
	
	$newElement = $global:junitReport.CreateElement("testcase")
	$newElement.SetAttribute("name", $caseName)
	$newElement.SetAttribute("classname", $classname)
	$newElement.SetAttribute("time", 0)
	
	$testcaseNode = $testsuite.testsuiteNode.AppendChild($newElement)
	
	$timer = CIStartTimer
	$testcase = New-Object -TypeName PSObject
	Add-Member -InputObject $testcase -MemberType NoteProperty -Name testsuite -Value $testsuite -Force
	Add-Member -InputObject $testcase -MemberType NoteProperty -Name testcaseNode -Value $testcaseNode -Force
	Add-Member -InputObject $testcase -MemberType NoteProperty -Name timer -Value $timer -Force
	return $testcase
}

Function FinishLogTestCase([object]$testcase, [string]$result="PASS", [string]$message="", [string]$detail="")
{
	if(!$global:isGenerateJunitReport)
	{
		return
	}
	
	$testcase.testcaseNode.Attributes["time"].Value = CIStopTimer $testcase.timer
	
	[int]$testcase.testsuite.testsuiteNode.Attributes["tests"].Value += 1
	if ($result -eq "FAIL")
	{
		$newChildElement = $global:junitReport.CreateElement("failure")
		$newChildElement.InnerText = $detail
		$newChildElement.SetAttribute("message", $message)
		$testcase.testcaseNode.AppendChild($newChildElement)
		
		[int]$testcase.testsuite.testsuiteNode.Attributes["failures"].Value += 1
	}
	
	if ($result -eq "ERROR")
	{
		$newChildElement = $global:junitReport.CreateElement("error")
		$newChildElement.InnerText = $detail
		$newChildElement.SetAttribute("message", $message)
		$testcase.testcaseNode.AppendChild($newChildElement)
		
		[int]$testcase.testsuite.testsuiteNode.Attributes["errors"].Value += 1
	}
	FinishLogReport $False
}

Function CIStartTimer()
{
	$timer = [system.diagnostics.stopwatch]::startNew()
	return $timer
}

Function CIStopTimer([System.Diagnostics.Stopwatch]$timer)
{
	$timer.Stop()
	return [System.Math]::Round($timer.Elapsed.TotalSeconds, 2)

}

Function AddReproVMDetailsToHtmlReport()
{
	$reproVMHtmlText += "<br><font size=`"2`"><em>Repro VMs: </em></font>"
	if ( $UserAzureResourceManager )
	{
		foreach ( $vm in $allVMData )
		{
			$reproVMHtmlText += "<br><font size=`"2`">ResourceGroup : $($vm.ResourceGroup), IP : $($vm.PublicIP), SSH : $($vm.SSHPort)</font>"
		}
	}
	else
	{
		foreach ( $vm in $allVMData )
		{
			$reproVMHtmlText += "<br><font size=`"2`">ServiceName : $($vm.ServiceName), IP : $($vm.PublicIP), SSH : $($vm.SSHPort)</font>"
		}
	}
	return $reproVMHtmlText
}

Function GetCurrentCycleData($xmlConfig, $cycleName)
{
	foreach ($Cycle in $xmlConfig.config.testCycles.Cycle )
	{
		if($cycle.cycleName -eq $cycleName)
		{
		return $cycle
		break
		}
	}

}

Function GetCurrentTestData($xmlConfig, $testName)
{
	foreach ($test in $xmlConfig.config.testsDefinition.test)
	{
		if ($test.testName -eq $testName)
		{
		LogMsg "Loading the test data for $($test.testName)"
		Set-Variable -Name CurrentTestData -Value $test -Scope Global -Force
		return $test
		break
		}
	}
}

Function RefineTestResult2 ($testResult)
{
	$i=0
	$tempResult = @()
	foreach ($cmp in $testResult)
	{
		if(($cmp -eq "PASS") -or ($cmp -eq "FAIL") -or ($cmp -eq "ABORTED") -or ($cmp -eq "Aborted"))
		{
			$tempResult += $testResult[$i]
			$tempResult += $testResult[$i+1]
			$testResult = $tempResult
			break
		}
		$i++;
	}
	return $testResult
}

Function RefineTestResult1 ($tempResult)
{
	foreach ($new in $tempResult)
	{
		$lastObject = $new
	}
	$tempResultSplitted = $lastObject.Split(" ")
	if($tempResultSplitted.Length > 1 )
	{
		Write-Host "Test Result =  $lastObject" -ForegroundColor Gray
	}
	$lastWord = ($tempResultSplitted.Length - 1)

	return $tempResultSplitted[$lastWord]
}

Function ValidateVHD($vhdPath)
{
    try
    {
        $tempVHDName = Split-Path $vhdPath -leaf
        LogMsg "Inspecting '$tempVHDName'. Please wait..."
        $VHDInfo = Get-VHD -Path $vhdPath -ErrorAction Stop
        LogMsg "  VhdFormat            :$($VHDInfo.VhdFormat)"
        LogMsg "  VhdType              :$($VHDInfo.VhdType)"
        LogMsg "  FileSize             :$($VHDInfo.FileSize)"
        LogMsg "  Size                 :$($VHDInfo.Size)"
        LogMsg "  LogicalSectorSize    :$($VHDInfo.LogicalSectorSize)"
        LogMsg "  PhysicalSectorSize   :$($VHDInfo.PhysicalSectorSize)"
        LogMsg "  BlockSize            :$($VHDInfo.BlockSize)"
        LogMsg "Validation successful."
    }
    catch
    {
        LogMsg "Failed: Get-VHD -Path $vhdPath"
        Throw "INVALID_VHD_EXCEPTION"
    }
}

Function ValidateMD5($filePath, $expectedMD5hash)
{
    LogMsg "Expected MD5 hash for $filePath : $($expectedMD5hash.ToUpper())"
    $hash = Get-FileHash -Path $filePath -Algorithm MD5
    LogMsg "Calculated MD5 hash for $filePath : $($hash.Hash.ToUpper())"
    if ($hash.Hash.ToUpper() -eq  $expectedMD5hash.ToUpper())
    {
        LogMsg "MD5 checksum verified successfully."
    }
    else
    {
        Throw "MD5 checksum verification failed."
    }
}

Function Test-FileLock 
{
	param 
	(
	  [parameter(Mandatory=$true)][string]$Path
	)
	$File = New-Object System.IO.FileInfo $Path
	if ((Test-Path -Path $Path) -eq $false) 
	{
		return $false
	}
	try 
	{
		$oStream = $File.Open([System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
		if ($oStream) 
		{
			$oStream.Close()
		}
		return $false
	} 
	catch 
	{
		# file is locked by a process.
		return $true
	}
}

Function CreateArrayOfTabs()
{
	$tab = @()
    for ( $i = 0; $i -lt 30; $i++)
    {
        $currentTab = ""
        for ( $j = 0; $j -lt $i; $j++)
        {
            $currentTab +=  "`t"
        }
        $tab += $currentTab
	}
	return $tab
}

Function UploadTestResultToDatabase ($TestPlatform,$TestLocation,$TestCategory,$TestArea,$TestName,$CurrentTestResult,$ExecutionTag,$GuestDistro,$KernelVersion,$LISVersion,$HostVersion,$VMSize,$Networking,$ARMImage,$OsVHD,$LogFile,$BuildURL)
{
	if ( $EnableTelemetry )
	{
		if ($XmlSecrets)
		{
			try
			{
				$TestResult = $CurrentTestResult.TestResult
				$TestSummary = $CurrentTestResult.TestSummary
				$UTCTime = (Get-Date).ToUniversalTime()
				$DateTimeUTC = "$($UTCTime.Year)-$($UTCTime.Month)-$($UTCTime.Day) $($UTCTime.Hour):$($UTCTime.Minute):$($UTCTime.Second)"
				$GlobalConfiguration = [xml](Get-Content .\XML\GlobalConfigurations.xml)
				$TestTag = $GlobalConfiguration.Global.$TestPlatform.ResultsDatabase.testTag
				$testLogStorageAccount = $XmlSecrets.secrets.testLogsStorageAccount
				$testLogStorageAccountKey = $XmlSecrets.secrets.testLogsStorageAccountKey
				$testLogFolder = "$($UTCTime.Year)-$($UTCTime.Month)-$($UTCTime.Day)"
				$ticks= (Get-Date).Ticks
				$uploadFileName = ".\Temp\$($TestName)-$ticks.zip"
				$out = ZipFiles -zipfilename $uploadFileName -sourcedir $LogDir
				$UploadedURL = .\Utilities\UploadFilesToStorageAccount.ps1 -filePaths $uploadFileName -destinationStorageAccount $testLogStorageAccount -destinationContainer "lisav2logs" -destinationFolder "$testLogFolder" -destinationStorageKey $testLogStorageAccountKey
				if ( $BuildURL )
				{
					$BuildURL = "$BuildURL`consoleFull"
				}
				else 
				{
					$BuildURL = ""	
				}
				if ( $TestPlatform -eq "HyperV")
				{
					$TestLocation = ($GlobalConfiguration.Global.$TestPlatform.Host.ServerName).ToLower()
				}
				elseif ($TestPlatform -eq "Azure")
				{
					$TestLocation = $TestLocation.ToLower()
				}
				$dataSource = $XmlSecrets.secrets.DatabaseServer
				$dbuser = $XmlSecrets.secrets.DatabaseUser
				$dbpassword = $XmlSecrets.secrets.DatabasePassword
				$database = $XmlSecrets.secrets.DatabaseName
				$dataTableName = "LISAv2Results"
				$SQLQuery = "INSERT INTO $dataTableName (DateTimeUTC,TestPlatform,TestLocation,TestCategory,TestArea,TestName,TestResult,SubTestName,SubTestResult,ExecutionTag,GuestDistro,KernelVersion,LISVersion,HostVersion,VMSize,Networking,ARMImage,OsVHD,LogFile,BuildURL) VALUES "
				$SQLQuery += "('$DateTimeUTC','$TestPlatform','$TestLocation','$TestCategory','$TestArea','$TestName','$testResult','','','$ExecutionTag','$GuestDistro','$KernelVersion','$LISVersion','$HostVersion','$VMSize','$Networking','$ARMImageName','$OsVHD','$UploadedURL', '$BuildURL'),"
				if ($TestSummary)
				{
					foreach ($tempResult in $TestSummary.Split('>'))
					{
						if ($tempResult)
						{
							$tempResult = $tempResult.Trim().Replace("<br /","").Trim()
							$subTestResult = $tempResult.Split(":")[$tempResult.Split(":").Count -1 ].Trim()
							$subTestName = $tempResult.Replace("$subTestResult","").Trim().TrimEnd(":").Trim()
							$SQLQuery += "('$DateTimeUTC','$TestPlatform','$TestLocation','$TestCategory','$TestArea','$TestName','$testResult','$subTestName','$subTestResult','$ExecutionTag','$GuestDistro','$KernelVersion','$LISVersion','$HostVersion','$VMSize','$Networking','$ARMImageName','$OsVHD','$UploadedURL', '$BuildURL'),"
						}
					}
				}
				$SQLQuery = $SQLQuery.TrimEnd(',')
				$connectionString = "Server=$dataSource;uid=$dbuser; pwd=$dbpassword;Database=$database;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
				$connection = New-Object System.Data.SqlClient.SqlConnection
				$connection.ConnectionString = $connectionString
				$connection.Open()
				LogMsg $SQLQuery
				$command = $connection.CreateCommand()
				$command.CommandText = $SQLQuery
				$result = $command.executenonquery()
				$connection.Close()
				LogMsg "Uploading test results to database :  done!!"
			}
			catch
			{			
				LogErr "Uploading test results to database :  ERROR"
				$line = $_.InvocationInfo.ScriptLineNumber
				$script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
				$ErrorMessage =  $_.Exception.Message
				LogMsg "EXCEPTION : $ErrorMessage"
				LogMsg "Source : Line $line in script $script_name."			
			}
		}
		else 
		{
			LogErr "Unable to send telemetry data to Azure. XML Secrets file not provided."	
		}
	}
}