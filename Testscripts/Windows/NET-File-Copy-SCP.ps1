# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    The script will copy 2 random generated 10GB files from a Windows host to
    the Linux VM, and then check if the sizes and checksums are matching.
#>

param([String] $TestParams,
      [object] $AllVmData)

#  Checks if test file is present
function Get-FileCheck {
    param (
        [String] $testfile,
        [String] $IPv4,
        [String] $VMPassword,
        [String] $VMUser,
        [String] $VMPort
    )
    $null = Run-LinuxCmd -username $VMUser -password $VMPassword -ip $IPv4 `
        -port $VMPort -command "wc -c < /mnt/$testfile" -ignoreLinuxExitCode:$true
    if (-not $?) {
        Write-LogErr "Unable to read file /mnt/$testfile"
        return $False
    }
    return $True
}

# Mount disk
function Connect-Disk {
    param (
        [String] $IPv4,
        [String] $VMPassword,
        [String] $VMUser,
        [String] $VMPort
    )
    $driveName = "/dev/sdc"

    $null = Run-LinuxCmd -username $VMUser -password $VMPassword -ip $IPv4 `
        -port $VMPort -command "(echo d;echo;echo w)|fdisk ${driveName}" -ignoreLinuxExitCode:$true
    if (-not $?) {
        Write-LogErr "Failed to format the disk in the VM"
        return $False
    }

    $null = Run-LinuxCmd -username $VMUser -password $VMPassword -ip $IPv4 `
        -port $VMPort -command "(echo n;echo p;echo 1;echo;echo;echo w)|fdisk ${driveName}"
    if (-not $?) {
        Write-LogErr "Failed to format the disk in the VM"
        return $False
    }

    $null = Run-LinuxCmd -username $VMUser -password $VMPassword -ip $IPv4 `
        -port $VMPort -command "mkfs.ext4 ${driveName}1"
    if (-not $?) {
        Write-LogErr "Failed to make file system in the VM"
        return $False
    }

    $null = Run-LinuxCmd -username $VMUser -password $VMPassword -ip $IPv4 `
        -port $VMPort -command "mount ${driveName}1 /mnt"
    if (-not $?) {
        Write-LogErr "Failed to mount the disk in the VM"
        return $False
    }

    Write-LogInfo "$driveName has been mounted to /mnt in the VM"
    return $True
}

# Create the test file
function Initialize-File {
    param (
        $Filename,
        $Filesize,
        $HvServer
    )
    # Get VHD path of tested server; file will be copied there
    $vhd_path = Get-VMHost -ComputerName $HvServer | Select-Object -ExpandProperty VirtualHardDiskPath

    # Fix path format if it's broken
    if ($vhd_path.Substring($vhd_path.Length - 1, 1) -ne "\"){
        $vhd_path = $vhd_path + "\"
    }

    $vhd_path_formatted = $vhd_path.Replace(':','$')

    $filePath = $vhd_path + $Filename
    $file_path_formatted = $vhd_path_formatted + $Filename
    $fullFilePath = "\\" + $HvServer + "\" + $file_path_formatted

    # Create a 10GB sample file
    $createfile = fsutil file createnew \\$HvServer\$file_path_formatted $Filesize

    if ($createfile -notlike "File *testfile-* is created") {
        Write-LogErr "Could not create the sample test file in the working directory! $file_path_formatted"
        exit -1
    }
    return $filePath, $file_path_formatted, $fullFilePath
}

#  Compute local files MD5
function Get-LocalMD5 {
    param (
        $FilePath
    )
    $localChksum = Get-FileHash $FilePath -Algorithm MD5 | Select-Object -ExpandProperty hash
    if (-not $?){
        Write-LogErr "Unable to get MD5 checksum"
        exit -1
    }
    else {
        Write-LogInfo "MD5 checksum on Hyper-V: $localChksum"
    }
    return $localChksum
}

# delete created files
function Remove-Files {
    param (
        [String] $HvServer,
        [String] $FilePathFormatted1,
        [String] $FilePathFormatted2
    )
    Remove-Item -Path \\$HvServer\$FilePathFormatted1 -Force
    if (-not $?) {
        Write-LogErr "Cannot remove the test file '${FilePathFormatted1}'!"
    }
    Remove-Item -Path \\$HvServer\$FilePathFormatted2 -Force
    if (-not $?) {
        Write-LogErr "Cannot remove the test file '${FilePathFormatted2}'!"
    }
}

# Main function
function Main {
    param (
        $HvServer,
        $IPv4,
        $VMPort,
        $VMPassword
    )
    $guestUsername = "root"

    Provision-VMsForLisa -allVMData $AllVMData -installPackagesOnRoleNames none
    # 10GB file size
    $filesize1 = 10737418240
    # 10GB file size
    $filesize2 = 10737418240
    # Define the file-name to use with the current time-stamp
    $testfile1 = "testfile-$(Get-Date -uformat '%H-%M-%S-%Y-%m-%d').file"
    $filePath1, $filePathFormatted1, $fullFilePath1 = Initialize-File $testfile1 $filesize1 $HvServer

    # Define the second file-name to use with the current time-stamp
    $testfile2 = "testfile-2-$(Get-Date -uformat '%H-%M-%S-%Y-%m-%d').file"
    $filePath2, $filePathFormatted2, $fullFilePath2 = Initialize-File $testfile2 $filesize2 $HvServer

    # mount disk
    $sts = Connect-Disk $IPv4 $VMPassword $guestUsername $VMPort
    if (-not $sts[-1]) {
        Write-LogErr "Failed to mount the disk in the VM."
        return "FAIL"
    }

    $localChksum1 = Get-LocalMD5 $fullFilePath1
    $localChksum2 = Get-LocalMD5 $fullFilePath2

    # Copy the file to the Linux guest VM
    # Using pscp because Copy-RemoteFiles function doesn't have the option of a specific location
    $Error.Clear()
    $command = "& '$((Get-Location).Path)\Tools\pscp.exe' -pw ${VMPassword} -P ${VMPort} '${fullFilePath2}' ${guestUsername}@${IPv4}:/mnt/"

    $job = Start-Job -ScriptBlock {Invoke-Expression $args[0]} -ArgumentList $command
    if (-not $job) {
        Write-LogErr "Job to transfer the 2nd file failed to start!"
        return "FAIL"
    }

    # Checking if the job is actually running
    $jobInfo = Get-Job -Id $job.Id
    if($jobInfo.State -ne "Running") {
        Write-LogErr "job did not start or terminated immediately!"
        return "FAIL"
    }

    $copyDuration1 = (Measure-Command { Tools\pscp.exe -pw $VMPassword -P $VMPort ${fullFilePath1} ${guestUsername}@${IPv4}:/mnt/ }).TotalMinutes
    while ($True){
        if ($job.state -eq "Completed"){
                $copyDuration2 = ($job.PSEndTime - $job.PSBeginTime).TotalMinutes
                Remove-Job -id $job.id
           break
        }
    }

    if ($Error.Count -eq 0) {
        Write-LogInfo "File has been successfully copied to guest VM"
    } else {
        Write-LogErr "An error occured while copying files!"
        Remove-Files $HvServer $filePathFormatted1 $filePathFormatted2
        return "FAIL"
    }

    Write-LogInfo "The file copy process took $([System.Math]::Round($copyDuration1, 2)) minutes for first file `
     and $([System.Math]::Round($copyDuration2, 2)) minutes for second file"

    # Checking if the file is present on the guest and file size is matching
    $sts = Get-FileCheck $testfile1 $IPv4 $VMPassword $guestUsername $VMPort
    if (-not $sts) {
        Write-LogErr "1st file is not present on the guest VM!"
        return "FAIL"
    } elseif ($sts -eq $filesize1) {
        "The 1st file copied matches the 10GB size."
    } else {
        Write-LogErr "The 1st file copied doesn't match the 10GB size!"
        Remove-Files $HvServer $filePathFormatted1 $filePathFormatted2
        return "FAIL"
    }

    # Checking if the file is present on the guest and file size is matching
    $sts = Get-FileCheck $testfile2 $IPv4 $VMPassword $guestUsername $VMPort
    if (-not $sts[-1]) {
        Write-LogErr "2nd file is not present on the guest VM!"
        Remove-Files $HvServer $filePathFormatted1 $filePathFormatted2
        return "FAIL"
    } elseif ($sts[0] -eq $filesize2) {
        Write-LogInfo "The 2nd file copied matches the 10GB size."
    } else {
        Write-LogErr "The 2nd file copied doesn't match the 10GB size!"
        Remove-Files
        return "FAIL"
    }

    # Get MD5 checksum for files on the VM
    # first file
    $md5RemoteFile1 = Run-LinuxCmd -username $guestUsername -password $VMPassword -ip $IPv4 `
        -port $VMPort -command "openssl md5 /mnt/$testfile1" -ignoreLinuxExitCode:$true
    if (-not $?) {
        Write-LogErr "Unable to run openssl command on VM for first file!"
        Remove-Files $HvServer $filePathFormatted1 $filePathFormatted2
        return "FAIL"
    }

    # Extract only the MD5 hash for the remote and local variables
    $remoteChecksum1=$md5RemoteFile1.split()[-1]
    $localFile1MD5=$localChksum1.split()[-1]
    Write-LogInfo "MD5 checksum for 1st file on Guest VM: $remoteChecksum1"

    $md5IsMatching1 = [string]::Compare($remoteChecksum1, $localFile1MD5, $true)
    if ($md5IsMatching1 -ne 0) {
        Write-LogErr "MD5 checksums are not matching for first file"
        Remove-Files $HvServer $filePathFormatted1 $filePathFormatted2
        return "FAIL"
    }
    Write-LogInfo "MD5 checksums are matching for first file"

    # 2nd file
    $md5RemoteFile2 = Run-LinuxCmd -username $guestUsername -password $VMPassword -ip $IPv4 `
        -port $VMPort -command "openssl md5 /mnt/$testfile2" -ignoreLinuxExitCode:$true
    if (-not $?) {
        Write-LogErr "Unable to run openssl command on VM for second file"
        Remove-Files $HvServer $filePathFormatted1 $filePathFormatted2
        return "FAIL"
    }

    $remoteChecksum2=$md5RemoteFile2.split()[-1]
    $localFile2MD5=$localChksum2.split()[-1]
    Write-LogInfo "MD5 checksum for 2nd file on Guest VM: $remoteChecksum2"

    $md5IsMatching2 = [string]::Compare($remoteChecksum2, $localFile2MD5, $true)
    if ($md5IsMatching2 -ne 0) {
        Write-LogErr "MD5 checksums are not matching for second file"
        Remove-Files $HvServer $filePathFormatted1 $filePathFormatted2
        return "FAIL"
    }
    Write-LogInfo "MD5 checksums are matching for the second file"

    Remove-Files $HvServer $filePathFormatted1 $filePathFormatted2
    return "PASS"
}

Main -HvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName -IPv4 $AllVMData.PublicIP `
     -VMPort $AllVMData.SSHPort -VMPassword $password
