#LogMsg ()
# Operation : Prints the messages, warnings, errors
# Parameter : message string
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
    $str += "<br />Logs can be found at \\${hostname}\TestResults\" + $xmlFilename + "-" + $StartTime.ToString("yyyyMMdd-HHmmss") + "<br /><br />"
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

####################################################
#SystemStart ()
# Operation : Starts the VHD provisioning Virtual Machine 
# Parameter : Name of the Virtual Machine
######################################################
function SystemStart ($VmObject)
{
    $vmname=$VmObject.vmName
    $hvServer=$VmObject.hvServer    
    LogMsg "VM $vmname is Starting"
    $startVMLog = Start-VM  -Name $vmname -ComputerName $hvServer 3>&1 2>&1
    $isVmStarted = $?
    if($isVmStarted)
    {
        if ($startVMLog -imatch "The virtual machine is already in the specified state.")
        {
            LogMsg "$startVMLog"
        }
        else
        {
            LogMsg "VM started Successfully"
            $VMState=GetVMState $vmname $hvServer
            LogMsg "Current Status : $VMState"
            WaitFor -seconds 10
        }
    }
    else
    {
        LogErr "$startVMLog"
        Throw "Failed to start VM."
    }
}

####################################################
#SystemStop ()
# Operation : Stops the VHD provisioning Virtual Machine
# Parameter : Name of the Virtual Machine
######################################################
function SystemStop ($VmObject)
{
    $vm = $VmObject
    $vmname=$vm.vmName
    $hvServer=$vm.hvServer
    $VMIP=$vm.ipv4
    $passwd=$vm.Password
    LogMsg "Shutting down the VM $vmname.."
    $VMState=GetVMState -VmObject $vm
    if(!($VMState -eq "Off"))
    {
        LogMsg "Issuing shutdown command.."
        $out = echo y|.\bin\plink -pw $passwd root@"$VMIP" "init 0" 3>&1 2>&1
        $isCommandSent = $?
        if(!$isCommandSent)
        {
            LogMsg "Failed to sent shutdown command .. Stopping forcibly."
            ForceShutDownVM -VmObject $vm
        }
        else
        {
            LogMsg "Shutdown command sent."
            WaitFor -seconds 15
            $counter = 1
            $retryAttemts = 10
            $VMState=GetVMState -VmObject $vm
            if($VMState -eq "Off")
            {
                $isSuccess=$true
            }
            while(($counter -le $retryAttemts) -and ($VMState -ne "Off"))
            {
                $isSuccess=$false
                Write-Host "Current Status : $VMState. Retrying $counter/$retryAttemts.."
                WaitFor -seconds 10
                $VMState=GetVMState -VmObject $vm
                if($VMState -eq "Off")
                {
                    $isSuccess=$true
                    break
                }
                $counter += 1
            }
            if ($isSuccess)
            {
                LogMsg "VM stopped successfully."
            }
            else 
            {
                Throw "VM failed to stop."
            }
        }
    }
    else
    {
    LogMsg "VM is already off."
    }
}

function ForceShutDownVM($VmObject)
{
    $vmname=$VmObject.vmName
    $hvServer=$VmObject.hvServer
    LogMsg "Force Shutdown VM : $vmname"
    $VMstopLog = stop-VM  -Name $vmname -ComputerName $hvServer -force 3>&1 2>&1
    $counter = 1
    $retryAttemts = 10
    $VMState=GetVMState -VmObject $vm
    while(($counter -le $retryAttemts) -and ($VMState -ne "Off"))
    {
        $isSuccess=$false
        Write-Host "Current Status : $VMState. Retrying $counter/$retryAttemts.."
        WaitFor -seconds 10
        $VMstopLog = stop-VM  -Name $vmname -ComputerName $hvServer -force 3>&1 2>&1
        $VMState=GetVMState -VmObject $vm
        if($VMState -eq "Off")
        {
            $isSuccess=$true
            break
        }
        $counter += 1
    }

    LogMsg "VM `'$vmname`' is $VMState"
}



#################################################
#GetVMState ()
#Function : Determinig the VM state
#Parameter : VM Name
#Return Value : state of the VM {"Running", "Stopped", "Paused", "Suspended", "Starting","Taking Snapshot", "Saving, "Stopping"}
########################################################

