$DBNull = [System.DBNull]::Value
Function AddClusterEnvDetailsinDB ($conn, $clusterObj,$testSuiteRunId) 
{
	$query = "INSERT INTO ClusterEnvDetails VALUES ('$testSuiteRunId','$($clusterObj.cluster)','$($clusterObj.rdos)','$($clusterObj.fabric)','$($clusterObj.location)')"
	ExecuteSqlStatement -sqlconn $conn -sqlQuery $query
}

Function AddServerEnvDetailsinDB ($conn, $serverObj,$testSuiteRunId) 
{
	$query = "INSERT INTO ServerEnvDetails VALUES ('$testSuiteRunId','$($serverObj.serverName)','$($serverObj.serverRam)','$($serverObj.serverCpu)','$($serverObj.serverBuild)')"
	ExecuteSqlStatement -sqlconn $conn -sqlQuery $query
}

Function AddTestResultinDB ($conn, $testResultObj) 
{
	$query = "INSERT INTO TestResult VALUES ('$($testResultObj.testRunId)','$($testResultObj.testName)','$($testResultObj.testResult)','$($testResultObj.testLogLocation)')"
	ExecuteSqlStatement -sqlconn $conn -sqlQuery $query
}

Function AddIozoneResultsinDB ($conn, $iozoneObj,$testCaseObj,$testSuiteRunId) 
{
	#$query = "INSERT INTO DiskTest VALUES ('$($iozoneObj.testRunId)','$($iozoneObj.fileSize)','$($iozoneObj.recordSize)','$($iozoneObj.write)','$($iozoneObj.rewrite)','$($iozoneObj.read)','$($iozoneObj.reread)','$($iozoneObj.randomread)','$($iozoneObj.randomwrite)','$($iozoneObj.bkwdread)','$($iozoneObj.recordrewrite)','$($iozoneObj.strideread)')"
	$query = "INSERT INTO DiskTest VALUES ('$testSuiteRunId','$($testCaseObj.testCaseId)','$($testCaseObj.startTime)','$($iozoneObj.diskDetails)','$($iozoneObj.storageType)','$($iozoneObj.fileSize)','$($iozoneObj.recordSize)','$($iozoneObj.write)','$($iozoneObj.rewrite)','$($iozoneObj.read)','$($iozoneObj.reread)','$($iozoneObj.randomread)','$($iozoneObj.randomwrite)','$($iozoneObj.bkwdread)','$($iozoneObj.recordrewrite)','$($iozoneObj.strideread)')"
	ExecuteSqlStatement -sqlConn $conn -sqlQuery $query
}

Function AddIPerfResultsinDB ($conn, $bandwidth,$testCaseObj,$testSuiteRunId) 
{
	#$query = "INSERT INTO DiskTest VALUES ('$($iozoneObj.testRunId)','$($iozoneObj.fileSize)','$($iozoneObj.recordSize)','$($iozoneObj.write)','$($iozoneObj.rewrite)','$($iozoneObj.read)','$($iozoneObj.reread)','$($iozoneObj.randomread)','$($iozoneObj.randomwrite)','$($iozoneObj.bkwdread)','$($iozoneObj.recordrewrite)','$($iozoneObj.strideread)')"
	$query = "INSERT INTO NetworkTest VALUES ('$testSuiteRunId','$($testCaseObj.testCaseId)','$($testCaseObj.startTime)','tcp','$bandwidth','$bandwidth','$bandwidth','$bandwidth','$bandwidth','$bandwidth')"
	ExecuteSqlStatement -sqlConn $conn -sqlQuery $query
}

