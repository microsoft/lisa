# Run PowerShell Unit Tests with Pester

Pester is a PowerShell library used for testing PowerShell code.

Pester's GitHub page: https://github.com/pester/Pester

## Install Pester

Pester comes preinstalled in Windows 10.

To install / update Pester on Windows >= 10:

```powershell
    Install-Module -Name Pester -Force -SkipPublisherCheck
```

## Create a unit test file

A PowerShell Pester test file should have the suffix `.Tests.ps1`.

The content of such a file should follow a classical BDD (Behaviorual Driven Deployment) test format.

```powershell

# Function under test
function Get-Cookie ([string]$Name="*")
{
    $cookies = @(
        @{ Name = 'Fudge' }
        @{ Name = 'Fortune' }
    )
    $cookies | where { $_.Name -like $Name }
}

# Pester tests
Describe 'Get-Cookie' {
    It "Given no parameters, it lists both cookies" {
       $cookies = Get-Cookie
       $cookies.Count | Should Be 2
    }
}
```

## Run Pester

```cmd
    powershell.exe -NonInteractive {Invoke-Pester }
```