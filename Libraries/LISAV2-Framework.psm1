##############################################################################################
# Framework-Azure.psm1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
    Pipeline framework modules for Azure environment.

.PARAMETER
    <Parameters>

.INPUTS


.NOTES
    Creation Date:
    Purpose/Change:

.EXAMPLE


#>
###############################################################################################

function Validate-AzureParameters {
    $parameterErrors = @()
    if ( !$ARMImageName -and !$OsVHD ) {
        $parameterErrors += "-ARMImageName '<Publisher> <Offer> <Sku> <Version>', or -OsVHD <'VHD_Name.vhd'> is required."
    }

    if (!$OsVHD) {
        if (($ARMImageName.Trim().Split(" ").Count -ne 4) -and ($ARMImageName -ne "")) {
            $parameterErrors += ("Invalid value for the provided ARMImageName parameter: <'${ARMImageName}'>." + `
                                 "The ARM image should be in the format: '<Publisher> <Offer> <Sku> <Version>'.")
        }
    }

    if (!$ARMImageName) {
        if ($OsVHD -and [System.IO.Path]::GetExtension($OsVHD) -ne ".vhd") {
            $parameterErrors += "-OsVHD $OsVHD does not have .vhd extension required by Platform Azure."
        }
    }

    if (!$TestLocation) {
        $parameterErrors += "-TestLocation <AzureRegion> is required."
    }

    if ([string]$VMGeneration -eq "2") {
        $parameterErrors += "-VMGeneration 2 is not supported on Azure."
    }
    return $parameterErrors
}

function Validate-HyperVParameters {
    $parameterErrors = @()
    if (!$OsVHD ) {
        $parameterErrors += "-OsVHD <'VHD_Name.vhd'> is required."
    }
    return $parameterErrors
}

function Validate-Parameters {
    $parameterErrors = @()
    $supportedPlatforms = @("Azure", "HyperV")

    if ($supportedPlatforms.contains($TestPlatform)) {

        # Validate general parameters
        if ( !$RGIdentifier ) {
            $parameterErrors += "-RGIdentifier <ResourceGroupIdentifier> is required."
        }
        if (!$VMGeneration) {
			# Set VM Generation default value to 1, if not specified.
			LogMsg "-VMGeneration not specified. Using default VMGeneration = 1"
			Set-Variable -Name VMGeneration -Value 1 -Scope Global
        } else {
            $supportedVMGenerations = @("1","2")
            if ($supportedVMGenerations.contains([string]$VMGeneration)) {
                if ([string]$VMGeneration -eq "2" -and $OsVHD `
                         -and [System.IO.Path]::GetExtension($OsVHD) -ne ".vhdx") {
                    $parameterErrors += "-VMGeneration 2 requires .vhdx files."
                }
            } else {
                $parameterErrors += "-VMGeneration $VMGeneration is not yet supported."
            }
        }

        # Validate platform dependent parameters
        $parameterErrors += & "Validate-${TestPlatform}Parameters"
    } else {
        if ($TestPlatform) {
            $parameterErrors += "$TestPlatform is not yet supported."
        } else {
            $parameterErrors += "'-TestPlatform' is not provided."
        }
    }
    if ($parameterErrors.Count -gt 0) {
        $parameterErrors | ForEach-Object { LogError $_ }
        throw "Failed to validate the test parameters provided. Please fix above issues and retry."
    } else {
        LogMsg "Test parameters have been validated successfully. Continue running the test."
    }
}

Function Inject-CustomTestParameters($CustomParameters, $ReplaceableTestParameters, $TestConfigurationXmlFile)
{
	if ($CustomParameters)
	{
		LogMsg "Checking custom parameters ..."
		$CustomParameters = $CustomParameters.Trim().Trim(";").Split(";")
		foreach ($CustomParameter in $CustomParameters)
		{
			$CustomParameter = $CustomParameter.Trim()
			$ReplaceThis = $CustomParameter.Split("=")[0]
			$ReplaceWith = $CustomParameter.Split("=")[1]
			$OldValue = ($ReplaceableTestParameters.ReplaceableTestParameters.Parameter | Where-Object `
				{ $_.ReplaceThis -eq $ReplaceThis }).ReplaceWith
			($ReplaceableTestParameters.ReplaceableTestParameters.Parameter | Where-Object `
				{ $_.ReplaceThis -eq $ReplaceThis }).ReplaceWith = $ReplaceWith
			LogMsg "Custom Parameter: $ReplaceThis=$OldValue --> $ReplaceWith"
		}
		LogMsg "Custom parameter(s) are ready to be injected along with default parameters, if any."
	}

	$XmlConfigContents = (Get-Content -Path $TestConfigurationXmlFile)
	foreach ($ReplaceableParameter in $ReplaceableTestParameters.ReplaceableTestParameters.Parameter)
	{
		if ($XmlConfigContents -match $ReplaceableParameter.ReplaceThis)
		{
			$XmlConfigContents = $XmlConfigContents.Replace($ReplaceableParameter.ReplaceThis,$ReplaceableParameter.ReplaceWith)
			LogMsg "$($ReplaceableParameter.ReplaceThis)=$($ReplaceableParameter.ReplaceWith) injected into $TestConfigurationXmlFile"
		}
	}
	Set-Content -Value $XmlConfigContents -Path $TestConfigurationXmlFile -Force
}