Function AddTestSuiteDetailsinDB ($conn, $testSuiteObj)
{
	#$query="INSERT INTO TestRunDetails VALUES ('$($testSuiteObj.testSuiteRunId)','$($testSuiteObj.runDate)','$($testSuiteObj.server)','$($testSuiteObj.linuxDistro)','$($testSuiteObj.perfTool)','$($testSuiteObj.lisBuild)','$($testSuiteObj.waagentBuild)','$($testSuiteObj.testName)','$($testSuiteObj.vmRam)','$($testSuiteObj.vmVcpu)','$($testSuiteObj.testRunDuration)','$($testSuiteObj.lisBuildBranch)','$($testSuiteObj.comments)')"
	$query="INSERT INTO TestSuiteRunDetails VALUES ('$($testSuiteObj.testSuiteRunId)','$($testSuiteObj.testSuiteName)','$($testSuiteObj.server)','$($testSuiteObj.linuxDistro)','$($testSuiteObj.startTime)','$($testSuiteObj.endTime)','$($testSuiteObj.comments)')"
	ExecuteSqlStatement -sqlConn $conn -sqlQuery $query
}

Function AddTestCaseDetailsinDB($conn, $testCaseObj,$testSuiteRunId)
{
	#$query="INSERT INTO TestRunDetails VALUES ('$($testCaseObj.testRunId)','$($testCaseObj.runDate)','$($testCaseObj.server)','$($testCaseObj.linuxDistro)','$($testCaseObj.perfTool)','$($testCaseObj.lisBuild)','$($testCaseObj.waagentBuild)','$($testCaseObj.testName)','$($testCaseObj.vmRam)','$($testCaseObj.vmVcpu)','$($testCaseObj.testRunDuration)','$($testCaseObj.lisBuildBranch)','$($testCaseObj.comments)')"
	$query="INSERT INTO TestCaseRunDetails VALUES ('$testSuiteRunId','$($testCaseObj.testCaseId)','$($testCaseObj.testName)','$($testCaseObj.testDescp)','$($testCaseObj.testCategory)','$($testCaseObj.result)','$($testCaseObj.perfTool)','$($testCaseObj.startTime)','$($testCaseObj.endTime)','$($testCaseObj.deploymentId)','$($testCaseObj.vmRam)','$($testCaseObj.vmVcpu)','$($testCaseObj.comments)')"
	ExecuteSqlStatement -sqlConn $conn -sqlQuery $query
}

Function AddSubTestResultinDB($conn,$subTestCaseObj,$testSuiteRunId)
{
	$query="INSERT INTO SubTestCaserunDetails VALUES ('$testSuiteRunId','$($subTestCaseObj.testCaseId)','$($subTestCaseObj.testName)','$($subTestCaseObj.result)','$($subTestCaseObj.startTime)','$($subTestCaseObj.SubtestStartTime)','$($subTestCaseObj.SubtestEndtime)','$($subTestCaseObj.endTime)','$($subTestCaseObj.comments)')"
	Write-host "$query"
    ExecuteSqlStatement -sqlConn $conn -sqlQuery $query
}

Function AddVmEnvDetailsinDB ($conn, $vmEnvObj,$testSuiteRunId)
{
	$query="INSERT INTO VMEnvDetails VALUES ('$testSuiteRunId','$($vmEnvObj.lisBuildBranch)','$($vmEnvObj.lisBuild)','$($vmEnvObj.kernelVersion)','$($vmEnvObj.waagentBuild)','$($vmEnvObj.vmImageDetails)')"
	ExecuteSqlStatement -sqlConn $conn -sqlQuery $query
}

Function UpdateTestSuiteEndTime($conn, $testSuiteObj)
{
  $query="UPDATE [LISPerfTestDB].[dbo].[TestSuiteRunDetails] SET EndTime = '$($testSuiteObj.endTime)' WHERE TestSuiteRunId='$($testSuiteObj.testSuiteRunId)' and StartTime='$($testSuiteObj.startTime)';"
  ExecuteSqlStatement -sqlConn $conn -sqlQuery $query
}

Function UpdateTestCaseStartTime($conn, $testCaseObj,$testSuiteRunId)
{
  $query="UPDATE [LISPerfTestDB].[dbo].[TestCaseRunDetails] SET StartTime = '$($testCaseObj.startTime)' WHERE TestSuiteRunId='$($testCaseObj.testSuiteRunId)';"
  ExecuteSqlStatement -sqlConn $conn -sqlQuery $query
}

