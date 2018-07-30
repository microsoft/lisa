# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#

$here = Split-Path -Parent $MyInvocation.MyCommand.Path

$moduleName = "HyperV"
$modulePath = Join-Path $here "../../Libraries/${moduleName}.psm1"

if (Get-Module $moduleName -ErrorAction SilentlyContinue) {
    Remove-Module $moduleName
}

Describe "Test if module ${moduleName} is valid" {
    It "Should load a valid module" {
        { Import-Module $modulePath } | Should Not Throw
    }
}