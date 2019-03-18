##############################################################################################
# TestReport.psm1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
	PS modules for LISAv2 test automation
	This module handles Junit report, HTML summary and text summary.

.PARAMETER
	<Parameters>

.INPUTS


.NOTES
	Creation Date:
	Purpose/Change:

.EXAMPLE


#>
###############################################################################################

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
			Write-LogErr "Invalid format for Get-TimerElapasedTime: $Format"
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
		$newElement.SetAttribute("skipped", 0)
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
		if ($result -imatch "FAIL") {
			$newChildElement = $this.JunitReport.CreateElement("failure")
			$newChildElement.InnerText = $detail
			$newChildElement.SetAttribute("message", "$caseName failed.")
			$testCaseNode.AppendChild($newChildElement)

			[int]$testSuiteNode.Attributes["failures"].Value += 1
		} elseif ($result -imatch "ABORTED") {
			$newChildElement = $this.JunitReport.CreateElement("error")
			$newChildElement.InnerText = $detail
			$newChildElement.SetAttribute("message", "$caseName aborted.")
			$testCaseNode.AppendChild($newChildElement)

			[int]$testSuiteNode.Attributes["errors"].Value += 1
		} elseif ($result -imatch "SKIPPED") {
			$newChildElement = $this.JunitReport.CreateElement("skipped")
			$testCaseNode.AppendChild($newChildElement)
			[int]$testSuiteNode.Attributes["skipped"].Value += 1
		}

		$this.SaveLogReport()
		$this.TestSuiteCaseLogTable["$testsuiteName$caseName"] = $null
	}

	[string] GetTestCaseElapsedTime([string]$TestSuiteName, [string]$CaseName, [string]$Format = "mm")
	{
		if($null -eq $this.JunitReport -or $null -eq $testsuiteName -or $null -eq $this.TestSuiteLogTable[$testsuiteName] `
			-or $null -eq $caseName -or $null -eq $this.TestSuiteCaseLogTable["$testsuiteName$caseName"])
		{
			Write-LogErr "Failed to get the elapsed time of test case $CaseName."
			return ""
		}
		return $this.TestSuiteCaseLogTable["$testsuiteName$caseName"].GetTimerElapasedTime($Format)
	}

	[string] GetTestSuiteElapsedTime([string]$TestSuiteName, [string]$Format = "mm")
	{
		if($null -eq $this.JunitReport -or $null -eq $testsuiteName -or $null -eq $this.TestSuiteLogTable[$testsuiteName])
		{
			Write-LogErr "Failed to get the elapsed time of test suite $TestSuiteName."
			return ""
		}
		return $this.TestSuiteLogTable[$testsuiteName].GetTimerElapasedTime($Format)
	}
}

Class TestSummary
{
	[string] $TextSummary
	[string] $HtmlSummary
	[bool] $AddHeader
	[int] $TotalTc
	[int] $TotalPassTc
	[int] $TotalFailTc
	[int] $TotalAbortedTc
	[int] $TotalSkippedTc
	[DateTime] $TestStartTime
	[string] $TestCategory
	[string] $TestArea
	[string] $TestName
	[string] $TestTag
	[string] $TestPriority

	TestSummary($TestCategory, $TestArea, $TestName, $TestTag, $TestPriority, $TotalCaseNum) {
		$this.TextSummary = ""
		$this.HtmlSummary = ""
		$this.AddHeader = $true
		$this.TotalPassTc = 0
		$this.TotalFailTc = 0
		$this.TotalAbortedTc = 0
		$this.TotalSkippedTc = 0
		$this.TotalTc = $TotalCaseNum
		$this.TestStartTime = [DateTime]::Now.ToUniversalTime()
		$this.TestCategory = $TestCategory
		$this.TestArea = $TestArea
		$this.TestName = $TestName
		$this.TestTag = $TestTag
		$this.TestPriority = $TestPriority
	}

	[string] GetPlainTextSummary ()
	{
		$testDuration= [Datetime]::Now.ToUniversalTime() - $this.TestStartTime
		$durationStr=$testDuration.Days.ToString() + ":" +  $testDuration.hours.ToString() + ":" + $testDuration.minutes.ToString()
		$str = "`r`n[LISAv2 Test Results Summary]`r`n"
		$str += "Test Run On           : " + $this.TestStartTime
		if ( $global:BaseOSVHD ) {
			$str += "`r`nVHD Under Test        : " + $global:BaseOSVHD
		}
		if ( $global:ARMImageName ) {
			$imageInfo = $global:ARMImageName.Split(' ')
			$str += "`r`nARM Image Under Test  : " + "$($imageInfo[0]) : $($imageInfo[1]) : $($imageInfo[2]) : $($imageInfo[3])"
		}
		if ($this.TestCategory) {
			$str += "`r`nTest Category         : $($this.TestCategory)"
		}
		if ($this.TestArea) {
			$str += "`r`nTest Area             : $($this.TestArea)"
		}
		if ($this.TestTag) {
			$str += "`r`nTest Tag              : $($this.TestTag)"
		}
		if ($this.TestPriority) {
			$str += "`r`nTest Priority         : $($this.TestPriority)"
		}
		$str += "`r`nTotal Test Cases      : " + $this.TotalTc + " (" + $this.TotalPassTc + " Passed, " + `
			$this.TotalFailTc + " Failed, " + $this.TotalAbortedTc + " Aborted, " + $this.TotalSkippedTc + " Skipped)"
		$str += "`r`nTotal Time (dd:hh:mm) : $durationStr`r`n`r`n"

		$str += $this.TextSummary.Replace("<br />", "`r`n")
		$str += "`r`n`r`nLogs can be found at $global:LogDir" + "`r`n`r`n"

		return $str
	}

	[void] SaveHtmlTestSummary ($FilePath) {
		$testDuration= [Datetime]::Now.ToUniversalTime() - $this.TestStartTime
		$durationStr=$testDuration.Days.ToString() + ":" +  $testDuration.hours.ToString() + ":" + $testDuration.minutes.ToString()
		$strHtml =  "<STYLE>" +
			"BODY, TABLE, TD, TH, P {" +
			"  font-family:Verdana,Helvetica,sans serif;" +
			"  font-size:11px;" +
			"  color:black;" +
			"}" +
			"TD.bg1 { color:black; background-color:#99CCFF; font-size:180% }" +
			"TD.bg2 { color:black; font-size:130% }" +
			"TD.bg3 { color:black; font-size:110% }" +
			".TFtable{width:1024px; border-collapse:collapse; }" +
			".TFtable td{ padding:7px; border:#4e95f4 1px solid;}" +
			".TFtable tr{ background: #b8d1f3;}" +
			".TFtable tr:nth-child(odd){ background: #dbe1e9;}" +
			".TFtable tr:nth-child(even){background: #ffffff;}" +
			"</STYLE>" +
			"<table>" +
			"<TR><TD class=`"bg1`" colspan=`"2`"><B>Test Complete</B></TD></TR>" +
			"</table>" +
			"<BR/>"
		$strHtml += "<table><TR><TD class=`"bg2`" colspan=`"2`"><B>LISAv2  test run on - $($this.TestStartTime)</B></TD></TR>"
		if (${env:BUILD_URL}) {
			$strHtml += "<TR><TD class=`"bg3`" colspan=`"2`">Build URL: <A href=`"${env:BUILD_URL}`">${env:BUILD_URL}</A></TD></TR>"
		}
		if ( $global:BaseOSVHD ) {
			$strHtml += "<TR><TD class=`"bg3`" colspan=`"2`">VHD under test - $global:BaseOSVHD</TD></TR>"
		}
		if ( $global:ARMImageName ) {
			$imageInfo = $global:ARMImageName.Split(' ')
			$strHtml += "<TR><TD class=`"bg3`" colspan=`"2`">ARM Image under test - $($imageInfo[0]) : $($imageInfo[1]) : $($imageInfo[2]) : $($imageInfo[3])</TD></TR>"
		}
		if ($this.TestCategory) {
			$strHtml += "<TR><TD class=`"bg3`" colspan=`"2`">Test Category - $($this.TestCategory)</TD></TR>"
		}
		if ($this.TestArea) {
			$strHtml += "<TR><TD class=`"bg3`" colspan=`"2`">Test Area - $($this.TestArea)</TD></TR>"
		}
		if ($this.TestTag) {
			$strHtml += "<TR><TD class=`"bg3`" colspan=`"2`">Test Tag - $($this.TestTag)</TD></TR>"
		}
		if ($this.TestPriority) {
			$strHtml += "<TR><TD class=`"bg3`" colspan=`"2`">Test Priority - $($this.TestPriority)</TD></TR>"
		}
		$strHtml += "</table><BR/>"
		$strHtml += "<table>"
		$strHtml += "<TR><TD class=`"bg3`" colspan=`"2`">Total Executed TestCases - $($this.TotalTc)</TD></TR>"
		$strHtml += "<TR><TD class=`"bg3`" colspan=`"2`">[&nbsp;" + `
			"<span> <span style=`"color:#008000;`"><strong>$($this.TotalPassTc)</strong></span></span> - $($global:ResultPass), " + `
			"<span> <span style=`"color:#cccccc;`"><strong>$($this.TotalSkippedTc)</strong></span></span> - $($global:ResultSkipped), " + `
			"<span> <span style=`"color:#ff0000;`"><strong>$($this.TotalFailTc)</strong></span></span> - $($global:ResultFail), " + `
			"<span> <span style=`"color:#ff0000;`"><strong><span style=`"background-color:#ffff00;`">$($this.TotalAbortedTc)</span></strong></span></span> - $($global:ResultAborted) " + `
			"]</TD></TR>"
		$strHtml += "<TR><TD class=`"bg3`" colspan=`"2`">Total Execution Time(dd:hh:mm) $durationStr</TD></TR>"
		$strHtml += "</table>"
		$strHtml += "<BR/>"

		# Add information about the detailed case result
		$strHtml += "<table border='0' class='TFtable'>"
		$strHtml += $this.HtmlSummary
		$strHtml += "</table></body></Html>"

		# Note(v-advlad): the check is required for unit tests to pass
		if (Test-Path (Split-Path $FilePath)) {
			Set-Content -Value $strHtml -Path $FilePath -Force | Out-Null
		} else {
			Write-LogWarn "$FilePath directory does not exist."
		}
	}

	[void] UpdateTestSummaryForCase([object]$TestData, [int]$ExecutionCount, [string]$TestResult, [string]$Duration, [string]$TestSummary, [object]$AllVMData)
	{
		if ( $this.AddHeader ) {
			$this.TextSummary += "{0,5} {1, -20} {2,-65} {3,20} {4,20} `r`n" -f "ID", "TestArea", "TestCaseName", "TestResult", "TestDuration(in minutes)"
			$this.TextSummary += "-------------------------------------------------------------------------------------------------------------------------------------------`r`n"
			$this.AddHeader = $false
		}
		$this.TextSummary += "{0,5} {1, -20} {2,-65} {3,20} {4,20} `r`n" -f "$ExecutionCount", "$($TestData.Area)", "$($TestData.testName)", "$TestResult", "$Duration"
		if ( $TestSummary ) {
			$this.TextSummary += "$TestSummary"
		}

		$testSummaryLinePassSkip = "<tr><td>$ExecutionCount</td><td>$($TestData.Area)</td><td>$($TestData.testName)</td><td>$Duration min</td><td>" + '{0}' + "</td></tr>"
		$testSummaryLineFailAbort = "<tr><td>$ExecutionCount</td><td>$($TestData.Area)</td><td>$($TestData.testName)$($this.GetReproVMDetails($AllVMData))</td><td>$Duration min</td><td>" + '{0}' + "</td></tr>"
		if ($TestResult -imatch $global:ResultPass) {
			$this.TotalPassTc += 1
			$testResultRow = "<span style='color:green;font-weight:bolder'>$($global:ResultPass)</span>"
			$this.HtmlSummary += $testSummaryLinePassSkip -f @($testResultRow)
		} elseif ($TestResult -imatch $global:ResultSkipped) {
			$this.TotalSkippedTc += 1
			$testResultRow = "<span style='background-color:gray;font-weight:bolder'>$($global:ResultSkipped)</span>"
			$this.HtmlSummary += $testSummaryLinePassSkip -f @($testResultRow)
		} elseif ($TestResult -imatch $global:ResultFail) {
			$this.TotalFailTc += 1
			$testResultRow = "<span style='color:red;font-weight:bolder'>$($global:ResultFail)</span>"
			$this.HtmlSummary += $testSummaryLineFailAbort -f @($testResultRow)
		} elseif ($TestResult -imatch $global:ResultAborted) {
			$this.TotalAbortedTc += 1
			$testResultRow = "<span style='background-color:yellow;font-weight:bolder'>$($global:ResultAborted)</span>"
			$this.HtmlSummary += $testSummaryLineFailAbort -f @($testResultRow)
		} else {
			Write-LogErr "Test Result is empty."
			$this.TotalAbortedTc += 1
			$testResultRow = "<span style='background-color:yellow;font-weight:bolder'>$($global:ResultAborted)</span>"
			$this.HtmlSummary += $testSummaryLineFailAbort -f @($testResultRow)
		}

		Write-LogInfo "CURRENT - $($global:ResultPass)    - $($this.TotalPassTc)"
		Write-LogInfo "CURRENT - $($global:ResultSkipped) - $($this.TotalSkippedTc)"
		Write-LogInfo "CURRENT - $($global:ResultFail)    - $($this.TotalFailTc)"
		Write-LogInfo "CURRENT - $($global:ResultAborted) - $($this.TotalAbortedTc)"
	}

	[string] GetReproVMDetails($allVMData) {
		if ($allVMData) {
			$reproVMHtmlText += "<br><font size=`"2`"><em>Repro VMs: </em></font>"

			foreach ( $vm in $allVMData )
			{
				$reproVMHtmlText += "<br><font size=`"2`">ResourceGroup : $($vm.ResourceGroupName), IP : $($vm.PublicIP), SSH : $($vm.SSHPort)</font>"
			}
			return $reproVMHtmlText
		}
		return ""
	}
}
