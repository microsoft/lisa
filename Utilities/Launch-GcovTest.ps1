param (
    [Parameter(Mandatory=$true)] [String] $SrcPackagePath,
    [Parameter(Mandatory=$true)] [String] $ReportDestination,
    [String] $LogPath,
    [String] $TestCategory,
    [String] $ReportName,
    [String] $TestArea,
    [String] $TestNames,
    [Switch] $OverallReport,

    # LISAv2 Params
    [Parameter(Mandatory=$true)] [String] $RGIdentifier,
    [Parameter(Mandatory=$true)] [String] $TestPlatform,
    [Parameter(Mandatory=$true)] [String] $TestLocation,
    [Parameter(Mandatory=$true)] [String] $StorageAccount,
    [Parameter(Mandatory=$true)] [String] $XMLSecretFile
)

$ARM_IMAGE_NAME = "Canonical UbuntuServer 18.04-LTS latest"
$TAR_PATH = "$($env:ProgramFiles)\Git\usr\bin\tar.exe"
$CURRENT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$WORK_DIR = $CURRENT_DIR.Directory.FullName

function Main {
    $SrcPackagePath = Resolve-Path $SrcPackagePath
    if ((-not $SrcPackagePath) -or (-not (Test-Path $SrcPackagePath))) {
        throw "Cannot find kernel source package"
    }

    $reportName = "report"
    if ($ReportName) {
        $reportName = $ReportName
    }elseif ($TestArea) {
        $reportName = $TestArea.ToLower()
    } else {
        $reportName = $TestCategory.ToLower()
    }

    $tests = @{}
    if ($TestArea) {
        $tests += @{"TestArea" = $TestArea}
    }
    if ($TestCategory) {
        $tests += @{"TestCategory" = $TestCategory}
    }
    if ($TestNames) {
        $tests = @{"TestNames" = $TestNames}
    }

    Push-Location $WORK_DIR

    if (-not $OverallReport) {
        Copy-Item -Path $SrcPackagePath "linux-source.deb"

        .\Run-LisaV2.ps1 -RGIdentifier $RGIdentifier -TestPlatform  $TestPlatform `
            -TestNames 'BUILD-GCOV-KERNEL' -TestLocation $TestLocation `
            -ARMImageName $ARM_IMAGE_NAME `
            -TestIterations 1 -StorageAccount $StorageAccount `
            -XMLSecretFile $XMLSecretFile

        $packagesPath = ".\CodeCoverage\artifacts\packages.tar"
        if (-not (Test-Path $packagesPath)) {
            throw "Cannot find kernel artifacts"
        } else {
            $packagesPath = Resolve-Path $packagesPath
            $packagesPath = Get-ChildItem $packagesPath
        }

        Push-Location $packagesPath.Directory.FullName
        & $TAR_PATH xf $packagesPath.Name
        Pop-Location

        .\Run-LisaV2.ps1 -RGIdentifier $RGIdentifier -TestPlatform  $TestPlatform `
            @tests -TestLocation $TestLocation `
            -ARMImageName $ARM_IMAGE_NAME `
            -TestIterations 1 -StorageAccount $StorageAccount `
            -XMLSecretFile $XMLSecretFile `
            -EnableCodeCoverage -CustomKernel "localfile:.\CodeCoverage\artifacts\*.deb"

        if ($LogPath) {
            if (-not (Test-Path $LogPath)) {
                New-Item -Path $LogPath -Type Directory
            }
            if (-not (Test-Path "${LogPath}\logs")) {
                New-Item -Path "${LogPath}\logs" -Type Directory
            }

            Copy-Item -Recurse -Path ".\CodeCoverage\logs\*" -Destination "${LogPath}\logs\" -Force
            Copy-Item -Recurse -Path ".\CodeCoverage\artifacts" -Destination "${LogPath}\" -Force
        }
    } else {
        $reportName = "overall"
        if (-not (Test-Path $LogPath)) {
            throw "Cannot find logs dir"
        }

        $artifactsPath = Join-Path $LogPath "artifacts"
        $logsPath = Join-Path $LogPath "logs"

        if ((-not (Test-Path $artifactsPath)) -or (-not (Test-Path $logsPath))) {
            throw "Cannot find logs"
        }
        if (Test-Path ".\CodeCoverage") {
            Remove-Item -Recurse -Path ".\CodeCoverage"
        }
        New-Item -Path ".\CodeCoverage" -Type Directory

        Copy-Item -Recurse -Path $artifactsPath -Destination ".\CodeCoverage"
        Copy-Item -Recurse -Path $logsPath -Destination ".\CodeCoverage"
    }

    .\Run-LisaV2.ps1 -RGIdentifier $RGIdentifier -TestPlatform  $TestPlatform `
        -TestNames "BUILD-GCOV-REPORT" -TestLocation $TestLocation `
        -ARMImageName $ARM_IMAGE_NAME `
        -TestIterations 1 -StorageAccount $StorageAccount `
        -XMLSecretFile $XMLSecretFile `
        -CustomTestParameters "GCOV_REPORT_CATEGORY=${reportName}"

    $reportsPath = ".\CodeCoverage\${reportName}.zip"
    if (-not (Test-Path $reportsPath)) {
        throw "Cannot find GCOV html report archive"
    }

    if (-not (Test-Path $ReportDestination)) {
        New-Item -Path $ReportDestination -Type Directory
    }
    $ReportDestination = Join-Path $ReportDestination $reportName
    if (Test-Path $ReportDestination) {
        Remove-Item -Path $ReportDestination -Recurse -Force
    }
    New-Item -Path $ReportDestination -Type Directory

    Expand-Archive -Path $reportsPath -DestinationPath $ReportDestination
    Pop-Location
}

Main