Function UpdateTestCaseResultAndEndtime($conn, $testCaseObj)
{
  $query="UPDATE [LISPerfTestDB].[dbo].[TestCaseRunDetails] SET Result = '$($testCaseObj.Result)' WHERE TestSuiteRunId='$($testCaseObj.testSuiteRunId)' and TestCaseID='$($testCaseObj.testCaseId)';UPDATE [LISPerfTestDB].[dbo].[TestCaseRunDetails] SET EndTime = '$($testCaseObj.endtime)' WHERE TestSuiteRunId='$($testCaseObj.testSuiteRunId)' and TestCaseID='$($testCaseObj.testCaseId)';"
  Write-Host "$query"
  ExecuteSqlStatement -sqlConn $conn -sqlQuery $query
}

Function CreateVMEnvObject
{
	param
	(
	[string] $lisBuildBranch,
	[string] $lisBuild,
	[string] $kernelVersion,
	[string] $waagentBuild,
	[string] $vmImageDetails
	)
	
	$objNode = New-Object -TypeName PSObject
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name lisBuildBranch -Value $lisBuildBranch -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name lisBuild -Value $lisBuild -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name kernelVersion -Value $kernelVersion -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name waagentBuild -Value $waagentBuild -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name vmImageDetails -Value $vmImageDetails -Force
	return $objNode
}

Function CreateTestSuiteObject
{
	param(
	[string] $testSuiteRunId,
	[string] $testSuiteName,
	[string] $server,
	[string] $linuxDistro,
	[string] $startTime,
	[string] $endTime,
	[string] $comments
	)
	$objNode = New-Object -TypeName PSObject
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name testSuiteRunId -Value $testSuiteRunId -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name testSuiteName -Value $testSuiteName -Force 
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name server -Value $server -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name linuxDistro -Value $linuxDistro -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name startTime -Value $startTime -Force 
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name endTime -Value $endTime -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name comments -Value $comments -Force
	return $objNode
}

Function CreateTestCaseObject 
{
	param(
	[string] $testSuiteRunId,
	[string] $testCaseId,	
	[string] $testName,
	[string] $testDescp,
	[string] $testCategory,
	[string] $result,
	[string] $perfTool,
	[string] $startTime,
	[string] $endTime,
	[string] $deploymentId,
	[string] $vmRam,
	[string] $vmVcpu,
	[string] $comments
	)
	$objNode = New-Object -TypeName PSObject
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name testSuiteRunId -Value $testSuiteRunId -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name testCaseId -Value $testCaseId -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name testName -Value $testName -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name testDescp -Value $testDescp -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name testCategory -Value $testCategory -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name result -Value $result -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name perfTool -Value $perfTool -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name startTime -Value $startTime -Force 
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name endTime -Value $endTime -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name deploymentId -Value $deploymentId -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name vmRam -Value $vmRam -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name vmVcpu -Value $vmVcpu -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name comments -Value $comments -Force
	
	return $objNode
}

Function CreateSubTestCaseObject
{
	param(
	[string] $testSuiteRunId,
	[string] $testCaseId,	
	[string] $testName,
	[string] $result,
	[string] $startTime,
	[string] $endTime,
	[string] $SubtestStartTime,
	[string] $SubtestEndTime,
	[string] $comments
	)
	$objNode = New-Object -TypeName PSObject
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name testSuiteRunId -Value $testSuiteRunId -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name testCaseId -Value $testCaseId -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name testName -Value $testName -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name result -Value $result -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name startTime -Value $startTime -Force 
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name endTime -Value $endTime -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name SubteststartTime -Value $SubteststartTime -Force 
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name SubtestendTime -Value $SubtestendTime -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name comments -Value $comments -Force
	return $objNode
}