function GetVMState ($VmObject)
{
    $vmname=$vm.vmName
    $hvServer=$vm.hvServer
    $VMIP=$vm.ipv4
    $passwd=$vm.Password
    try
    {
    $VMstatus = Get-VM -Name $vmname -ComputerName $hvServer 3>&1 2>&1
    }
    Catch
    {
    LogErr "Exception Message : $VMstatus"
    Throw "Failed to Get the VM status."
    }
    return $VMstatus.state
}

###############################################################
#TestPort ()
# Function : Checking port 22 of the VM
# parameter : IP address
##############################################################

function TestPort ([string] $IP)
{
    
    $out = .\bin\vmmftest -server $IP -port 22 -timeout=3 3>&1 2>&1 
    if ($out -imatch "$IP is alive")
    {
        $isConnected=$true
    }
    else
    {
        $isConnected=$false
    }
    return $isConnected
}

Function csuploadSetConnetion ([string] $subscription)
{
    if ($subscription -eq $null -or $subscription.Length -eq 0)
    {
        "Error: Subscription is null"
        return $False
    }
    .\tools\CsUpload\csupload.exe Set-Connection $subscription

    if($?)
    {
	    LogMsg "Csupload connection set successfully.."
        return $true
    }
    else
    {
	    LogErr "Error in setting up Csupload connection.."
        return $False
    }

}

