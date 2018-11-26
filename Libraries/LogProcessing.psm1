##############################################################################################
# LogProcessing.psm1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
	PS modules for LISAv2 test automation
	This module handles logging, test summary, and test reports.

.PARAMETER
	<Parameters>

.INPUTS


.NOTES
	Creation Date:
	Purpose/Change:

.EXAMPLE


#>
###############################################################################################

Function Write-Log()
{
	param
	(
		[ValidateSet('INFO','WARN','ERROR', IgnoreCase = $false)]
		[string]$logLevel,
		[string]$text
	)

	if ($password) {
		$text = $text.Replace($password,"******")
	}
	$now = [Datetime]::Now.ToUniversalTime().ToString("MM/dd/yyyy HH:mm:ss")
	$logType = $logLevel.PadRight(5, ' ')
	$finalMessage = "$now : [$logType] $text"
	$fgColor = "White"
	switch ($logLevel)
	{
		"INFO"	{$fgColor = "White"; continue}
		"WARN"	{$fgColor = "Yellow"; continue}
		"ERROR"	{$fgColor = "Red"; continue}
	}
	Write-Host $finalMessage -ForegroundColor $fgColor

	try
	{
		if ($LogDir) {
			if (!(Test-Path $LogDir)) {
				New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
			}
		} else {
			$LogDir = $env:TEMP
		}

		$LogFileFullPath = Join-Path $LogDir $LogFileName
		if (!(Test-Path $LogFileFullPath)) {
			New-Item -path $LogDir -name $LogFileName -type "file" | Out-Null
		}
		Add-Content -Value $finalMessage -Path $LogFileFullPath -Force
	}
	catch
	{
		Write-Output "[LOG FILE EXCEPTION] : $now : $text"
	}
}

Function LogMsg($text)
{
	Write-Log "INFO" $text
}

Function LogErr($text)
{
	Write-Log "ERROR" $text
}

Function LogError($text)
{
	Write-Log "ERROR" $text
}

Function LogWarn($text)
{
	Write-Log "WARN" $text
}

Function CreateResultSummary($testResult, $checkValues, $testName, $metaData)
{
	if ( $metaData )
	{
		$resultString = "	$metaData : $testResult <br />"
	}
	else
	{
		$resultString = "	$testResult <br />"
	}
	return $resultString
}

Function GetFinalResultHeader($resultArr){
	if(($resultArr -imatch "FAIL" ) -or ($resultArr -imatch "Aborted"))
	{
		$result = "FAIL"
		if($resultArr -imatch "Aborted")
		{
			$result = "Aborted"
		}
	}
	else
	{
		$result = "PASS"
	}
	return $result
}

<#
JUnit XML Report Schema:
	http://windyroad.com.au/dl/Open%20Source/JUnit.xsd
Example:
	$junitReport = [JUnitReportGenerator]::New($TestReportXml)
	$junitReport.StartLogTestSuite("LISAv2")

	$junitReport.StartLogTestCase("LISAv2", "BVT", "LISAv2.BVT")
	$junitReport.CompleteLogTestCase("LISAv2", "BVT", "PASS")

	$junitReport.StartLogTestCase("LISAv2", "NETWORK", "LISAv2.NETWORK")
	$junitReport.CompleteLogTestCase("LISAv2","NETWORK", "FAIL", "Stack trace: XXX")

	$junitReport.CompleteLogTestSuite("LISAv2")

	$junitReport.StartLogTestSuite("FCTesting")

	$junitReport.StartLogTestCase("FCTesting", "BVT", "FCTesting.BVT")
	$junitReport.CompleteLogTestCase("FCTesting", "BVT", "PASS")

	$junitReport.StartLogTestCase("FCTesting", "NEGATIVE", "FCTesting.NEGATIVE")
	$junitReport.CompleteLogTestCase("FCTesting", "NEGATIVE", "FAIL", "Stack trace: XXX")

	$junitReport.CompleteLogTestSuite("FCTesting")

	$junitReport.SaveLogReport()

report.xml:
	<testsuites>
	  <testsuite name="LISAv2" timestamp="2014-07-11T06:37:24" tests="3" failures="1" errors="1" time="0.04">
		<testcase name="BVT" classname="LISAv2.BVT" time="0" />
		<testcase name="NETWORK" classname="LISAv2.NETWORK" time="0">
		  <failure message="NETWORK fail">Stack trace: XXX</failure>
		</testcase>
		<testcase name="VNET" classname="LISAv2.VNET" time="0">
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

