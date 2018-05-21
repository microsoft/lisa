#Import Libraries.
Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global }

$allReports = Get-ChildItem .\report | Where-Object {($_.FullName).EndsWith("-junit.xml") -and ($_.FullName -imatch "\d\d\d\d\d\d")}
$retValue = 0
foreach ( $report in $allReports )
{
    LogMsg "Analysing $($report.FullName).."
    $resultXML = [xml](Get-Content "$($report.FullName)" -ErrorAction SilentlyContinue)
    if ( ( $resultXML.testsuites.testsuite.failures -eq 0 ) -and ( $resultXML.testsuites.testsuite.errors -eq 0 ) -and ( $resultXML.testsuites.testsuite.tests -gt 0 ))
    {
    }
    else
    {
        $retValue = 1
    }
    foreach ($testcase in $resultXML.testsuites.testsuite.testcase)
    {
        if ($testcase.failure)
        {
            LogMsg "$($testcase.name) : FAIL"
        }
        else 
        {
            LogMsg "$($testcase.name) : PASS"
        }
    }    
    LogMsg "----------------------------------------------"
}
LogMsg "Exiting with Code : $retValue"
exit $retValue