Function UpdateGlobalConfigurationXML($XmlSecretsFilePath)
{
	# The file $XmlSecretsFilePath has been validated before calling this function
	Get-ChildItem (Join-Path "." "Libraries") -Recurse | `
		Where-Object { $_.FullName.EndsWith(".psm1") } | `
		ForEach-Object { Import-Module $_.FullName -Force -Global -DisableNameChecking }

	$XmlSecrets = [xml](Get-Content $XmlSecretsFilePath)
	$GlobalConfigurationXMLFilePath = Resolve-Path ".\XML\GlobalConfigurations.xml"
	$GlobalXML = [xml](Get-Content $GlobalConfigurationXMLFilePath)
	$RegionAndStorageAccountsXMLFilePath = Resolve-Path ".\XML\RegionAndStorageAccounts.xml"
	$RegionStorageMapping = [xml](Get-Content $RegionAndStorageAccountsXMLFilePath)

	$GlobalXML.Global.Azure.Subscription.SubscriptionID = $XmlSecrets.secrets.SubscriptionID
	$GlobalXML.Global.Azure.TestCredentials.LinuxUsername = $XmlSecrets.secrets.linuxTestUsername
	$GlobalXML.Global.Azure.TestCredentials.LinuxPassword = $XmlSecrets.secrets.linuxTestPassword
	$GlobalXML.Global.Azure.ResultsDatabase.server = $XmlSecrets.secrets.DatabaseServer
	$GlobalXML.Global.Azure.ResultsDatabase.user = $XmlSecrets.secrets.DatabaseUser
	$GlobalXML.Global.Azure.ResultsDatabase.password = $XmlSecrets.secrets.DatabasePassword
	$GlobalXML.Global.Azure.ResultsDatabase.dbname = $XmlSecrets.secrets.DatabaseName
	$GlobalXML.Global.HyperV.TestCredentials.LinuxUsername = $XmlSecrets.secrets.linuxTestUsername
	$GlobalXML.Global.HyperV.TestCredentials.LinuxPassword = $XmlSecrets.secrets.linuxTestPassword
	$GlobalXML.Global.HyperV.ResultsDatabase.server = $XmlSecrets.secrets.DatabaseServer
	$GlobalXML.Global.HyperV.ResultsDatabase.user = $XmlSecrets.secrets.DatabaseUser
	$GlobalXML.Global.HyperV.ResultsDatabase.password = $XmlSecrets.secrets.DatabasePassword
	$GlobalXML.Global.HyperV.ResultsDatabase.dbname = $XmlSecrets.secrets.DatabaseName

	if ($TestPlatform -eq "Azure")
	{
		if ( $StorageAccount -imatch "ExistingStorage_Standard" )
		{
			$GlobalXML.Global.$TestPlatform.Subscription.ARMStorageAccount = $RegionStorageMapping.AllRegions.$TestLocation.StandardStorage
		}
		elseif ( $StorageAccount -imatch "ExistingStorage_Premium" )
		{
			$GlobalXML.Global.$TestPlatform.Subscription.ARMStorageAccount = $RegionStorageMapping.AllRegions.$TestLocation.PremiumStorage
		}
		elseif ( $StorageAccount -imatch "NewStorage_Standard" )
		{
			$GlobalXML.Global.$TestPlatform.Subscription.ARMStorageAccount = "NewStorage_Standard_LRS"
		}
		elseif ( $StorageAccount -imatch "NewStorage_Premium" )
		{
			$GlobalXML.Global.$TestPlatform.Subscription.ARMStorageAccount = "NewStorage_Premium_LRS"
		}
		elseif ($StorageAccount -eq "")
		{
			$GlobalXML.Global.$TestPlatform.Subscription.ARMStorageAccount = $RegionStorageMapping.AllRegions.$TestLocation.StandardStorage
			LogMsg "Auto selecting storage account : $($GlobalXML.Global.$TestPlatform.Subscription.ARMStorageAccount) as per your test region."
		}
		elseif ($StorageAccount)
		{
			$GlobalXML.Global.$TestPlatform.Subscription.ARMStorageAccount = $StorageAccount.Trim()
			LogMsg "Selecting custom storage account : $($GlobalXML.Global.$TestPlatform.Subscription.ARMStorageAccount) as per your test region."
		}
	}
	if ($TestPlatform -eq "HyperV")
	{
		if ( $SourceOsVHDPath )
		{
			for( $index=0 ; $index -lt $GlobalXML.Global.$TestPlatform.Hosts.ChildNodes.Count ; $index++ ) {
				$GlobalXML.Global.$TestPlatform.Hosts.ChildNodes[$index].SourceOsVHDPath = $SourceOsVHDPath
			}
		}
		if ( $DestinationOsVHDPath )
		{
			for( $index=0 ; $index -lt $GlobalXML.Global.$TestPlatform.Hosts.ChildNodes.Count ; $index++ ) {
				$GlobalXML.Global.$TestPlatform.Hosts.ChildNodes[$index].DestinationOsVHDPath = $DestinationOsVHDPath
			}
		}
		if ($TestLocation)
		{
			$Locations = $TestLocation.split(',')
			$index = 0
			foreach($Location in $Locations)
			{
				$GlobalXML.Global.$TestPlatform.Hosts.ChildNodes[$index].ServerName = $Location
				Get-VM -ComputerName $GlobalXML.Global.$TestPlatform.Hosts.ChildNodes[$index].ServerName | Out-Null
				if ($?)
				{
					LogMsg "Set '$($Location)' to As GlobalConfiguration.Global.HyperV.Hosts.ChildNodes[$($index)].ServerName"
				}
				else
				{
					LogErr "Did you used -TestLocation XXXXXXX. In HyperV mode, -TestLocation can be used to Override HyperV server mentioned in GlobalConfiguration XML file."
					LogErr "In HyperV mode, -TestLocation can be used to Override HyperV server mentioned in GlobalConfiguration XML file."
					Throw "Unable to access HyperV server - '$($Location)'"
				}
				$index++
			}
		}
		else
		{
			$TestLocation = $GlobalXML.Global.$TestPlatform.Hosts.ChildNodes[0].ServerName
			LogMsg "Read Test Location from GlobalConfiguration.Global.HyperV.Hosts.ChildNodes[0].ServerName"
			Get-VM -ComputerName $TestLocation | Out-Null
		}
	}
	#If user provides Result database / result table, then add it to the GlobalConfiguration.
	if( $ResultDBTable -or $ResultDBTestTag)
	{
		if( $ResultDBTable )
		{
			$GlobalXML.Global.$TestPlatform.ResultsDatabase.dbtable = ($ResultDBTable).Trim()
			LogMsg "ResultDBTable : $ResultDBTable added to .\XML\GlobalConfigurations.xml"
		}
		if( $ResultDBTestTag )
		{
			$GlobalXML.Global.$TestPlatform.ResultsDatabase.testTag = ($ResultDBTestTag).Trim()
			LogMsg "ResultDBTestTag: $ResultDBTestTag added to .\XML\GlobalConfigurations.xml"
		}
	}
	#$GlobalConfiguration.Save("$WorkingDirectory\XML\GlobalConfigurations.xml")
	$GlobalXML.Save($GlobalConfigurationXMLFilePath )
	LogMsg "Updated GlobalConfigurations.xml file."
}