function UploadVHD ($xmlConfig)
{
    #CSUpload Parameters
    $SubscriptionID=$xmlConfig.config.Azure.CSUpload.Subscription
    $DestinationURL=$xmlConfig.config.Azure.CSUpload.DestinationURL
    $VHDpath=$xmlConfig.config.Azure.CSUpload.VHDpath
    $VHDname = $xmlConfig.config.Azure.CSUpload.VHDName

    #Set Connection of CSUpload to upload a VHD to cloud

    LogMsg "Connecting to Azure cloud to upload test VHD : $VHDName"
    #LogMsg ".\SetupScripts\csuploadSetConnection.ps1 $SubscriptionID"

    $isConnectinSet= csuploadSetConnetion $SubscriptionID
    if($isConnectinSet)
    {
        #Uploading the test VHD to cloud
        
        LogMsg "Uplaoding the test VHD $VHDName to Azure cloud..."
        $curtime = Get-Date
        $ImageName = "ICA-UPLOADED-" + $Distro + "-" + $curtime.Month + "-" +  $curtime.Day  + "-" + $curtime.Year + "-" + $curtime.Hour + "-" + $curtime.Minute + ".vhd"
        $ImageDestination =  $DestinationURL + "/" + $ImageName
        $ImageLabel = $ImageName
        $ImageLiteralPath =  $VHDpath + "\" + "$VHDName"

        LogMsg "Image Name using        : $ImageName"
        LogMsg "Image Label using       : $ImageLabel"
        LogMsg "Destination place using : $ImageDestination"
        LogMsg "Literal path using      : $ImageLiteralPath"

        $uploadLogs = .\tools\CsUpload\csupload.exe Add-DurableImage -Destination $ImageDestination -Name $ImageName -Label $ImageLabel -LiteralPath $ImageLiteralPath -OS Linux 3>&1 2>&1
        if($uploadLogs -imatch  "is registered successfully")
        {
            LogMsg "VHD uploaded successfully."
            LogMsg "Publishing the image name.."
            SetOSImageToDistro -Distro $Distro -xmlConfig $xmlConfig -ImageName "`"$ImageName`""
            return $true
        }
        else
        {
            LogErr "Failed to upload VHD. Please find the parameters used below."
            LogErr "Image Name used        : $ImageName"
            LogErr "Image Label used       : $ImageLabel"
            LogErr "Destination place used : $ImageDestination"
            LogErr "Literal path used      : $ImageLiteralPath"
            Throw "Failed to upload vhd."
        }
    }
    else
    {
        Throw "Failed to set connection fo csupload."
    }
}

function VHDProvision ($xmlConfig, $uploadflag)
{
	if (!$onCloud)
	{
	    #VM Parameters
	    $vm=$xmlConfig.config.VMs.vm
	    $testVM=$vm.vmName
	    $VMIP=$vm.ipv4
	    $passwd=$vm.Password
	    $VHDName=$xmlConfig.config.Azure.CSUpload.VHDName
	    $hvServer=$vm.hvServer
	    $Platform=$xmlConfig.config.global.platform

	    #LIS Tarball
	    $LISTarball=$xmlConfig.config.VMs.vm.LIS_TARBALL
	  
	    
	    #Start the VM..
	    SystemStart -VmObject $vm

	    #Checking avaialability of port 22

	    CheckSSHConnection -VMIpAddress $VMIP
	    Write-Host "Done"
	    #.\SetupScripts\VHDProvision.ps1 $testVM $VMIP $passwd $LISTarball
	    $isAllPackagesInstalled = InstallPackages -VMSshPort 22 -VMUserName "root" -VMPassword "redhat" -VMIpAddress $VMIP

	        # Collect VHD provision logs
	        #
	    if ($isAllPackagesInstalled)
	    {
	       
	        LogMsg "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~"
	        LogMsg "TestVHD {$VHDName} is provisioned for automation"
	        LogMsg "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~"
	        
	    }
	    else
	    {
	        LogMsg "Error:Failed to pull VHD Provision logfile"
	        return $false
	        
	    }
	    
	    # Stop the VM after VHD preparation
	   
	    SystemStop -VmObject $vm

	    if ($uploadflag)
	    {
	       UploadVHD $xmlConfig
	       if(!$?) 
	       {
	           return $false
	       }
	    }
	   

	}
	else
	{
	    #VHD preparation on clod part here--

	    #Deploy one VM on cloud..
	    $isDeployed = DeployVMs -xmlConfig $xmlConfig -setupType LargeVM -Distro $Distro
	    #$isDeployed =  "ICA-LargeVM-testdistro-7-16-1-41-23"
	    #$isDeployed = $true
	    if ($isDeployed)
	    {   
	           
	            $testServiceData = Get-AzureService -ServiceName $isDeployed

	            #Get VMs deployed in the service..
	            $testVMsinService = $testServiceData | Get-AzureVM

	            $hs1vm1 = $testVMsinService
	            $hs1vm1Endpoints = $hs1vm1 | Get-AzureEndpoint
	            $hs1vm1sshport = GetPort -Endpoints $hs1vm1Endpoints -usage ssh
	            $hs1VIP = $hs1vm1Endpoints[0].Vip
	            $hs1ServiceUrl = $hs1vm1.DNSName
	            $hs1ServiceUrl = $hs1ServiceUrl.Replace("http://","")
	            $hs1ServiceUrl = $hs1ServiceUrl.Replace("/","")
	            $hs1vm1Hostname =  $hs1vm1.Name
	   
	            

	        $isAllPackagesInstalled = InstallPackages -VMIpAddress $hs1VIP -VMSshPort $hs1vm1sshport -VMUserName $user -VMPassword $password
	                                  

	        $capturedImage = CaptureVMImage -ServiceName $isDeployed
	        #$capturedImage = "ICA-CAPTURED-testDistro-7-5-2013-4-37.vhd"
	        LogMsg "Publishing the image name.."
	        SetOSImageToDistro -Distro $Distro -xmlConfig $xmlConfig -ImageName "`"$capturedImage`""
	            

	        Write-Host $xmlConfig
	    }
	    else
	    {
	        $retValue = $false
	        Throw "Deployment Failed."
	    }

	    #InstallPackages run on cloud.

	    #deprovision VM..

	    #Capture Image with generated Name..
	  
	}
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

Function CSUploadSetSubscription([string] $subscription)
{
	if ($subscription -eq $null -or $subscription.Length -eq 0)
	{
	    "Error: Subscription is null"
	    return $False
	}
	.\tools\CsUpload\csupload Set-Connection $subscription

	if($?)
	{
		"Csupload connection set successfully.."
	}
	else
	{
		"Error in setting up Csupload connection.."
		Break;
	}
}

Function ImportAzureSDK()
{
	$module = get-module | select-string -pattern azure -quiet
	if (! $module)
	{
		import-module .\tools\AzureSDK\Azure.psd1
	}
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

Function CheckSSHConnection($VMIpAddress)
{
    $retryCount = 1
    $maxRetryCount = 100
    $isConnected= TestPort -IP $VMIpAddress
    if($isConnected)
    {
        $isSuccess = $true
    }
    while (($retryCount -le $maxRetryCount) -and (!$isConnected))
    {
        $isSuccess = $False
        LogMsg "Connecting to ssh network of VM $VMIpAddress. Retry $retryCount/$maxRetryCount.."
        $isConnected= TestPort -IP $VMIpAddress
        if($isConnected)
        {
            $isSuccess = $true
            break
        }
        $retryCount += 1
        WaitFor -seconds 5
    }
    if($isSuccess)
    {
        LogMsg "Connected to $VMIpAddress."
    }
    else
    {
        Throw "Connection failed to $VMIpAddress."
    }
    
}

Function RunAzureCmd ($AzureCmdlet, $maxWaitTimeSeconds = 600, [string]$storageaccount = "")
{
    $timeExceeded = $false
    LogMsg "$AzureCmdlet"
    $jobStartTime = Get-Date 
    $CertThumbprint = $xmlConfig.config.Azure.General.CertificateThumbprint
    try
    {
        $myCert = Get-Item Cert:\CurrentUser\My\$CertThumbprint
    }
    catch
    {
        $myCert = Get-Item Cert:\LocalMachine\My\$CertThumbprint
    }
    if(!$storageaccount)
    {
      $storageaccount = $xmlConfig.config.Azure.General.StorageAccount
    }
    if (IsEnvironmentSupported)
    {
        $environment = $xmlConfig.config.Azure.General.Environment
        $AzureJob = Start-Job -ScriptBlock { $PublicConfiguration = $args[6];$PrivateConfiguration = $args[7];$suppressedOut = Set-AzureSubscription -SubscriptionName $args[1] -Certificate $args[2] -SubscriptionID $args[3] -ServiceEndpoint $args[4] -CurrentStorageAccountName $args[5] -Environment $args[8];$suppressedOut = Select-AzureSubscription -Current $args[1];Invoke-Expression $args[0];} -ArgumentList $AzureCmdlet, $xmlConfig.config.Azure.General.SubscriptionName, $myCert, $xmlConfig.config.Azure.General.SubscriptionID, $xmlConfig.config.Azure.General.ManagementEndpoint, $storageaccount, $PublicConfiguration, $PrivateConfiguration, $environment
    }
    else
    {
        $AzureJob = Start-Job -ScriptBlock { $PublicConfiguration = $args[6];$PrivateConfiguration = $args[7];$suppressedOut = Set-AzureSubscription -SubscriptionName $args[1] -Certificate $args[2] -SubscriptionID $args[3] -ServiceEndpoint $args[4] -CurrentStorageAccountName $args[5];$suppressedOut = Select-AzureSubscription -Current $args[1];Invoke-Expression $args[0];} -ArgumentList $AzureCmdlet, $xmlConfig.config.Azure.General.SubscriptionName, $myCert, $xmlConfig.config.Azure.General.SubscriptionID, $xmlConfig.config.Azure.General.ManagementEndpoint, $storageaccount, $PublicConfiguration, $PrivateConfiguration
    }
    $currentTime = Get-Date
    while (($AzureJob.State -eq "Running") -and !$timeExceeded)
        {
        $currentTime = Get-Date        
        $timeLapsed = (($currentTime - $jobStartTime).TotalSeconds) 
        Write-Progress -Activity $AzureCmdlet -Status $AzureJob.State -PercentComplete (($timeLapsed / $maxWaitTimeSeconds)*100) -Id 142536 -SecondsRemaining ( $maxWaitTimeSeconds - $timeLapsed )
        Write-Host "." -NoNewline
        sleep -Seconds 1
        if ($timeLapsed -gt $maxWaitTimeSeconds)
            {
                $timeExceeded = $true
            }
        }
    Write-Progress -Id 142536 -Activity $AzureCmdlet -Completed
    LogMsg "Time Lapsed : $timeLapsed Seconds."
    $AzureJobOutput = Receive-Job $AzureJob
    $operationCounter = 0
    $operationSuccessCounter = 0
    $operationFailureCounter = 0
    if ($AzureJobOutput -eq $null)
    {
        $operationCounter += 1
    }
    else
    {
        foreach ($operation in $AzureJobOutput)
        {
            $operationCounter += 1 
            if ($operation.OperationStatus -eq "Succeeded")
            {
                $operationSuccessCounter += 1
            }
            else
            {
                $operationFailureCounter += 1
            }
        }
    }
    if($operationCounter -eq $operationSuccessCounter)
    {
        return $AzureJobOutput
    }
    else
    {
        if($timeExceeded)
        {
            LogErr "Azure Cmdlet : Timeout"
        } 
        Throw "Failed to execute Azure command."
    }
}