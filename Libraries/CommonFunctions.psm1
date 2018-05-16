Function ThrowException($Exception)
{
    $line = $Exception.InvocationInfo.ScriptLineNumber
    $script_name = ($Exception.InvocationInfo.ScriptName).Replace($PWD,".")
    $ErrorMessage =  $Exception.Exception.Message
    Write-Host "EXCEPTION : $ErrorMessage"
    Write-Host "SOURCE : Line $line in script $script_name."
    Throw "Calling function - $($MyInvocation.MyCommand)"
}
function LogVerbose () 
{
    param
    (
        [string]$text
    )
    try
    {
        $text = $text.Replace('"','`"')
        $now = [Datetime]::Now.ToUniversalTime().ToString("MM/dd/yyyy HH:mm:ss")
        if ( $VerboseCommand )
        {
            Write-Verbose "$now : $text" -Verbose       
        }
    }
    catch
    {
        ThrowException($_)
    }
}
function LogError () 
{
    param
    (
        [string]$text
    )
    try
    {
        $text = $text.Replace('"','`"')
        $now = [Datetime]::Now.ToUniversalTime().ToString("MM/dd/yyyy HH:mm:ss")
        Write-Host "Error: $now : $text"
    }
    catch
    {
        ThrowException($_)
    }    
}

function LogMsg()
{
    param
    (
        [string]$text
    )
    try
    {
        $text = $text.Replace('"','`"')
        $now = [Datetime]::Now.ToUniversalTime().ToString("MM/dd/yyyy HH:mm:ss")
        Write-Host "$now : $text"
    }
    catch
    {
        ThrowException($_)
    }  
}

Function LogErr 
{
    param
    (
        [string]$text
    )
    {
        LogError ($text)
    }
}

Function LogWarn()
{
    param
    (
        [string]$text
    )
    try
    {
        $text = $text.Replace('"','`"')
        $now = [Datetime]::Now.ToUniversalTime().ToString("MM/dd/yyyy HH:mm:ss")
        Write-Host "WARGNING: $now : $text"
    }
    catch
    {
        ThrowException($_)
    }  
}
Function ValiateXMLs( [string]$ParentFolder )
{
    LogMsg "Validating XML Files from $ParentFolder folder recursively..."
    LogVerbose "Get-ChildItem `"$ParentFolder\*.xml`" -Recurse..."
    $allXmls = Get-ChildItem "$ParentFolder\*.xml" -Recurse
    $xmlErrorFiles = @()
    foreach ($file in $allXmls)
    {
        try
        {
            $TempXml = [xml](Get-Content $file.FullName)
            LogVerbose -text "$($file.FullName) validation successful."
            
        }
        catch
        {
            LogError -text "$($file.FullName) validation failed."
            $xmlErrorFiles += $file.FullName
        }
    }
    if ( $xmlErrorFiles.Count -gt 0 )
    {
        $xmlErrorFiles | ForEach-Object -Process {LogMsg $_}
        Throw "Please fix above ($($xmlErrorFiles.Count)) XML files."
    }
}