Function UpdateXMLStringsFromSecretsFile($XmlSecretsFilePath)
{
	# The file $XmlSecretsFilePath has been validated before calling this function
	$TestXMLs = Get-ChildItem -Path ".\XML\TestCases\*.xml"
	$XmlSecrets = [xml](Get-Content $XmlSecretsFilePath)
	foreach ($file in $TestXMLs)
	{
		$CurrentXMLText = Get-Content -Path $file.FullName
		foreach ($Replace in $XmlSecrets.secrets.ReplaceTestXMLStrings.Replace)
		{
			$ReplaceString = $Replace.Split("=")[0]
			$ReplaceWith = $Replace.Split("=")[1]
			if ($CurrentXMLText -imatch $ReplaceString)
			{
				$content = [System.IO.File]::ReadAllText($file.FullName).Replace($ReplaceString,$ReplaceWith)
				[System.IO.File]::WriteAllText($file.FullName, $content)
				LogMsg "$ReplaceString replaced in $($file.FullName)"
			}
		}
	}
	LogMsg "Updated Test Case xml files."
}

Function Match-TestPriority($currentTest)
{
    if( -not $TestPriority ) {
        return $True
    }

    $priorityInXml = $currentTest.Priority
    if (-not $priorityInXml) {
        LogMsg "Warning: Priority of $($currentTest.TestName) is not defined, set its priority 1 by default."
        $priorityInXml = 1
    }
    foreach( $priority in $TestPriority.Split(",") ) {
        if ($priorityInXml -eq $priority) {
            return $True
        }
    }
    return $False
}

