##############################################################################################
# parser.ps1
# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for full license information.
# Description : Parsing moduels for test log access.
# Operations :
#              
## Author : lisasupport@microsoft.com
###############################################################################################
Import-Module .\AzureWinUtils.psm1 -Force

Function GetStringMatchCount([string] $logFile,[string] $beg,[string] $end, [string] $str){
$match=GetStringMatchObject -logFile $logFile -beg $beg -end $end -str $str
return $match.Count
}

Function GetTotalDataTransfer([string] $logFile,[string] $beg,[string] $end){
$dataTransfer=GetDataTxed -logFile $logFile -ptrn "\d*[bits,KBytes]/sec$" 
return $dataTransfer
}

Function GetTotalUdpServerTransfer([string] $logFile,[string] $beg,[string] $end){
$dataTransfer=GetDataTxed -logFile $logFile -ptrn "[bits,bytes]/sec"
return $dataTransfer
}

Function GetCustomProbeMsgsCount([string] $logFile,[string] $beg,[string] $end) {
$match=GetStringMatchObject -logFile $logFile -beg $beg -end $end -str "0.00 KBytes  0.00 KBytes/sec"
return $match.Count
}

Function IsCustomProbeMsgsPresent ([string] $logFile,[string] $beg,[string] $end) {
$cpStr="0.00 KBytes  0.00 KBytes/sec"
$match=IsContainString -logFile $logFile -beg $beg -end $end -str $cpStr
return $match
}

Function GetUdpLoss([string] $logFile, [string] $beg,[string] $end) {
$match=GetStringMatchObject -logFile $logFile -beg $beg -end $end -str "\([\d,\d.\d]*%\)$"
Write-Host $match
$arr = @()
foreach ($item in $match) {
$item = $item.ToString()
$str2=@($item.Split(" ",[StringSplitOptions]'RemoveEmptyEntries'))
foreach ($a in $str2) {
	if($a.Contains("%"))
		{
		 $i=$str2.IndexOf($a)
		 $a=$str2[$i]
		 $b=$a.Split("%")
		 $num=$b[0].Split("(")
		 $arr += $num
		 }
}
$sum = ($arr | Measure-Object -Sum).Sum
}
Write-Host $sum
return $sum
}

Function GetDataTxed([string] $logFile,[string] $beg,[string] $end, [string] $ptrn) {
$match=GetStringMatchObject -logFile $logFile -beg $beg -end $end -str $ptrn
$match= $match | Select-String -Pattern "0.00 KBytes/sec" -NotMatch
$lastItem=$match.Item($match.Length-1)
$lastItem=$lastItem.ToString()
Write-Host $lastItem
$str1=@($lastItem.Split(']'))
$str2=@($lastItem.Split(" ",[StringSplitOptions]'RemoveEmptyEntries'))
Write-Host $str2
foreach ($a in $str2) {
	if($a.Contains("Bytes") -and !($a.Contains("Bytes/sec")))
		{
		$i=$str2.IndexOf($a)
		 $result=$str2[$i-1]+$str2[$i]
		}
}
return $result
}

Function AnalyseIperfServerConnectivity([string] $logFile,[string] $beg,[string] $end) {
$connectStr="\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\sport\s\d*\sconnected with \d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\sport\s\d"
$match=IsContainString -logFile $logFile -beg $beg -end $end -str $connectStr
$failure = 0
If($match) {
	LogMsg "Server connected!"
	return $true
} else {
	LogMsg "Server connection Fails!"
	return $false
}
}

Function AnalyseIperfClientConnectivity([string] $logFile,[string] $beg,[string] $end) {
$connectStr="\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\sport\s\d*\sconnected with \d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\sport\s\d"
$match=IsContainString -logFile $logFile -beg $beg -end $end -str $connectStr
$failure = 0
If($match) {
	Write-Host "Success"
	$match = IsContainString -logFile $logFile -beg $beg -end $end -str "failed"
	If($match) {
		$failure = $failure + 1
		LogMsg "Client connected with some failed connections!"
	}	
	$match = IsContainString -logFile $logFile -beg $beg -end $end -str "error"	
	If($match) {
		$failure = $failure + 1
		LogMsg "There were some errors in the connections!"
	}
	$match = IsContainString -logFile $logFile -beg $beg -end $end -str "refused"	
	If($match) {
		$failure = $failure + 1
		LogMsg "Some connections were refused!" 
	}
	if ($failure -eq 0) {
		LogMsg "Client was successfully connected to server"
		return $true
	} else {
		LogMsg "Client connection fails"
		return $false
	}
} else {
	$match = IsContainString -logFile $logFile -beg $beg -end $end -str "No address associated"	
	If($match) {
		LogMsg "Client was not connected to server!"
		LogMsg "No address associated with hostname"
		return $false
	} 
	elseif (($match= IsContainString -logFile $logFile -beg $beg -end $end -str "Connection refused")) {
		LogMsg "Client was not connected to server."
		LogMsg "Connection refused by the server."
		return $false
	}
	elseif (($match= IsContainString -logFile $logFile -beg $beg -end $end -str "Name or service not known")) {
		LogMsg "Client was not connected to server."
		LogMsg "Name or service not known."
		return $false
	} else {
		LogMsg "Client was not connected to server."
		LogMsg "Unlisted error. Check logs for more information...!."
		return $false
	}
}
}

