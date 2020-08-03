# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#

using Module "..\..\..\TestControllers\AzureController.psm1"

$moduleName = "AzureController"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$logModulePath = Join-Path $here "../../../Libraries/TestLogs.psm1"
$helpersModulePath = Join-Path $here "../../../Libraries/TestHelpers.psm1"
$azureModulePath = Join-Path $here "../../../Libraries/Azure.psm1"
Import-Module $logModulePath -Force -DisableNameChecking
Import-Module $helpersModulePath -Force -DisableNameChecking
Import-Module $azureModulePath -Force -DisableNameChecking

function Select-AzSubscription {
	param($SubscriptionId)
	return
}

Describe "Test if module ${moduleName} ParseAndValidateParameters is valid" {
	It "Should validate parameters" {
		Mock Write-LogInfo -Verifiable -ModuleName $moduleName { return }

		$azureController = New-Object -TypeName $moduleName
		$fakeParams = @{
			"RGIdentifier" = "fakeRG";
			"ARMImageName" = "one two three four";
			"TestLocation" = "fakeLocation";
		}

		{ $azureController.ParseAndValidateParameters($fakeParams) } | Should -Not -Throw
	}

	It "Should not validate parameters" {
		Mock Write-LogErr -Verifiable -ModuleName $moduleName { return }

		$azureController = New-Object -TypeName $moduleName
		$fakeParams = @{
			"RGIdentifier" = "";
			"ARMImageName" = "one two three";
			"TestLocation" = "";
		}

		{ $azureController.ParseAndValidateParameters($fakeParams) } | Should -Throw
	}

	It "Should run all mocked commands" {
		Assert-VerifiableMock
	}
}

Describe "Test if module ${moduleName} SetGlobalVariables is valid" {
	It "Should set global variables" {
		#Mock Set-Variable -Verifiable -ModuleName $moduleName { return }

		$azureController = New-Object -TypeName $moduleName

		{ $azureController.SetGlobalVariables() } | Should -Not -Throw
	}

	It "Should run all mocked commands" {
		Assert-VerifiableMock
	}
}

Describe "Test if module ${moduleName} PrepareTestEnvironment is valid" {
	It "Should prepare test env" {

		Mock Set-Variable -Verifiable -ModuleName $moduleName { return }
		Mock Add-AzureAccountFromSecretsFile -Verifiable -ModuleName $moduleName { return }
		Mock Write-LogErr -Verifiable -ModuleName "TestController" { return }
		Mock Write-LogInfo -Verifiable -ModuleName $moduleName { return }
		Mock Resolve-Path -Verifiable -ModuleName "TestController" {
			$fakeXML = Join-Path $env:temp "test.xml"
			New-Item -Type File -Path $fakeXML -Force | Out-Null;
			@'
			<Global>
				<Azure>
					<Subscription>
						<SubscriptionID>test</SubscriptionID>
						<ARMStorageAccount>ARMStorageAccount</ARMStorageAccount>
					</Subscription>
				</Azure>
			</Global>
'@ | Add-Content -Path $fakeXML
			return $fakeXML
		}
		Mock Get-LISAv2Tools -Verifiable -ModuleName "TestController" { return }
		Mock Set-AzContext -Verifiable -ModuleName $moduleName {
			return @{
				"Account" = @{
					"Id" = "Id"
				};
				"Subscription" = @{
					"SubscriptionId" = "SubscriptionId";
					"ARMStorageAccount" = "ARMStorageAccount";
					"Name" = "SubscriptionId"
				};
				"Environment" = @{
					"ActiveDirectoryServiceEndpointResourceId" = "https://management.core.windows.net/"
				}
			}
		}

		$azureController = New-Object -TypeName $moduleName
		$azureController.TestLocation = "westus2"
		$azureController.GlobalConfigurationFilePath = ".\XML\GlobalConfigurations.xml"
		$fakeXML = "test1.xml"

		{ $azureController.PrepareTestEnvironment($fakeXML) } | Should -Not -Throw
	}
}

Describe "Test if module ${moduleName} PrepareTestEnvironment can fail" {
	It "Should fail to prepare test env" {
		Mock Write-LogErr -Verifiable -ModuleName "TestController" { return }

		$azureController = New-Object -TypeName $moduleName

		$fakeXML = "test2.xml"
		{ $azureController.PrepareTestEnvironment($fakeXML) } | Should -Throw
	}

	It "Should run all mocked commands" {
		Assert-VerifiableMock
	}
}

Describe "Test if module ${moduleName} PrepareTestImage is valid" {
	It "Should set prepare test image" {
		$azureController = New-Object -TypeName $moduleName

		{ $azureController.PrepareTestImage() } | Should -Not -Throw
	}

	It "Should run all mocked commands" {
		Assert-VerifiableMock
	}
}