Function CollectTestCases($TestXMLs)
{
    if ( $TestCategory -eq "All") { $TestCategory = "" }
    if ( $TestArea -eq "All") { $TestArea = "" }
    if ( $TestNames -eq "All") { $TestNames = "" }
    if ( $TestTag -eq "All") { $TestTag = "" }
    $AllLisaTests = @()
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
                        $status = Match-TestPriority -currentTest $test
                        if ($status) {
                            LogMsg "Collected $($test.TestName)"
                            $AllLisaTests += $test
                        }
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
                        $status = Match-TestPriority -currentTest $test
                        if ($status) {
                            LogMsg "Collected $($test.TestName)"
                            $AllLisaTests += $test
                        }
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
                    if (($test.Platform.Split(",").Contains($TestPlatform) ) -and $($TestCategory -eq $test.Category) `
                        -and $($TestArea.Split(",").Contains($test.Area)))
                    {
                        $status = Match-TestPriority -currentTest $test
                        if ($status) {
                            LogMsg "Collected $($test.TestName)"
                            $AllLisaTests += $test
                        }
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
                        $status = Match-TestPriority -currentTest $test
                        if ($status) {
                            LogMsg "Collected $($test.TestName)"
                            $AllLisaTests += $test
                        }
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
                        $status = Match-TestPriority -currentTest $test
                        if ($status) {
                            LogMsg "Collected $($test.TestName)"
                            $AllLisaTests += $test
                        }
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
                        $status = Match-TestPriority -currentTest $test
                        if ($status) {
                            LogMsg "Collected $($test.TestName)"
                            $AllLisaTests += $test
                        }
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
        LogError "TestPriority : $TestPriority"
        Throw "Invalid Test Selection"
    }
    return $AllLisaTests
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
    $str = "<br />[LISAv2 Test Results Summary]<br />"
    $str += "Test Run On           : " + $startTime
    if ( $BaseOsImage )
    {
        $str += "<br />Image Under Test      : " + $BaseOsImage
    }
    if ( $BaseOSVHD )
    {
        $str += "<br />VHD Under Test        : " + $BaseOSVHD
    }
    if ( $ARMImage )
    {
        $str += "<br />ARM Image Under Test  : " + "$($ARMImage.Publisher) : $($ARMImage.Offer) : $($ARMImage.Sku) : $($ARMImage.Version)"
    }
	$str += "<br />Total Test Cases      : " + $testSuiteResultDetails.totalTc + " (" + $testSuiteResultDetails.totalPassTc + " Pass" + ", " + $testSuiteResultDetails.totalFailTc + " Fail" + ", " + $testSuiteResultDetails.totalAbortedTc + " Abort)"
	$str += "<br />Total Time (dd:hh:mm) : " + $testSuiteRunDuration.ToString()
	$str += "<br />XML File              : $xmlFilename<br /><br />"

    # Add information about the host running ICA to the e-mail summary
    $str += "<pre>"
    $str += $testCycle.emailSummary + "<br />"
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
    # Highlight the failed tests
    $body = $body.Replace("Aborted", '<em style="background:Yellow; color:Red">Aborted</em>')
    $body = $body.Replace("FAIL", '<em style="background:Yellow; color:Red">Failed</em>')

	Send-mailMessage -to $to -from $from -subject $subject -body $body -smtpserver $smtpServer -BodyAsHtml
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

Function StartLogReport([string]$reportPath)
{
	if(!$junitReport)
	{
		$global:junitReport = new-object System.Xml.XmlDocument
		$newElement = $global:junitReport.CreateElement("testsuites")
		$global:reportRootNode = $global:junitReport.AppendChild($newElement)
		$global:junitReportPath = $reportPath
		$global:isGenerateJunitReport = $True
		# To avoid PSUseDeclaredVarsMoreThanAssignments warning when run PS Analyzer
		LogMsg "global parameter reportRootNode is set to $global:reportRootNode"
		LogMsg "global parameter junitReportPath is set to $global:junitReportPath"
		LogMsg "global parameter isGenerateJunitReport is set to $global:isGenerateJunitReport"
	}
	else
	{
		throw "LISAv2 test report has been created."
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
		# To avoid PSUseDeclaredVarsMoreThanAssignments warning when run PS Analyzer
		LogMsg "global parameter junitReport is set to $global:junitReport  (null)"
		LogMsg "global parameter reportRootNode is set to $global:reportRootNode  (null)"
		LogMsg "global parameter junitReportPath is set to $global:junitReportPath (Empty)"
		LogMsg "global parameter isGenerateJunitReport is set to $global:isGenerateJunitReport (False)"
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

Function Get-SQLQueryOfTelemetryData ($TestPlatform,$TestLocation,$TestCategory,$TestArea,$TestName,$CurrentTestResult, `
									$ExecutionTag,$GuestDistro,$KernelVersion,$LISVersion,$HostVersion,$VMSize, `
									$Networking,$ARMImage,$OsVHD,$LogFile,$BuildURL)
{
	if ($EnableTelemetry) {
		try
		{
			$TestResult = $CurrentTestResult.TestResult
			$TestSummary = $CurrentTestResult.TestSummary
			$UTCTime = (Get-Date).ToUniversalTime()
			$DateTimeUTC = "$($UTCTime.Year)-$($UTCTime.Month)-$($UTCTime.Day) $($UTCTime.Hour):$($UTCTime.Minute):$($UTCTime.Second)"
			$GlobalConfiguration = [xml](Get-Content .\XML\GlobalConfigurations.xml)
			$testLogStorageAccount = $XmlSecrets.secrets.testLogsStorageAccount
			$testLogStorageAccountKey = $XmlSecrets.secrets.testLogsStorageAccountKey
			$testLogFolder = "$($UTCTime.Year)-$($UTCTime.Month)-$($UTCTime.Day)"
			$ticks= (Get-Date).Ticks
			$uploadFileName = Join-Path $env:TEMP "$TestName-$ticks.zip"
			$null = New-ZipFile -zipFileName $uploadFileName -sourceDir $LogDir
			$UploadedURL = .\Utilities\UploadFilesToStorageAccount.ps1 -filePaths $uploadFileName `
			-destinationStorageAccount $testLogStorageAccount -destinationContainer "lisav2logs" `
			-destinationFolder "$testLogFolder" -destinationStorageKey $testLogStorageAccountKey
			if ($BuildURL) {
				$BuildURL = "$BuildURL`consoleFull"
			} else {
				$BuildURL = ""
			}
			if ($TestPlatform -eq "HyperV") {
				$TestLocation = ($GlobalConfiguration.Global.$TestPlatform.Hosts.ChildNodes[0].ServerName).ToLower()
			} elseif ($TestPlatform -eq "Azure") {
				$TestLocation = $TestLocation.ToLower()
			}
			$dataTableName = "LISAv2Results"
			$SQLQuery = "INSERT INTO $dataTableName (DateTimeUTC,TestPlatform,TestLocation,TestCategory,TestArea,TestName,TestResult,SubTestName,SubTestResult,ExecutionTag,GuestDistro,KernelVersion,LISVersion,HostVersion,VMSize,Networking,ARMImage,OsVHD,LogFile,BuildURL) VALUES "
			$SQLQuery += "('$DateTimeUTC','$TestPlatform','$TestLocation','$TestCategory','$TestArea','$TestName','$testResult','','','$ExecutionTag','$GuestDistro','$KernelVersion','$LISVersion','$HostVersion','$VMSize','$Networking','$ARMImageName','$OsVHD','$UploadedURL', '$BuildURL'),"
			if ($TestSummary) {
				foreach ($tempResult in $TestSummary.Split('>')) {
					if ($tempResult) {
						$tempResult = $tempResult.Trim().Replace("<br /","").Trim()
						$subTestResult = $tempResult.Split(":")[$tempResult.Split(":").Count -1 ].Trim()
						$subTestName = $tempResult.Replace("$subTestResult","").Trim().TrimEnd(":").Trim()
						$SQLQuery += "('$DateTimeUTC','$TestPlatform','$TestLocation','$TestCategory','$TestArea','$TestName','$testResult','$subTestName','$subTestResult','$ExecutionTag','$GuestDistro','$KernelVersion','$LISVersion','$HostVersion','$VMSize','$Networking','$ARMImageName','$OsVHD','$UploadedURL', '$BuildURL'),"
					}
				}
			}
			$SQLQuery = $SQLQuery.TrimEnd(',')
			LogMsg "Get the SQL query of test results:  done"
			return $SQLQuery
		}
		catch
		{
			LogErr "Get the SQL query of test results:  ERROR"
			$line = $_.InvocationInfo.ScriptLineNumber
			$script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
			$ErrorMessage =  $_.Exception.Message
			LogMsg "EXCEPTION : $ErrorMessage"
			LogMsg "Source : Line $line in script $script_name."
		}
	} else {
		return $null
	}
}

