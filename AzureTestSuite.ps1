##############################################################################################
# AzureTestSuite.ps1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
	This scripts takes care of launching .\Windows\PowershellScript.ps1 file

.PARAMETER
#	See param lines

.INPUTS
    Copied Base VHD to current storage account
    Cycle through each test scripts
    Start TestScripts
    Start logging in report_test.xml

#>
###############################################################################################

param($xmlConfig, [string] $Distro, [string] $cycleName, [int] $TestIterations)
Function RunTestsOnCycle ($cycleName , $xmlConfig, $Distro, $TestIterations ) {
	LogMsg "Starting the Cycle - $($CycleName.ToUpper())"
	$executionCount = 0

	foreach ( $tempDistro in $xmlConfig.config.$TestPlatform.Deployment.Data.Distro ) {
		if ( ($tempDistro.Name).ToUpper() -eq ($Distro).ToUpper() )	{
			if ( $UseAzureResourceManager )	{
				if ( ($null -ne $tempDistro.ARMImage.Publisher) -and ($null -ne $tempDistro.ARMImage.Offer) -and ($null -ne $tempDistro.ARMImage.Sku) -and ($null -ne $tempDistro.ARMImage.Version)) {
					$ARMImage = $tempDistro.ARMImage
					Set-Variable -Name ARMImage -Value $ARMImage -Scope Global
					LogMsg "ARMImage name - $($ARMImage.Publisher) : $($ARMImage.Offer) : $($ARMImage.Sku) : $($ARMImage.Version)"
				}
				if ( $tempDistro.OsVHD ) {
					$BaseOsVHD = $tempDistro.OsVHD.Trim()
					Set-Variable -Name BaseOsVHD -Value $BaseOsVHD -Scope Global
					LogMsg "Base VHD name - $BaseOsVHD"
				}
			} else {
				if ( $tempDistro.OsImage ) {
					$BaseOsImage = $tempDistro.OsImage.Trim()
					Set-Variable -Name BaseOsImage -Value $BaseOsImage -Scope Global
					LogMsg "Base image name - $BaseOsImage"
				}
			}
		}
	}
	if (!$BaseOsImage  -and !$UseAzureResourceManager) {
		Throw "Please give ImageName or OsVHD for ASM deployment."
	}
	if (!$($ARMImage.Publisher) -and !$BaseOSVHD -and $UseAzureResourceManager) {
		Throw "Please give ARM Image / VHD for ARM deployment."
	}

	#If Base OS VHD is present in another storage account, then copy to test storage account first.
	if ($BaseOsVHD -imatch "/") {
		#Check if the test storage account is same as VHD's original storage account.
		$givenVHDStorageAccount = $BaseOsVHD.Replace("https://","").Replace("http://","").Split(".")[0]
		$ARMStorageAccount = $xmlConfig.config.$TestPlatform.General.ARMStorageAccount

		if ($givenVHDStorageAccount -ne $ARMStorageAccount ) {
			LogMsg "Your test VHD is not in target storage account ($ARMStorageAccount)."
			LogMsg "Your VHD will be copied to $ARMStorageAccount now."
			$sourceContainer =  $BaseOsVHD.Split("/")[$BaseOsVHD.Split("/").Count - 2]
			$vhdName =  $BaseOsVHD.Split("/")[$BaseOsVHD.Split("/").Count - 1]
			if ($ARMStorageAccount -inotmatch "NewStorage_") {
				#Copy the VHD to current storage account.
				$copyStatus = CopyVHDToAnotherStorageAccount -sourceStorageAccount $givenVHDStorageAccount -sourceStorageContainer $sourceContainer -destinationStorageAccount $ARMStorageAccount -destinationStorageContainer "vhds" -vhdName $vhdName
				if (!$copyStatus) {
					Throw "Failed to copy the VHD to $ARMStorageAccount"
				} else {
					Set-Variable -Name BaseOsVHD -Value $vhdName -Scope Global
					LogMsg "New Base VHD name - $vhdName"
				}
			} else {
				Throw "Automation only supports copying VHDs to existing storage account."
			}
		}
	}

	LogMsg "Loading the cycle Data..."

	$currentCycleData = GetCurrentCycleData -xmlConfig $xmlConfig -cycleName $cycleName

	$xmlElementsToAdd = @("currentTest", "stateTimeStamp", "state", "emailSummary", "htmlSummary", "jobID", "testCaseResults")
	foreach($element in $xmlElementsToAdd) {
		if (! $testCycle.${element}) {
			$newElement = $xmlConfig.CreateElement($element)
			$newElement.set_InnerText("")
			$testCycle.AppendChild($newElement)
		}
	}
	$testSuiteLogFile=$LogFile
	$testSuiteResultDetails=@{"totalTc"=0;"totalPassTc"=0;"totalFailTc"=0;"totalAbortedTc"=0}

	# Start JUnit XML report logger.
	$reportFolder = "$pwd/report"
	if(!(Test-Path $reportFolder)) {
		New-Item -ItemType "Directory" $reportFolder
	}

	StartLogReport("$reportFolder/report_$($testCycle.cycleName).xml")
	$testsuite = StartLogTestSuite "CloudTesting"

	if ($testPlatform -eq "Azure") {
		$ExecuteSetupForEachTest = $true
	} elseif ($testPlatform -eq "Hyperv") {
		$ExecuteSetupForEachTest = $false
	}

	$testCount = $currentCycleData.test.Length
	$testIndex = 0
	if (-not $testCount) {
		$testCount = 1
	}

	if ($RunSelectedTests) {
		foreach ($test in $currentCycleData.SelectNodes("test")) {
			if ($RunSelectedTests.Trim().Replace(" ","").Split(",") -notcontains $test.Name) {
				LogMsg "Skipping $($test.Name) because it is not in selected tests to run."
				$test.ParentNode.RemoveChild($test)
			}
		}
	}
	foreach ($test in $currentCycleData.test) {
		$testIndex ++
		$currentTestData = GetCurrentTestData -xmlConfig $xmlConfig -testName $test.Name
		$originalTestName = $currentTestData.testName
		if ( $currentTestData.AdditionalCustomization.Networking -eq "SRIOV" ) {
			Set-Variable -Name EnableAcceleratedNetworking -Value $true -Scope Global
		}

		if ($testIndex -eq 1) {
			$TestState = @{"ExecuteSetup" = $True}
			if ($testCount -eq 1) {
				$TestState += @{"ExecuteTeardown" = $True}
			}
		} elseif ($testIndex -eq $testCount) {
			$TestState = @{"ExecuteTeardown" = $True}
		} else {
			$TestState = @{}
		}
		# Generate Unique Test
		for ( $testIterationCount = 1; $testIterationCount -le $TestIterations; $testIterationCount ++ ) {
			if ( $TestIterations -ne 1 ) {
				$currentTestData.testName = "$($originalTestName)-$testIterationCount"
				$test.Name = "$($originalTestName)-$testIterationCount"
			}
			# For the last test running in economy mode, set the IsLastCaseInCycle flag so that the deployments could be cleaned up
			if ($EconomyMode -and $counter -eq ($testCount - 1)) {
				Set-Variable -Name IsLastCaseInCycle -Value $true -Scope Global
			} else {
				Set-Variable -Name IsLastCaseInCycle -Value $false -Scope Global
			}
			if ($currentTestData) {
				if (!( $currentTestData.Platform.Contains($xmlConfig.config.CurrentTestPlatform))) {
					LogMsg "$($currentTestData.testName) does not support $($xmlConfig.config.CurrentTestPlatform) platform."
					continue;
				}

				if(($testPriority -imatch $currentTestData.Priority ) -or (!$testPriority))	{
					$CurrentTestLogDir = "$LogDir\$($currentTestData.testName)"
					mkdir "$CurrentTestLogDir" -ErrorAction SilentlyContinue | out-null
					Set-Variable -Name CurrentTestLogDir -Value $CurrentTestLogDir -Scope Global
					Set-Variable -Name LogDir -Value $CurrentTestLogDir -Scope Global
					$TestCaseLogFile = "$CurrentTestLogDir\CurrentTestLogs.txt"
					$testcase = StartLogTestCase $testsuite "$($test.Name)" "CloudTesting.$($testCycle.cycleName)"
					$testSuiteResultDetails.totalTc = $testSuiteResultDetails.totalTc +1
					$stopWatch = SetStopWatch

					Set-Variable -Name currentTestData -Value $currentTestData -Scope Global
					try	{
						$testResult = @()
						LogMsg "~~~~~~~~~~~~~~~TEST STARTED : $($currentTestData.testName)~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~"
						LogMsg "Starting multiple tests : $($currentTestData.testName)"
						$CurrentTestResult = Run-Test -CurrentTestData $currentTestData -XmlConfig $xmlConfig `
							-Distro $Distro -LogDir $LogDir -VMUser $user -VMPassword $password `
							-DeployVMPerEachTest $ExecuteSetupForEachTest @TestState
						$testResult = $CurrentTestResult.TestResult
						$testSummary = $CurrentTestResult.TestSummary
					}
					catch {
						$testResult = "ABORTED"
						$ErrorMessage =  $_.Exception.Message
						$line = $_.InvocationInfo.ScriptLineNumber
						LogMsg "EXCEPTION : $ErrorMessage at line: $line"
					}
					finally	{
						try {
							$tempHtmlText = ($testSummary).Substring(0,((($testSummary).Length)-6))
						}
						catch {
							$tempHtmlText = "Unable to parse the results. Will be fixed shortly."
						}
						$executionCount += 1
						$testRunDuration = GetStopWatchElapasedTime $stopWatch "mm"
						$testRunDuration = $testRunDuration.ToString()
						$testCycle.emailSummary += "$($currentTestData.testName) Execution Time: $testRunDuration minutes<br />"
						$testCycle.emailSummary += "	$($currentTestData.testName) : $($testResult)  <br />"
						if ( $testSummary ) {
							$testCycle.emailSummary += "$($testSummary)"
						}
						LogMsg "~~~~~~~~~~~~~~~TEST END : $($currentTestData.testName)~~~~~~~~~~"
						$CurrentTestLogDir = $null
						Set-Variable -Name CurrentTestLogDir -Value $null -Scope Global -Force
					}
					if($testResult -imatch "PASS") {
						$testSuiteResultDetails.totalPassTc = $testSuiteResultDetails.totalPassTc +1
						$testResultRow = "<span style='color:green;font-weight:bolder'>PASS</span>"
						FinishLogTestCase $testcase
						$testCycle.htmlSummary += "<tr><td><font size=`"3`">$executionCount</font></td><td>$tempHtmlText</td><td>$testRunDuration min</td><td>$testResultRow</td></tr>"
					}
					elseif($testResult -imatch "FAIL") {
						$testSuiteResultDetails.totalFailTc = $testSuiteResultDetails.totalFailTc +1
						$caseLog = Get-Content -Raw $TestCaseLogFile
						$testResultRow = "<span style='color:red;font-weight:bolder'>FAIL</span>"
						FinishLogTestCase $testcase "FAIL" "$($test.Name) failed." $caseLog
						$testCycle.htmlSummary += "<tr><td><font size=`"3`">$executionCount</font></td><td>$tempHtmlText$(AddReproVMDetailsToHtmlReport)</td><td>$testRunDuration min</td><td>$testResultRow</td></tr>"
					}
					elseif($testResult -imatch "ABORTED") {
						$testSuiteResultDetails.totalAbortedTc = $testSuiteResultDetails.totalAbortedTc +1
						$caseLog = Get-Content -Raw $TestCaseLogFile
						$testResultRow = "<span style='background-color:yellow;font-weight:bolder'>ABORT</span>"
						FinishLogTestCase $testcase "ERROR" "$($test.Name) is aborted." $caseLog
						$testCycle.htmlSummary += "<tr><td><font size=`"3`">$executionCount</font></td><td>$tempHtmlText$(AddReproVMDetailsToHtmlReport)</td><td>$testRunDuration min</td><td>$testResultRow</td></tr>"
					}
					else {
						LogErr "Test Result is empty."
						$testSuiteResultDetails.totalAbortedTc = $testSuiteResultDetails.totalAbortedTc +1
						$caseLog = Get-Content -Raw $TestCaseLogFile
						$testResultRow = "<span style='background-color:yellow;font-weight:bolder'>ABORT</span>"
						FinishLogTestCase $testcase "ERROR" "$($test.Name) is aborted." $caseLog
						$testCycle.htmlSummary += "<tr><td><font size=`"3`">$executionCount</font></td><td>$tempHtmlText$(AddReproVMDetailsToHtmlReport)</td><td>$testRunDuration min</td><td>$testResultRow</td></tr>"
					}
					LogMsg "CURRENT - PASS    - $($testSuiteResultDetails.totalPassTc)"
					LogMsg "CURRENT - FAIL    - $($testSuiteResultDetails.totalFailTc)"
					LogMsg "CURRENT - ABORTED - $($testSuiteResultDetails.totalAbortedTc)"
					#Back to Test Suite Main Logging
					$global:LogFile = $testSuiteLogFile
					$currentJobs = Get-Job
					foreach ( $job in $currentJobs ) {
						$jobStatus = Get-Job -Id $job.ID
						if ( $jobStatus.State -ne "Running" ) {
							Remove-Job -Id $job.ID -Force
							if ( $? ) {
								LogMsg "Removed $($job.State) background job ID $($job.Id)."
							}
						} else {
							LogMsg "$($job.Name) is running."
						}
					}
					Set-Variable -Name LogDir -Value $RootLogDir -Scope Global
				} else {
					LogMsg "Skipping $($currentTestData.Priority) test : $($currentTestData.testName)"
				}
			} else {
				LogErr "No Test Data found for $($test.Name).."
			}
		}
	}

	LogMsg "Checking background cleanup jobs.."
	$cleanupJobList = Get-Job | Where-Object { $_.Name -imatch "DeleteResourceGroup"}
	$isAllCleaned = $false
	while(!$isAllCleaned) {
		$runningJobsCount = 0
		$isAllCleaned = $true
		$cleanupJobList = Get-Job | Where-Object { $_.Name -imatch "DeleteResourceGroup"}
		foreach ( $cleanupJob in $cleanupJobList ) {

			$jobStatus = Get-Job -Id $cleanupJob.ID
			if ( $jobStatus.State -ne "Running" ) {

				$tempRG = $($cleanupJob.Name).Replace("DeleteResourceGroup-","")
				LogMsg "$tempRG : Delete : $($jobStatus.State)"
				Remove-Job -Id $cleanupJob.ID -Force
			} else  {
				LogMsg "$($cleanupJob.Name) is running."
				$isAllCleaned = $false
				$runningJobsCount += 1
			}
		}
		if ($runningJobsCount -gt 0) {
			Write-Output "$runningJobsCount background cleanup jobs still running. Waiting 30 seconds..."
			Start-Sleep -Seconds 30
		}
	}
	Write-Output "All background cleanup jobs finished."
	$azureContextFiles = Get-Item "$env:TEMP\*.azurecontext"
	$azureContextFiles | Remove-Item -Force | Out-Null
	LogMsg "Removed $($azureContextFiles.Count) context files."
	LogMsg "Cycle Finished.. $($CycleName.ToUpper())"

	FinishLogTestSuite($testsuite)
	FinishLogReport

	$testSuiteResultDetails
}

RunTestsOnCycle -cycleName $cycleName -xmlConfig $xmlConfig -Distro $Distro -TestIterations $TestIterations
