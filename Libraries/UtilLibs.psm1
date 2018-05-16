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