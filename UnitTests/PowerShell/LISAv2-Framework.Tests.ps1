# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$moduleName = "LISAv2-Framework"

Import-Module (Join-Path $here "..\..\${moduleName}") -Force -DisableNameChecking

function Select-AzSubscription {
	param($SubscriptionId)
	return
}

Describe "Test if ${moduleName} Run-LISAv2 fails" {
	It "Should fail with bad test platform parameters" {
		Mock Write-LogInfo -Verifiable -ModuleName $moduleName {}
		Mock Write-LogErr -Verifiable -ModuleName $moduleName {}

		{ Run-LISAv2 -Verbose } | Should -Throw

		Assert-VerifiableMock
	}
}


Describe "Test if ${moduleName} Run-LISAv2 fails with no test cases found" {
	It "Should fail with no test case found" {
		Mock Write-LogInfo -Verifiable -ModuleName $moduleName {}
		Mock Write-LogErr -Verifiable -ModuleName $moduleName {}
		Mock Validate-XmlFiles -Verifiable -ModuleName $moduleName {}

		Mock Write-LogInfo -Verifiable -ModuleName "AzureController" {}
		Mock Select-AzSubscription -Verifiable -ModuleName "AzureController" {
			return @{
				"Account" = @{
					"Id" = "Id";
					"Type" = "User"
				};
				"Subscription" = @{
					"SubscriptionId" = "SubscriptionId";
					"ARMStorageAccount" = "ARMStorageAccount";
					"Name" = "SubscriptionId"
				}
			}
		}

		Mock Write-LogErr -Verifiable -ModuleName "TestController" {}
		Mock Select-TestCases -Verifiable -ModuleName "TestController" {}

		{ Run-LISAv2 -Verbose -TestPlatform "Azure" -RGIdentifier "test" -ARMImageName "one two three four" `
			-TestLocation "westus2" } | Should -Throw

		Assert-VerifiableMock
	}
}

Describe "Test if ${moduleName} Run-LISAv2 fails to parse report results on Azure" {
	It "Should fail at parsing report results on Azure" {
		Mock Write-LogInfo -Verifiable -ModuleName "AzureController" {}
		Mock Measure-SubscriptionCapabilities -Verifiable -ModuleName "AzureController" {}
		Mock Select-AzSubscription -Verifiable -ModuleName "AzureController" {
			return @{
				"Account" = @{
					"Id" = "Id";
					"Type" = "User"
				};
				"Subscription" = @{
					"SubscriptionId" = "SubscriptionId";
					"ARMStorageAccount" = "ARMStorageAccount";
					"Name" = "SubscriptionId"
				}
			}
		}

		Mock Write-LogErr -Verifiable -ModuleName "AzureProvider" {}
		Mock Invoke-AllResourceGroupDeployments -Verifiable -ModuleName "AzureProvider" { return }

		Mock Write-LogInfo -Verifiable -ModuleName "TestController" {}
		Mock Write-LogErr -Verifiable -ModuleName "TestController" {}

		Mock New-Item -Verifiable -ModuleName "TestLogs" { return }
		Mock Add-Content -Verifiable -ModuleName "TestLogs" { return }
		Mock Write-LogInfo -Verifiable -ModuleName $moduleName {}
		Mock Validate-XmlFiles -Verifiable -ModuleName $moduleName {}
		Mock New-Item -Verifiable -ModuleName $moduleName { return }
		Mock Join-Path -Verifiable -ModuleName $moduleName { return "fake_path"}
		Mock New-ZipFile -Verifiable -ModuleName $moduleName { return }

		{ Run-LISAv2 -Verbose -TestPlatform "Azure" -RGIdentifier "test" -ARMImageName "one two three four" `
			-TestLocation "westus2" -TestNames "VERIFY-DEPLOYMENT-PROVISION"} | Should -Throw

		Assert-VerifiableMock
	}
}
