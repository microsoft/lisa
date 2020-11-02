# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#

$here = Split-Path -Parent $MyInvocation.MyCommand.Path

$moduleName = "Azure"
$modulePath = Join-Path $here "../../../Libraries/${moduleName}.psm1"
$logModulePath = Join-Path $here "../../../Libraries/TestLogs.psm1"

if (Get-Module $moduleName -ErrorAction SilentlyContinue) {
    Remove-Module $moduleName
}

function Get-AzVM {}

function Get-LISAStorageAccount {}

function Get-AzStorageAccount {}

function Get-AzStorageAccountKey {}


Describe "Test if module ${moduleName} is valid" {
    It "Should load a valid module" {
        { Import-Module $modulePath -DisableNameChecking } | Should -Not -Throw
        { Import-Module $logModulePath -DisableNameChecking } | Should -Not -Throw
    }
}

Describe "Test Get-AzureBootDiagnostics" {
    Mock Get-AzVM -Verifiable -ModuleName $moduleName { return @{"BootDiagnostics"=@{"SerialConsoleLogBlobUri" = "http://fake.fakepath.com/blob/blobpath"}} }
    Mock Write-LogInfo -Verifiable -ModuleName $moduleName { return }
    Mock Get-LISAStorageAccount -Verifiable -ModuleName $moduleName { return @{"StorageAccountName" = "fake"; "ResourceGroupName" = "fake_rg"}}
    Mock Get-AzStorageAccountKey -Verifiable -ModuleName $moduleName { throw "fail"}

    It "Should not find an AzureVmKernelPanic" {
        Get-AzureBootDiagnostics @{"ResourceGroupName" = "fake_rg"; "RoleName" = "fake_role"} | Should -Be $false
    }

    It "Should run all mocked commands" {
        Assert-VerifiableMock
    }
}

Describe "Test Check-AzureVmKernelPanic" {
    Mock Get-AzureBootDiagnostics -Verifiable -ModuleName $moduleName { return $true }
    Mock Test-Path -Verifiable -ModuleName $moduleName { return $true }
    Mock Get-Content -Verifiable -ModuleName $moduleName { return "RIP: rest in peace" }

    It "Should not find an AzureVmKernelPanic" {
        Check-AzureVmKernelPanic | Should -Be $true
    }

    It "Should run all mocked commands" {
        Assert-VerifiableMock
    }
}