Function IsContainString([string] $logFile,[string] $beg,[string] $end, [string] $str) {
$match=GetStringMatchObject -logFile $logFile -beg $beg -end $end -str $str
If ($match.count -gt 0) {
	return $true
} else {
	return $false
}
}

Function GetStringMatchObject([string] $logFile,[string] $beg,[string] $end, [string] $str) {
if ($beg -eq "0") {
	$begPos = 1
	$match=Select-String -Pattern $end -Path $logFile
	$endPos= $match.LineNumber
	$lineArr = ($begPos-1)..($endPos-1)
	$match=Get-Content -Path $logFile | Select-Object -Index $lineArr | Select-String -Pattern $str
} elseif ($beg -ne ""  -and $end -ne "") {
	$match=Select-String -Pattern $beg -Path $logFile
	$begPos= $match.LineNumber
	$match=Select-String -Pattern $end -Path $logFile
	$endPos= $match.LineNumber
	$lineArr = ($begPos-1)..($endPos-1)
	$match=Get-Content -Path $logFile | Select-Object -Index $lineArr | Select-String -Pattern $str
} else {
	$match=Select-String -Pattern $str -Path $logFile
}
#Write-Host $match
return $match
}

Function GetParallelConnectionCount([string] $logFile,[string] $beg,[string] $end){
$connectStr="\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\sport\s\d*\sconnected with \d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\sport\s\d"
$p=GetStringMatchCount -logFile $logFile -beg $beg -end $end -str $connectStr
return $p
}

Function GetMSSSize([string] $logFile,[string] $beg,[string] $end){
$match=GetStringMatchObject -logFile $logFile -beg $beg -end $end -str "MSS size \d*\sbytes"
If ($match.Length -gt 1) {
$lastItem=$match.Item($match.Length-1) 
} else {
$lastItem=$match
}
$lastItem=$lastItem.ToString()
#$str1=@($lastItem.Split(']'))
$str2=@($lastItem.Split(" ",[StringSplitOptions]'RemoveEmptyEntries'))
foreach ($a in $str2) {
	if($a.Contains("size"))
		{
		 $i=$str2.IndexOf($a)
		 $result=$str2[$i+1]+$str2[$i+2]
		}
}
return $result
}

Function GetParallelConnectionsCount($iperfClientoutput){
$iperfClientOutput = $iperfClientOutput.Split("")
$uniqueIds = @()
$AllConnectedIDs = @()
$NoofUniqueIds = 0
foreach ($word in $iperfClientOutput)
    {
    if ($word -imatch "]")
        {
        $word = $word.Replace("]","")
        $word = $word.Replace("[","")
        $word = $word -as [int]
        if ($word)
        {
            $AllConnectedIDs += $word
            $NotUnique = 0
            foreach ($id in $uniqueIds)
                {
                if ($word -eq $id)
                    {
                    $NotUnique = $NotUnique + 1
                    }
                }
            if ($NotUnique -eq 0)
                {
                $uniqueIds += $word
                }
            }
        
        }
    }
    $NoofUniqueIds = $uniqueIds.Count
    #return $AllConnectedIDs, $uniqueIds, $NoofUniqueIds
    return $NoofUniqueIds
}

#GetStringMatchObject -logFile ".\bookmark.txt" -beg "BookMark1" -end "BookMark3" -str "MSS size \d"
#GetStringMatchCount -logFile ".\bookmark.txt" -beg "BookMark1" -end "BookMark2" -str "connected"
GetTotalDataTransfer -logFile ".\cp.txt" 
#GetMSSSize -logFile ".\bookmark.txt" -beg "BookMark2" -end "BookMark3"
#GetUdpLoss -logFile ".\udpclient.txt"
#GetTotalUdpServerTransfer -logFile "iperf-server.txt"
#GetParallelConnectionCount -logFile ".\bookmark.txt" -beg "BookMark1" -end "BookMark2"
#AnalyseIperfServerConnectivity ".\bookmark.txt"
#IsCustomProbeMsgsPresent ".\cp.txt"