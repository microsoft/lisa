# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$moduleName = "LISAv2-Framework"

Import-Module (Join-Path $here "..\..\${moduleName}") -Force -DisableNameChecking

function Select-AzureRmSubscription {
	param($SubscriptionId)
	return
}

Describe "Test if module ${moduleName} Run-LISAv2 fails" {
	It "Should fail with bad test platform parameters" {
		Mock Write-LogInfo -Verifiable -ModuleName $moduleName {}
		Mock Write-LogErr -Verifiable -ModuleName $moduleName {}

		{ Run-LISAv2 -Verbose } | Should Throw

		Assert-VerifiableMock
	}
}
