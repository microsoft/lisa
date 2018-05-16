Import-Module .\TestLibs\RDFELibstemp.psm1 -Force


$iperfclient = "D:\v-shisav\Automation\Development Branch\TestResults\Azure_ICA-20130221-083212\NETWORK-IE-UDP-SINGLE-HS-DIFF-DATAGRAM\1000\iperf-client.txt"
$iperfserver = "D:\v-shisav\Automation\Development Branch\TestResults\Azure_ICA-20130221-083212\NETWORK-IE-UDP-SINGLE-HS-DIFF-DATAGRAM\1000\iperf-server.txt"

#Write-Host $iperfclient
AnalyseIperfServerConnectivity -logfile $iperfserver -beg "TestStarted" -end "TestCompleted"
#GetParallelConnectionCount -logFile $iperfclient -beg "TestStarted" -end "TestCompleted"

#GetStringMatchObject -beg "" -end "" -logFile $iperfclient -str "teststarted"
#I COULDN'T GET, WHAT SHOULD BE THE "ptrn"?