Function CreateTestRunObject 
{
	param(
	[string] $testSuiteRunId,
	[string] $runDate,
	[string] $server,
	[string] $testName,
	[string] $testDescp,
	[string] $testCategory,
	[string] $testId,
	[string] $linuxDistro,
	[string] $perfTool,
	[string] $testRunDuration,
	[string] $lisBuildBranch,
	[string] $comments
	)
	$objNode = New-Object -TypeName PSObject
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name testRunId -Value $testSuiteRunId -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name runDate -Value $runDate -Force 
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name server -Value $server -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name testName -Value $testName -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name testDescp -Value $testDescp -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name testCategory -Value $testCategory -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name testId -Value $testId -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name linuxDistro -Value $linuxDistro -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name perfTool -Value $perfTool -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name testRunDuration -Value $testRunDuration -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name comments -Value $comments -Force
	
	return $objNode
}

Function CreateIozoneNode
{
	param(
	[Parameter(Mandatory=$true)] [string] $recordSize,
	[Parameter(Mandatory=$true)] [string] $fileSize,
	[Parameter(Mandatory=$true)] [string] $logDir,
	[Parameter(Mandatory=$true)] [string] $storageType
	)

	$objNode = New-Object -TypeName PSObject
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name diskDetails -Value null -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name storageType -Value $storageType -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name recordSize -Value $recordSize -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name fileSize -Value $fileSize -Force 
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name logDir -Value $LogDir -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name write -Value null -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name rewrite -Value null -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name read -Value null -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name reread -Value null -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name randomread -Value null -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name randomwrite -Value null -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name bkwdread -Value null -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name recordrewrite -Value null -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name strideread -Value null -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name ip -Value $nodeIp -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name sshPort -Value $nodeSshPort -Force 
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name tcpPort -Value $nodeTcpPort -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name user -Value $user -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name password -Value $password -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name files -Value $files -Force
	return $objNode
}

Function CreateTestResultObject
{
	param(
	[string] $testSuiteRunId,
	[string] $testName,
	[string] $testResult,
	[string] $testLogLocation
	)
	$objNode = New-Object -TypeName PSObject
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name testRunId -Value $testSuiteRunId -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name testName -Value $testName -Force 
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name testResult -Value $testResult -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name testloglocation -Value $testLoglocation -Force
	return $objNode
	
}

Function CreateIperfResultObj
{
	param(
	[string] $serverBandwidth,
	[string] $clientBandwidth
	)
	$objNode = New-Object -TypeName PSObject
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name protocol -Value protocol -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name serverBandwidth -Value $serverBandwidth -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name clientBandwidth -Value $clientBandwidth -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name jitter -Value $jitter -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name packetLoss -Value $packetLoss -Force
	return $objNode
}

Function CreateClusterEnvObject
{
	param(
	[string] $cluster,
	[string] $rdos,
	[string] $fabric,
	[string] $location
	)
	$objNode = New-Object -TypeName PSObject
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name cluster -Value $cluster -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name rdos -Value $rdos -Force 
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name fabric -Value $fabric -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name location -Value $location -Force
	return $objNode
	
}

Function CreateServerEnvObject
{
	param(
	[string] $serverName,
	[string] $serverRam,
	[string] $serverCpu,
	[string] $serverBuild
	)
	$objNode = New-Object -TypeName PSObject
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name serverName -Value $serverName -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name serverRam -Value $serverRam -Force 
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name serverCpu -Value $serverCpu -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name serverBuild -Value $serverBuild -Force
	return $objNode
}

Function GenerateTestSuiteRunID ($conn) 
{
	$idObj=GetSqlQueryResult -sqlConn $conn -sqlQuery "SELECT MAX(TestSuiteRunID) AS RunId FROM TestSuiteRunDetails" -scaler
	#$idObj=ExecuteAccessSQLStatement $conn "SELECT MAX(TestRunID) AS RunId FROM TestRunDetails"
	if (!($idObj -eq $DBNull))
	{
		$id=$idObj + 1
	}
	else 
	{
		$id=1
	}
	return $id
}