Class ReportNode
{
	[System.Xml.XmlElement] $XmlNode
	[System.Diagnostics.Stopwatch] $Timer

	ReportNode([object] $XmlNode)
	{
		$this.XmlNode = $XmlNode
		$this.Timer = [System.Diagnostics.Stopwatch]::startNew()
	}

	[string] StopTimer()
	{
		if ($null -eq $this.Timer)
		{
			return ""
		}
		$this.Timer.Stop()
		return [System.Math]::Round($this.Timer.Elapsed.TotalSeconds, 2).ToString()
	}

	[string] GetTimerElapasedTime([string] $Format="mm")
	{
		$num = 0
		if ($Format -eq "ss")
		{
			$num=$this.Timer.Elapsed.TotalSeconds
		}
		elseif ($Format -eq "hh")
		{
			$num=$this.Timer.Elapsed.TotalHours
		}
		elseif ($Format -eq "mm")
		{
			$num=$this.Timer.Elapsed.TotalMinutes
		}
		else
		{
			LogError "Invalid format for GetTimerElapasedTime: $Format"
		}
		return [System.Math]::Round($num, 2).ToString()
	}
}

Class JUnitReportGenerator
{
	[string] $JunitReportPath
	[Xml] $JunitReport
	[System.Xml.XmlElement] $ReportRootNode
	[object] $TestSuiteLogTable
	[object] $TestSuiteCaseLogTable

	JUnitReportGenerator([string]$ReportPath)
	{
		$this.JunitReportPath = $ReportPath
		$this.JunitReport = New-Object System.Xml.XmlDocument
		$newElement = $this.JunitReport.CreateElement("testsuites")
		$this.ReportRootNode = $this.JunitReport.AppendChild($newElement)
		$this.TestSuiteLogTable = @{}
		$this.TestSuiteCaseLogTable = @{}
	}

	[void] SaveLogReport()
	{
		if ($null -ne $this.JunitReport) {
			$this.JunitReport.Save($this.JunitReportPath)
		}
	}

	[void] StartLogTestSuite([string]$testsuiteName)
	{
		if($null -eq $this.JunitReport -or $null -eq $testsuiteName -or $null -ne $this.TestSuiteLogTable[$testsuiteName])
		{
			return
		}

		$newElement = $this.JunitReport.CreateElement("testsuite")
		$newElement.SetAttribute("name", $testsuiteName)
		$newElement.SetAttribute("timestamp", [Datetime]::Now.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss"))
		$newElement.SetAttribute("tests", 0)
		$newElement.SetAttribute("failures", 0)
		$newElement.SetAttribute("errors", 0)
		$newElement.SetAttribute("time", 0)
		$testsuiteNode = $this.ReportRootNode.AppendChild($newElement)

		$testsuite = [ReportNode]::New($testsuiteNode)

		$this.TestSuiteLogTable[$testsuiteName] = $testsuite
	}

	[void] CompleteLogTestSuite([string]$testsuiteName)
	{
		if($null -eq $this.TestSuiteLogTable[$testsuiteName])
		{
			return
		}

		$this.TestSuiteLogTable[$testsuiteName].XmlNode.Attributes["time"].Value = $this.TestSuiteLogTable[$testsuiteName].StopTimer()
		$this.SaveLogReport()
		$this.TestSuiteLogTable[$testsuiteName] = $null
	}

	[void] StartLogTestCase([string]$testsuiteName, [string]$caseName, [string]$className)
	{
		if($null -eq $this.JunitReport -or $null -eq $testsuiteName -or $null -eq $this.TestSuiteLogTable[$testsuiteName] `
			-or $null -eq $caseName -or $null -ne $this.TestSuiteCaseLogTable["$testsuiteName$caseName"])
		{
			return
		}

		$newElement = $this.JunitReport.CreateElement("testcase")
		$newElement.SetAttribute("name", $caseName)
		$newElement.SetAttribute("classname", $classname)
		$newElement.SetAttribute("time", 0)

		$testcaseNode = $this.TestSuiteLogTable[$testsuiteName].XmlNode.AppendChild($newElement)

		$testcase = [ReportNode]::New($testcaseNode)
		$this.TestSuiteCaseLogTable["$testsuiteName$caseName"] = $testcase
	}

	[void] CompleteLogTestCase([string]$testsuiteName, [string]$caseName, [string]$result="PASS", [string]$detail="")
	{
		if($null -eq $this.JunitReport -or $null -eq $testsuiteName -or $null -eq $this.TestSuiteLogTable[$testsuiteName] `
			-or $null -eq $caseName -or $null -eq $this.TestSuiteCaseLogTable["$testsuiteName$caseName"])
		{
			return
		}
		$testCaseNode = $this.TestSuiteCaseLogTable["$testsuiteName$caseName"].XmlNode
		$testCaseNode.Attributes["time"].Value = $this.TestSuiteCaseLogTable["$testsuiteName$caseName"].StopTimer()

		$testSuiteNode = $this.TestSuiteLogTable[$testsuiteName].XmlNode
		[int]$testSuiteNode.Attributes["tests"].Value += 1
		if ($result -imatch "FAIL")
		{
			$newChildElement = $this.JunitReport.CreateElement("failure")
			$newChildElement.InnerText = $detail
			$newChildElement.SetAttribute("message", "$caseName failed.")
			$testCaseNode.AppendChild($newChildElement)

			[int]$testSuiteNode.Attributes["failures"].Value += 1
		}

		if ($result -imatch "ABORTED")
		{
			$newChildElement = $this.JunitReport.CreateElement("error")
			$newChildElement.InnerText = $detail
			$newChildElement.SetAttribute("message", "$caseName aborted.")
			$testCaseNode.AppendChild($newChildElement)

			[int]$testSuiteNode.Attributes["errors"].Value += 1
		}
		$this.SaveLogReport()
		$this.TestSuiteCaseLogTable["$testsuiteName$caseName"] = $null
	}

	[string] GetTestCaseElapsedTime([string]$TestSuiteName, [string]$CaseName, [string]$Format = "mm")
	{
		if($null -eq $this.JunitReport -or $null -eq $testsuiteName -or $null -eq $this.TestSuiteLogTable[$testsuiteName] `
			-or $null -eq $caseName -or $null -eq $this.TestSuiteCaseLogTable["$testsuiteName$caseName"])
		{
			LogErr "Failed to get the elapsed time of test case $CaseName."
			return ""
		}
		return $this.TestSuiteCaseLogTable["$testsuiteName$caseName"].GetTimerElapasedTime($Format)
	}

	[string] GetTestSuiteElapsedTime([string]$TestSuiteName, [string]$Format = "mm")
	{
		if($null -eq $this.JunitReport -or $null -eq $testsuiteName -or $null -eq $this.TestSuiteLogTable[$testsuiteName])
		{
			LogErr "Failed to get the elapsed time of test suite $TestSuiteName."
			return ""
		}
		return $this.TestSuiteLogTable[$testsuiteName].GetTimerElapasedTime($Format)
	}
}

Function GetTestSummary($testCycle, [DateTime] $StartTime, [string] $xmlFilename, [string] $distro, $testSuiteResultDetails)
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

Function Add-ReproVMDetailsToHtmlReport()
{
	$reproVMHtmlText += "<br><font size=`"2`"><em>Repro VMs: </em></font>"

	foreach ( $vm in $allVMData )
	{
		$reproVMHtmlText += "<br><font size=`"2`">ResourceGroup : $($vm.ResourceGroupName), IP : $($vm.PublicIP), SSH : $($vm.SSHPort)</font>"
	}
	return $reproVMHtmlText
}

Function Update-TestSummaryForCase ([string]$TestName, [int]$ExecutionCount, [string]$TestResult, [object]$TestCycle, [object]$ResultDetails, [string]$Duration, [string]$TestSummary, [bool]$AddHeader)
{
	if ( $AddHeader ) {
		$TestCycle.emailSummary += "{0,5} {1,-50} {2,20} {3,20} <br />" -f "ID", "TestCaseName", "TestResult", "TestDuration(in minutes)"
		$TestCycle.emailSummary += "------------------------------------------------------------------------------------------------------<br />"
	}
	$TestCycle.emailSummary += "{0,5} {1,-50} {2,20} {3,20} <br />" -f "$ExecutionCount", "$TestName", "$TestResult", "$Duration"
	if ( $TestSummary ) {
		$TestCycle.emailSummary += "$TestSummary"
	}

	$ResultDetails.totalTc += 1
	if ( $TestResult -imatch "PASS" ) {
		$ResultDetails.totalPassTc += 1
		$testResultRow = "<span style='color:green;font-weight:bolder'>PASS</span>"
		$TestCycle.htmlSummary += "<tr><td><font size=`"3`">$ExecutionCount</font></td><td>$TestName</td><td>$Duration min</td><td>$testResultRow</td></tr>"
	}
	elseif ( $TestResult -imatch "FAIL" ) {
		$ResultDetails.totalFailTc += 1
		$testResultRow = "<span style='color:red;font-weight:bolder'>FAIL</span>"
		$TestCycle.htmlSummary += "<tr><td><font size=`"3`">$ExecutionCount</font></td><td>$TestName$(Add-ReproVMDetailsToHtmlReport)</td><td>$Duration min</td><td>$testResultRow</td></tr>"
	}
	elseif ( $TestResult -imatch "ABORTED" ) {
		$ResultDetails.totalAbortedTc += 1
		$testResultRow = "<span style='background-color:yellow;font-weight:bolder'>ABORT</span>"
		$TestCycle.htmlSummary += "<tr><td><font size=`"3`">$ExecutionCount</font></td><td>$TestName$(Add-ReproVMDetailsToHtmlReport)</td><td>$Duration min</td><td>$testResultRow</td></tr>"
	}
	else {
		LogErr "Test Result is empty."
		$ResultDetails.totalAbortedTc += 1
		$testResultRow = "<span style='background-color:yellow;font-weight:bolder'>ABORT</span>"
		$TestCycle.htmlSummary += "<tr><td><font size=`"3`">$ExecutionCount</font></td><td>$TestName$(Add-ReproVMDetailsToHtmlReport)</td><td>$Duration min</td><td>$testResultRow</td></tr>"
	}

	LogMsg "CURRENT - PASS    - $($ResultDetails.totalPassTc)"
	LogMsg "CURRENT - FAIL    - $($ResultDetails.totalFailTc)"
	LogMsg "CURRENT - ABORTED - $($ResultDetails.totalAbortedTc)"
}