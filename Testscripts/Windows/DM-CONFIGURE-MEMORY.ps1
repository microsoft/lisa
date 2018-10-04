# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
 Configure Dynamic Memory for given Virtual Machines.

 Description:
   Configure Dynamic Memory parameters for a set of Virtual Machines.
   The testParams have the format of:

      vmName=Name of a VM, enableDM=[yes|no], minMem= (decimal) [MB|GB|%], maxMem=(decimal) [MB|GB|%],
      startupMem=(decimal) [MB|GB|%], memWeight=(0 < decimal < 100)

   vmName is the name of a existing Virtual Machines.

   enable specifies if Dynamic Memory should be enabled or not on the given Virtual Machines.
     accepted values are: yes | no

   minMem is the minimum amount of memory assigned to the specified virtual machine(s)
    the amount of memory can be specified as a decimal followed by a qualifier
    valid qualifiers are: MB, GB and % . %(percent) means percentage of free Memory on the host

   maxMem is the maximum memory amount assigned to the virtual machine(s)
    the amount of memory can be specified as a decimal followed by a qualifier
    valid qualifiers are: MB, GB and % . %(percent) means percentage of free Memory on the host

   startupMem is the amount of memory assigned at startup for the given VM
    the amount of memory can be specified as a decimal followed by a qualifier
    valid qualifiers are: MB, GB and % . %(percent) means percentage of free Memory on the host

   memWeight is the priority a given VM has when assigning Dynamic Memory
    the memory weight is a decimal between 0 and 100, 0 meaning lowest priority and 100 highest.

   The following is an example of a testParam for configuring Dynamic Memory

       "enableDM=yes;minMem=512MB;maxMem=50%;startupMem=1GB;memWeight=20"

   All setup and cleanup scripts must return a boolean ($true or $false)
   to indicate if the script completed successfully or not.

   .Parameter vmName
    Name of the VM to remove NIC from .

    .Parameter hvServer
    Name of the Hyper-V server hosting the VM.

    .Parameter testParams
    Test data for this test case

#>
param([String] $TestParams)

function Main {
    param (
         $TestParams
	  )
    $currentTestResult = CreateTestResultObject
    $resultArr = @()
    try {
        $testResult = $null
        $captureVMData = $allVMData
        $VMName = $captureVMData.RoleName
        $HvServer= $captureVMData.HyperVhost
        #
        # Check input arguments
        #
        if (-not $VMName)
        {
           throw "INFO: VM name is null. "
        }
        if (-not $HvServer)
        {
            throw "Error: HvServer is null"
        }
        if (-not $TestParams)
        {
          throw "Error: TestParams is null"
        }
        $tpEnabled = $null
        [int64]$tPminMem = 0
        [int64]$tPmaxMem = 0
        [int64]$tPstartupMem = 0
        [int64]$tPmemWeight = -1
        [int64]$tPstaticMem = 0
        $bootLargeMem = $false
        if ($TestParams.enableDM -ilike "yes")
        {
            $tpEnabled = $true
        }
        else
        {
            $tpEnabled = $false
        }
        $tPminMem = Convert-ToMemSize $TestParams.minMem $HvServer

        if ($tPminMem -le 0)
        {
            LogErr "Error: Unable to convert minMem to int64."
        }

        $tPmaxMem = Convert-ToMemSize $TestParams.maxMem $HvServer

        if ($tPmaxMem -le 0)
        {
           LogErr "Error: Unable to convert maxMem to int64."
        }
        $tPstartupMem = Convert-ToMemSize $TestParams.startupMem $HvServer
        if ($tPstartupMem -le 0)
        {
            LogErr "Error: Unable to convert minMem to int64."
        }
        $tPmemWeight = [Convert]::ToInt32($TestParams.memWeight)

        if ($tPmemWeight -lt 0 -or $tPmemWeight -gt 100)
        {
           throw "Error: Memory weight needs to be between 0 and 100."
        }
        LogMsg "tPmemWeight $tPmemWeight"

        if ($TestParams.bootLargeMem -ilike "yes")
        {
		    $bootLargeMem = $true
        }
        LogMsg "BootLargeMemory: $bootLargeMem"
        $tPstaticMem = Convert-ToMemSize $TestParams.staticMem $HvServer
        if ($tPstaticMem -le 0)
        {
           LogErr "Error: Unable to convert staticMem to int64."
        }
        # check if we have all variables set
        if ( $VMName -and ($tpEnabled -eq $false -or $tpEnabled -eq $true) -and $tPstartupMem -and ([int64]$tPmemWeight -ge [int64]0) )
        {
            # make sure VM is off
            if (Get-VM -Name $VMName -ComputerName $HvServer |  Where-Object { $_.State -like "Running" })
            {
                LogMsg "Stopping VM $VMName"
                Stop-VM -Name $VMName -ComputerName $HvServer -force

                if (-not $?)
                {
                    throw "Error: Unable to shut $VMName down (in order to set Memory parameters)"
                }

                # wait for VM to finish shutting down
                $timeout = 30
                while (Get-VM -Name $VMName -ComputerName $HvServer |  Where-Object { $_.State -notlike "Off" })
                {
                    if ($timeout -le 0)
                    {
                        throw "Error: Unable to shutdown $VMName"
                    }
                    start-sleep -s 5
                    $timeout = $timeout - 5
                }
            }
            if ($bootLargeMem) {
                $OSInfo = Get-CIMInstance Win32_OperatingSystem -ComputerName $HvServer
		        $freeMem = $OSInfo.FreePhysicalMemory * 1KB
		        if ($tPstartupMem -le $freeMem) {
		            Set-VMMemory -VMName $VMName -ComputerName $HvServer -DynamicMemoryEnabled $false -StartupBytes $tPstartupMem
                }
                else {
                    throw "Error: Insufficient memory to run test. Skipping test."
		        }
            }
	        elseif ($tpEnabled)
            {
                if ($maxMem_xmlValue -eq $startupMem_xmlValue)
                {
                  $tPstartupMem = $tPmaxMem
                }
                Set-VMMemory -VMName $VMName -ComputerName $HvServer -DynamicMemoryEnabled $tpEnabled `
                              -MinimumBytes $tPminMem -MaximumBytes $tPmaxMem -StartupBytes $tPstartupMem `
                              -Priority $tPmemWeight
            }
            else
            {
                Set-VMMemory -VMName $VMName -ComputerName $HvServer -DynamicMemoryEnabled $tpEnabled `
                            -StartupBytes $tPstartupMem -Priority $tPmemWeight
            }
            if ( $?){
               LogMsg "set VM memeory for $VMName."
            }
            if (-not $?)
            {
                throw "Error: Unable to set VM Memory for $VMName."
                "DM enabled: $tpEnabled"
                "min Mem: $tPminMem"
                "max Mem: $tPmaxMem"
                "startup Mem: $tPstartupMem"
                "weight Mem: $tPmemWeight"
            }
            # check if mem is set correctly
            $vm_mem = (Get-VMMemory $VMName -ComputerName $HvServer).Startup
            if( $vm_mem -eq $tPstartupMem )
            {
                LogMSG "Set VM Startup Memory for $VMName to $tPstartupMem"
                $testResult = "PASS"
            }
            else
            {
                throw "Error : Unable to set VM Startup Memory for $VMName to $tPstartupMem"
            }
        }
    }
    catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    }
    finally {
        if (!$testResult) {
            $testResult = "Aborted"
        }
            $resultArr += $testResult
    }

    $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}

Main -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n"))