Function UploadTestResultToDatabase ($SQLQuery)
{
	if ($XmlSecrets) {
		$dataSource = $XmlSecrets.secrets.DatabaseServer
		$dbuser = $XmlSecrets.secrets.DatabaseUser
		$dbpassword = $XmlSecrets.secrets.DatabasePassword
		$database = $XmlSecrets.secrets.DatabaseName

		if ($dataSource -and $dbuser -and $dbpassword -and $database) {
			try
			{
				LogMsg "SQLQuery:  $SQLQuery"
				$connectionString = "Server=$dataSource;uid=$dbuser; pwd=$dbpassword;Database=$database;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
				$connection = New-Object System.Data.SqlClient.SqlConnection
				$connection.ConnectionString = $connectionString
				$connection.Open()
				$command = $connection.CreateCommand()
				$command.CommandText = $SQLQuery
				$null = $command.executenonquery()
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
		} else {
			LogErr "Database details are not provided. Results will not be uploaded to database!!"
		}
	} else {
		LogErr "Unable to send telemetry data to Azure. XML Secrets file not provided."
	}
}

Function Get-LISAv2Tools($XMLSecretFile)
{
	# Copy required binary files to working folder
	$CurrentDirectory = Get-Location
	$CmdArray = @('7za.exe','dos2unix.exe','gawk','jq','plink.exe','pscp.exe', `
					'kvp_client32','kvp_client64','nc.exe')

	if ($XMLSecretFile) {
		$WebClient = New-Object System.Net.WebClient
		$xmlSecret = [xml](Get-Content $XMLSecretFile)
		$toolFileAccessLocation = $xmlSecret.secrets.blobStorageLocation
	}

	$CmdArray | ForEach-Object {
		# Verify the binary file in Tools location
		if (! (Test-Path $CurrentDirectory/Tools/$_) ) {
			LogErr "$_ file is not found in Tools folder."
		    if ($toolFileAccessLocation) {
		        $WebClient.DownloadFile("$toolFileAccessLocation/$_","$CurrentDirectory\Tools\$_")
		        LogMsg "File $_ successfully downloaded in Tools folder: $CurrentDirectory\Tools."
		    } else {
		        Throw "$_ file is not found, please either download the file to Tools folder, or specify the blobStorageLocation in XMLSecretFile"
            }
        }
	}
}


function Get-SecretParams {
    <#
    .DESCRIPTION
    Used only if the "SECRET_PARAMS" parameter exists in the test definition xml.
    Used to specify parameters that should be passed to test script but cannot be
    present in the xml test definition or are unknown before runtime.
    #>

    param(
        [array]$ParamsArray,
        [xml]$XMLConfig
    )

    $platform = $XMLConfig.config.CurrentTestPlatform
    $testParams = @{}

    foreach ($param in $ParamsArray.Split(',')) {
        switch ($param) {
            "Password" {
                $value = $($XMLConfig.config.$platform.Deployment.Data.Password)
                $testParams["PASSWORD"] = $value
            }
            "RoleName" {
                $value = $AllVMData.RoleName | ?{$_ -notMatch "dependency"}
                $testParams["ROLENAME"] = $value
            }
            "Distro" {
                $value = $detectedDistro
                $testParams["DETECTED_DISTRO"] = $value
            }
            "Ipv4" {
                $value = $AllVMData.PublicIP
                $testParams["ipv4"] = $value
            }
            "VM2Name" {
                $value = $DependencyVmName
                $testParams["VM2Name"] = $value
            }
            "CheckpointName" {
                $value = "ICAbase"
                $testParams["CheckpointName"] = $value
            }
        }
    }

    return $testParams
}

function Parse-TestParameters {
    <#
    .DESCRIPTION
    Converts the parameters specified in the test definition into a hashtable
    to be used later in test.
    #>

    param(
        $XMLParams,
        $XMLConfig
    )

    $testParams = @{}
    foreach ($param in $XMLParams.param) {
        $name = $param.split("=")[0]
        if ($name -eq "SECRET_PARAMS") {
            $paramsArray = $param.split("=")[1].trim("(",")"," ").split(" ")
            $testParams += Get-SecretParams -ParamsArray $paramsArray `
                 -XMLConfig $XMLConfig
        } else {
            $value = $param.split("=")[1]
            $testParams[$name] = $value
        }
    }

    return $testParams
}

