Function LogText ($text)
{
        Write-Host "$(Get-Date -Format "yyyy-mm-dd hh:mm:ss tt") : INFO : $text"
}

Function ValidateVHD($vhdPath)
{
    try
    {
        $tempVHDName = Split-Path $vhdPath -leaf
        LogText -text "Inspecting '$tempVHDName'. Please wait..."
        $vhdInfo = Get-VHD -Path $vhdPath -ErrorAction Stop
        LogText -text "  VhdFormat            :$($vhdInfo.VhdFormat)"
        LogText -text "  VhdType              :$($vhdInfo.VhdType)"
        LogText -text "  FileSize             :$($vhdInfo.FileSize)"
        LogText -text "  Size                 :$($vhdInfo.Size)"
        LogText -text "  LogicalSectorSize    :$($vhdInfo.LogicalSectorSize)"
        LogText -text "  PhysicalSectorSize   :$($vhdInfo.PhysicalSectorSize)"
        LogText -text "  BlockSize            :$($vhdInfo.BlockSize)"
        LogText -text "Validation successful."
    }
    catch
    {
        LogText -text "Failed: Get-VHD -Path $vhdPath"
        Throw "INVALID_VHD_EXCEPTION"
    }
}

Function ValidateMD5($filePath, $expectedMD5hash)
{
    LogText -text "Expected MD5 hash for $filePath : $($expectedMD5hash.ToUpper())"
    $hash = Get-FileHash -Path $filePath -Algorithm MD5
    LogText -text "Calculated MD5 hash for $filePath : $($hash.Hash.ToUpper())"
    if ($hash.Hash.ToUpper() -eq  $expectedMD5hash.ToUpper())
    {
        LogText -text "MD5 checksum verified successfully."
    }
    else
    {
        Throw "MD5 checksum verification failed."
    }
}

function Test-FileLock {
  param (
    [parameter(Mandatory=$true)][string]$Path
  )

  $oFile = New-Object System.IO.FileInfo $Path

  if ((Test-Path -Path $Path) -eq $false) {
    return $false
  }

  try {
    $oStream = $oFile.Open([System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)

    if ($oStream) {
      $oStream.Close()
    }
    $false
  } catch {
    # file is locked by a process.
    return $true
  }
}