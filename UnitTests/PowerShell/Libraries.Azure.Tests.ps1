# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#

$here = Split-Path -Parent $MyInvocation.MyCommand.Path

$moduleName = "Azure"
$modulePath = Join-Path $here "../../Libraries/${moduleName}.psm1"
$logProcessingModulePath = Join-Path $here "../../Libraries/LogProcessing.psm1"

if (Get-Module $moduleName -ErrorAction SilentlyContinue) {
    Remove-Module $moduleName
}

function Get-AzureRmVm {}

function Get-AzureRmStorageAccount {}

function Get-AzureRmStorageAccountKey {}


Describe "Test if module ${moduleName} is valid" {
    It "Should load a valid module" {
        { Import-Module $modulePath -DisableNameChecking } | Should Not Throw
        { Import-Module $logProcessingModulePath -DisableNameChecking } | Should Not Throw
    }
}

Describe "Test Get-AzureBootDiagnostics" {
    Mock Get-AzureRmVm -Verifiable -ModuleName $moduleName { return @{"BootDiagnostics"=@{"SerialConsoleLogBlobUri" = "http://fake.fakepath.com/blob/blobpath"}} }
    Mock Write-LogInfo -Verifiable -ModuleName $moduleName { return }
    Mock Get-AzureRmStorageAccount -Verifiable -ModuleName $moduleName { return @{"StorageAccountName" = "fake"; "ResourceGroupName" = "fake_rg"}}
    Mock Get-AzureRmStorageAccountKey -Verifiable -ModuleName $moduleName { throw "fail"}

    It "Should not find an AzureVmKernelPanic" {
        Get-AzureBootDiagnostics @{"ResourceGroupName" = "fake_rg"; "RoleName" = "fake_role"} | Should Be $false
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
        Check-AzureVmKernelPanic | Should Be $true
    }

    It "Should run all mocked commands" {
        Assert-VerifiableMock
    }
}