function Run-SetupScript {
    <#
    .DESCRIPTION
    Executes a powershell script specified in the <setupscript> tag
    Used to further prepare environment/VM
    #>

    param(
        [string]$Script,
        [hashtable]$Parameters
    )
    $workDir = Get-Location
    $scriptLocation = Join-Path $workDir $Script
    $scriptParameters = ""
    foreach ($param in $Parameters.Keys) {
        $scriptParameters += "${param}=$($Parameters[$param]);"
    }
    $msg = ("Test setup/cleanup started using script:{0} with parameters:{1}" `
             -f @($Script,$scriptParameters))
    LogMsg $msg
    $result = & "${scriptLocation}" -TestParams $scriptParameters
    return $result
}

function Create-ConstantsFile {
    <#
    .DESCRIPTION
    Generic function that creates the constants.sh file using a hashtable
    #>

    param(
        [string]$FilePath,
        [hashtable]$Parameters
    )

    Set-Content -Value "#Generated by LISAv2" -Path $FilePath -Force
    foreach ($param in $Parameters.Keys) {
        Add-Content -Value ("{0}={1}" `
                 -f @($param,$($Parameters[$param]))) -Path $FilePath -Force
        $msg = ("{0}={1} added to constants.sh file" `
                 -f @($param,$($Parameters[$param])))
        LogMsg $msg
    }
}

function Run-TestScript {
    <#
    .DESCRIPTION
    Executes test scripts specified in the <testScript> tag.
    Supports python, shell and powershell scripts.
    Python and shell scripts will be executed remotely.
    Powershell scripts will be executed host side.
    After the test completion, the method will collect logs
    (for shell and python) and return the relevant test result.
    #>

    param(
        [string]$Script,
        [hashtable]$Parameters,
        [string]$LogDir,
        $VMData,
        $XMLConfig,
        [string]$Username,
        [string]$Password,
        [string]$TestName,
        [string]$TestLocation,
        [int]$Timeout
    )

    $workDir = Get-Location
    $scriptName = $Script.split(".")[0]
    $scriptExtension = $Script.split(".")[1]
    $constantsPath = Join-Path $workDir "constants.sh"
    $testResult = ""

    Create-ConstantsFile -FilePath $constantsPath -Parameters $Parameters
    if(!$IsWindows){
        foreach ($VM in $VMData) {
            RemoteCopy -upload -uploadTo $VM.PublicIP -Port $VM.SSHPort `
                -files $constantsPath -Username $Username -password $Password
            LogMsg "Constants file uploaded to: $($VM.RoleName)"
        }
    }
    LogMsg "Test script: ${Script} started."
    if ($scriptExtension -eq "sh") {
        RunLinuxCmd -Command "echo '${Password}' | sudo -S -s eval `"export HOME=``pwd``;bash ${Script} > ${TestName}_summary.log 2>&1`"" `
             -Username $Username -password $Password -ip $VMData.PublicIP -Port $VMData.SSHPort `
             -runMaxAllowedTime $Timeout
    } elseif ($scriptExtension -eq "ps1") {
        $scriptDir = Join-Path $workDir "Testscripts\Windows"
        $scriptLoc = Join-Path $scriptDir $Script
        foreach ($param in $Parameters.Keys) {
            $scriptParameters += (";{0}={1}" -f ($param,$($Parameters[$param])))
        }
        LogMsg "${scriptLoc} -TestParams $scriptParameters"
        $testResult = & "${scriptLoc}" -TestParams $scriptParameters
    } elseif ($scriptExtension -eq "py") {
        RunLinuxCmd -Username $Username -password $Password -ip $VMData.PublicIP -Port $VMData.SSHPort `
             -Command "python ${Script}" -runMaxAllowedTime $Timeout -runAsSudo
        RunLinuxCmd -Username $Username -password $Password -ip $VMData.PublicIP -Port $VMData.SSHPort `
             -Command "mv Runtime.log ${TestName}_summary.log" -runAsSudo
    }

    if (-not $testResult) {
        $testResult = Collect-TestLogs -LogsDestination $LogDir -ScriptName $scriptName -TestType $scriptExtension `
             -PublicIP $VMData.PublicIP -SSHPort $VMData.SSHPort -Username $Username -password $Password `
             -TestName $TestName
    }
    return $testResult
}

function Collect-TestLogs {
    <#
    .DESCRIPTION
    Collects logs created by the test script.
    The function collects logs only if a shell/python test script is executed.
    #>

    param(
        [string]$LogsDestination,
        [string]$ScriptName,
        [string]$PublicIP,
        [string]$SSHPort,
        [string]$Username,
        [string]$Password,
        [string]$TestType,
        [string]$TestName
    )
    # Note: This is a temporary solution until a standard is decided
    # for what string py/sh scripts return
    $resultTranslation = @{ "TestAborted" = "Aborted";
                            "TestFailed" = "FAIL";
                            "TestCompleted" = "PASS"
                          }

    if ($TestType -eq "sh") {
        $filesTocopy = "{0}/state.txt, {0}/summary.log, {0}/TestExecution.log, {0}/TestExecutionError.log" `
            -f @("/home/${Username}")
        RemoteCopy -download -downloadFrom $PublicIP -downloadTo $LogsDestination `
             -Port $SSHPort -Username "root" -password $Password `
             -files $filesTocopy
        $summary = Get-Content (Join-Path $LogDir "summary.log")
        $testState = Get-Content (Join-Path $LogDir "state.txt")
        $testResult = $resultTranslation[$testState]
    } elseif ($TestType -eq "py") {
        $filesTocopy = "{0}/state.txt, {0}/Summary.log, {0}/${TestName}_summary.log" `
            -f @("/home/${Username}")
        RemoteCopy -download -downloadFrom $PublicIP -downloadTo $LogsDestination `
             -Port $SSHPort -Username "root" -password $Password `
             -files $filesTocopy
        $summary = Get-Content (Join-Path $LogDir "Summary.log")
        $testResult = $summary
    }

    LogMsg "TEST SCRIPT SUMMARY ~~~~~~~~~~~~~~~"
    $summary | ForEach-Object {
        Write-Host $_ -ForegroundColor Gray -BackgroundColor White
    }
    LogMsg "END OF TEST SCRIPT SUMMARY ~~~~~~~~~~~~~~~"

    return $testResult
}

function Run-Test {
<#
    .SYNOPSIS
    Common framework used for test execution. Supports Azure and Hyper-V platforms.

    .DESCRIPTION
    The Run-Test function implements the existing LISAv2 methods into a common
    framework used to run tests.
    The function is comprised of the next steps:

    - Test resource deployment step:
        Deploys VMs and other necessary resources (network interfaces, virtual networks).
        Enables root user for all VMs in deployment.
        For Hyper-V it creates one snapshot for each VM in deployment.
    - Setup script execution step (Hyper-V only):
        Executes a setup script to further prepare environment/VMs.
        The script is specified in the test definition using the <SetupScript> tag.
    - Test dependency upload step:
        Uploads all files specified inside the test definition <files> tag.
    - Test execution step:
        Creates and uploads the constants.sh used to pass parameters to remote scripts
        (constants.sh file contains parameters specified in the <testParams> tag).
        Executes the test script specified in the <testScript> tag
        (the shell/python scripts will be executed remotely).
        Downloads logs for created by shell/python test scripts.
    - Test resource cleanup step:
        Removes deployed resources depending on the test result and parameters.

    .PARAMETER CurrentTestData
        Test definition xml structure.

    .PARAMETER XmlConfig
        Xml structure that contains all the relevant information about test/deployment.

    .PARAMETER Distro
        Distro under test.

    .PARAMETER VMUser
        Username used in all VMs in deployment.

    .PARAMETER VMPassword
        Password used in all VMs in deployment.

    .PARAMETER ExecuteSetup
        Switch variable that specifies if the framework should create a new deployment

    .PARAMETER ExecuteTeardown
        Switch variable that specifies if the framework should clean the deployment
    #>

    param(
        $CurrentTestData,
        $XmlConfig,
        [string]$Distro,
        [string]$LogDir,
        [string]$VMUser,
        [string]$VMPassword,
        [bool]$ExecuteSetup,
        [bool]$ExecuteTeardown
    )

    $currentTestResult = CreateTestResultObject
    $resultArr = @()
    $testParameters = @{}
    $testPlatform = $XmlConfig.config.CurrentTestPlatform
    $testResult = $false
    $timeout = 300

    if ($testPlatform -eq "Azure") {
        $testLocation = $($xmlConfig.config.$TestPlatform.General.Location).Replace('"',"").Replace(' ',"").ToLower()
    } elseif ($testPlatform -eq "HyperV") {
        if($TestLocation){
            $testLocation = $TestLocation
        }else{
            $testLocation = $xmlConfig.config.HyperV.Hosts.ChildNodes[0].ServerName
        }
    }

    if ($ExecuteSetup -or -not $isDeployed) {
        $global:isDeployed = DeployVMS -setupType $CurrentTestData.setupType `
            -Distro $Distro -XMLConfig $XmlConfig -VMGeneration $VMGeneration
        if (!$isDeployed) {
            throw "Could not deploy VMs."
        }
        if(!$IsWindows){
            Enable-RootUser -RootPassword $VMPassword -VMData $AllVMData `
                -Username $VMUser -password $VMPassword
        }
        if ($testPlatform.ToUpper() -eq "HYPERV") {
            Create-HyperVCheckpoint -VMData $AllVMData -CheckpointName "ICAbase"
            $global:AllVMData = Check-IP -VMData $AllVMData
        }
    } else {
        if ($testPlatform.ToUpper() -eq "HYPERV") {
            if ($CurrentTestData.AdditionalHWConfig.HyperVApplyCheckpoint -eq "False") {
                RemoveAllFilesFromHomeDirectory -allDeployedVMs $AllVMData
                LogMsg "Removed all files from home directory."
            } else  {
                Apply-HyperVCheckpoint -VMData $AllVMData -CheckpointName "ICAbase"
                $global:AllVMData = Check-IP -VMData $AllVMData
                LogMsg "Public IP found for all VMs in deployment after checkpoint restore"
            }
        }
    }

    if (!$IsWindows) {
        $null = GetAndCheckKernelLogs -allDeployedVMs $allVMData -status "Initial"
    }

    if ($CurrentTestData.TestParameters) {
        $testParameters = Parse-TestParameters -XMLParams $CurrentTestData.TestParameters `
             -XMLConfig $xmlConfig
    }

    if ($testPlatform -eq "Hyperv" -and $CurrentTestData.SetupScript) {
        if ($null -eq $CurrentTestData.runSetupScriptOnlyOnce) {
            foreach ($VM in $AllVMData) {
                if (Get-VM -Name $VM.RoleName -ComputerName $VM.HyperVHost -EA SilentlyContinue) {
                    Stop-VM -Name $VM.RoleName -TurnOff -Force -ComputerName $VM.HyperVHost
                }
                foreach ($script in $($CurrentTestData.SetupScript).Split(",")) {
                    $null = Run-SetupScript -Script $script -Parameters $testParameters
                }
                if (Get-VM -Name $VM.RoleName -ComputerName $VM.HyperVHost -EA SilentlyContinue) {
                    Start-VM -Name $VM.RoleName -ComputerName $VM.HyperVHost
                }
            }
        }
        else {
            foreach ($script in $($CurrentTestData.SetupScript).Split(",")) {
                $null = Run-SetupScript -Script $script -Parameters $testParameters
            }
        }
    }

    if ($CurrentTestData.files) {
        # This command uploads test dependencies in the home directory for the $vmUsername user
        if(!$IsWindows){
            foreach ($VMData in $AllVMData) {
                RemoteCopy -upload -uploadTo $VMData.PublicIP -Port $VMData.SSHPort `
                    -files $CurrentTestData.files -Username $VMUser -password $VMPassword
                LogMsg "Test files uploaded to VM $($VMData.RoleName)"
            }
        }
    }

    if ($CurrentTestData.Timeout) {
        $timeout = $CurrentTestData.Timeout
    }

    if ($CurrentTestData.TestScript) {
        $testResult = Run-TestScript -Script $CurrentTestData.TestScript `
             -Parameters $testParameters -LogDir $LogDir -VMData $AllVMData `
             -Username $VMUser -password $VMPassword -XMLConfig $XmlConfig `
             -TestName $currentTestData.testName -TestLocation $testLocation `
             -Timeout $timeout
        $resultArr += $testResult
    }

    if ($testPlatform -eq "Hyperv" -and $CurrentTestData.CleanupScript) {
        foreach ($VM in $AllVMData) {
            if (Get-VM -Name $VM.RoleName -ComputerName `
                $VM.HyperVHost -EA SilentlyContinue) {
                Stop-VM -Name $VM.RoleName -TurnOff -Force -ComputerName `
                    $VM.HyperVHost
            }
            foreach ($script in $($CurrentTestData.CleanupScript).Split(",")) {
                $null = Run-SetupScript -Script $script `
                    -Parameters $testParameters
            }
            if (Get-VM -Name $VM.RoleName -ComputerName $VM.HyperVHost `
                -EA SilentlyContinue) {
                Start-VM -Name $VM.RoleName -ComputerName `
                    $VM.HyperVHost
            }
        }
    }

    $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
    LogMsg "VM CLEANUP ~~~~~~~~~~~~~~~~~~~~~~~"
    if ($xmlConfig.config.HyperV.Deployment.($CurrentTestData.setupType).ClusteredVM) {
        foreach ($VM in $AllVMData) {
            Add-VMGroupMember -Name $VM.HyperVGroupName -VM (Get-VM -name $VM.RoleName -ComputerName $VM.HyperVHost) `
                -ComputerName $VM.HyperVHost
        }
    }
    $optionalParams = @{}
    if ($testParameters["SkipVerifyKernelLogs"] -eq "True") {
        $optionalParams["SkipVerifyKernelLogs"] = $True
    }
    DoTestCleanUp -CurrentTestResult $CurrentTestResult -TestName $currentTestData.testName `
    -ResourceGroups $isDeployed @optionalParams -DeleteRG $ExecuteTeardown

    return $currentTestResult
}