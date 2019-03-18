##############################################################################################
# CheckImageUpdate.ps1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.SYNOPSIS
	Check new vhds from specific storage container by check blob's metadata
	If the config file exist, if has below format, main function for the config file is to give us the extra mail receivers
	# Accepted config.xml format:
	# 1. <MailReceivers>someone1@where.com,someone2@where.com</MailReceivers>
	# 2. One of the <MailReceivers> and <LogContainer> tags should be present
	#	<Config>
	#		<ImageMatch>namepattern</ImageMatch>
	#		<MailReceivers>someone1@where.com,someone2@where.com</MailReceivers>
	#		<LogContainer>
	#			<ContainerName>testing-logs</ContainerName>
	#			<SASL_URL>the SAS URL (with write permission) of the container for us to write result to </SASL_URL>
	#		</LogContainer>
	#	</Config>
.PARAMETER
#	See param lines

.INPUTS

.NOTES
    Creation Date:  23rd Nov 2018

.EXAMPLE

#>
###############################################################################################
Function Detect-NewVHDFromStorageContainer {
	param(
		[string]$Containers= "",
		[string]$DetectInterval= ""
	)

	$containers_result = $Containers.Split(";")

	$xmlFile = "blobsXml.xml"
	$configFile = "config.xml"
	$newVhdsFile = "NewVHDs.xml"
	$vhdCount = 0
	$lastCheckTime = [DateTime]::Now.AddHours(-$DetectInterval)

	if (Test-Path $newVhdsFile) {
		Remove-Item $newVhdsFile
	}

	if (Test-Path $xmlFile) {
		Remove-Item $xmlFile
	}

	if (Test-Path $configFile) {
		Remove-Item $configFile
	}

	$VhdInfoXml = New-Object -TypeName xml
	$root = $VhdInfoXml.CreateElement("VHDInfo")
	$VhdInfoXml.AppendChild($root) | Out-Null
	foreach ($container in $containers_result) {
		($DistroCategory, $Url, $TestCategory) = $container.Split(',')
		if (-not $DistroCategory -or -not $Url) {
			continue
		}
		$DistroCategory = $DistroCategory.Trim()
		$Url = $Url.Trim()
		$listBlobUrl = $Url + "&restype=container&comp=list"
		if (Test-Path $xmlFile) {
			Remove-Item $xmlFile
		}

		$configFileUrl = $Url.Insert($Url.IndexOf('?'), "/$configFile")
		$mailReceviers = ""
		try {
			Invoke-RestMethod $configFileUrl -Method Get -ErrorVariable restError -OutFile $configFile

			if ($?) {
				$configXml = [xml](Get-Content $configFile)
				if ($configXml.MailReceivers) {
					$mailReceviers = $configXml.MailReceivers
				}
				if ($configXml.Config) {
					if ($configXml.Config.ImageMatch) {
						$imageMatchRegex = $configXml.Config.ImageMatch
					}
					if ($configXml.Config.MailReceivers) {
						$mailReceviers = $configXml.Config.MailReceivers
					}
					if ($configXml.Config.LogContainer -and $configXml.Config.LogContainer.SASL_URL) {
						$logContainerSAS = $configXml.Config.LogContainer.SASL_URL
					}
				}
			}
		} catch {
			Write-Host "No config file"
		}

		# Get the blob metadata
		Invoke-RestMethod $listBlobUrl -Headers @{"Accept"="Application/xml"} -ErrorVariable restError -OutFile $xmlFile

		if ($?) {
			$blobsXml = [xml](Get-Content $xmlFile)
			$vhdUrls = @()
			foreach ($blob in $blobsXml.EnumerationResults.Blobs.Blob) {
				$timeStamp = [DateTime]::Parse($blob.Properties.'Last-Modified')
				$etag = $blob.Properties.Etag

				if (($timeStamp -gt $lastCheckTime) -and (($blob.Properties.BlobType.ToLower() -eq "pageblob") `
													-or $blob.Name.EndsWith(".vhd")) -and (-not $blob.Name.ToLower().Contains("alpha"))) {
					$srcUrl = $Url.Insert($Url.IndexOf('?'), '/' + $blob.Name)

					# Try get metadata the second time to check whether the VHD is in the progress of uploading. Etag value changes if the vhd is being uploaded.
					Start-Sleep -s 5
					Invoke-RestMethod $listBlobUrl -Headers @{"Accept"="Application/xml"} -ErrorVariable restError -OutFile $xmlFile

					if ($?) {
						$blobsXml2 = [xml](Get-Content $xmlFile)
						$isUploading = $false
						foreach ($b in $blobsXml2.EnumerationResults.Blobs.Blob) {
							if ($b.Name -eq $blob.Name) {
								if ($b.Properties.Etag -ne $etag) {
									$isUploading = $true
									break
								}
							}
						}
						if ($isUploading) {
							continue
						}
					} else {
						Write-Host "Error: Get blob data of distro category $DistroCategory failed($($restError[0].Message))."
						continue
					}

					# for distros that specifies images match conditions
					if($imageMatchRegex) {
						# image name match with regex defined
						if($blob.Name -match $imageMatchRegex) {
							$vhdUrls += $srcUrl
						}
					} else {
						$vhdUrls += $srcUrl
					}
				}
			}
			if ($vhdUrls.Count -gt 0) {
				$vhdCount += $vhdUrls.Count
				Write-Host "Info: $vhdCount new VHD(s) found in distro category $DistroCategory in past $DetectInterval hours."
				$index = 1
				foreach ($vhdurl in $vhdUrls) {
				$output = @"

Info: Number # $index URL is $vhdurl
"@
					Write-Host $output
					$index++
				}
				$VhdNode = $VhdInfoXml.CreateElement("VHD")
				$root.AppendChild($VhdNode) | Out-Null
				$DistroCategoryNode = $VhdInfoXml.CreateElement("DistroCategory")
				$DistroCategoryNode.set_InnerXml($DistroCategory) | Out-Null
				$VhdNode.AppendChild($DistroCategoryNode) | Out-Null
				if ( $mailReceviers ) {
					$MailReceiversNode = $VhdInfoXml.CreateElement("MailReceivers")
					$MailReceiversNode.set_InnerXml($mailReceviers)
					$VhdNode.AppendChild($MailReceiversNode) | Out-Null
				}

				$UrlsNode = $VhdInfoXml.CreateElement("Urls")
				$VhdNode.AppendChild($UrlsNode) | Out-Null
				foreach ($vhdurl in $vhdUrls) {
					if(Validate-VHD -url $vhdurl) {
						$UrlNode = $VhdInfoXml.CreateElement("Url")
						$UrlNode.set_InnerXml($vhdUrl.Replace('&','&amp;'))
						$UrlsNode.AppendChild($UrlNode) | Out-Null
					}
				}

				$TestCategoryNode = $VhdInfoXml.CreateElement("TestCategory")
				$TestCategoryNode.set_InnerXml($TestCategory)
				$VhdNode.AppendChild($TestCategoryNode) | Out-Null

				if($logContainerSAS) {
					$LogContainerSASUrlNode = $VhdInfoXml.CreateElement("LogContainerSASUrl")
					$LogContainerSASUrlNode.set_InnerXml($logContainerSAS.Replace('&','&amp;'))
					$VhdNode.AppendChild($LogContainerSASUrlNode) | Out-Null
				}
			} else {
				Write-Host "Info: No new VHD found of distro category $DistroCategory in past $DetectInterval hours."
			}
		} else {
			Write-Host "Error: Get blob data failed($($restError[0].Message)) for distro category $DistroCategory."
		}
	}

	if ($vhdCount -gt 0) {
		$VhdInfoXml.Save($newVhdsFile)
	}
}

Function Validate-VHD {
	param(
		[string]$url= ""
	)
	$vhdName = "test_vhd_"+$(Get-Random)+".vhd"
	Write-Host "Info: Start to validate VHD $url."
	$azcopy_Path="C:\Program Files (x86)\Microsoft SDKs\Azure\AzCopy\AzCopy.exe"
	if( [System.IO.File]::Exists($azcopy_Path) ) {
		& $azcopy_Path /Source:$url /Dest:$pwd/$vhdName /V /NC:30 /Y
	} else {
		Write-Host "Error: Please install tool AzCopy."
		return $false
	}
	Test-VHD $pwd/$vhdName
	$returnVal = $?
	Remove-Item $pwd/$vhdName
	if($returnVal) {
		Write-Host "Info: Above VHD is a valid vhd."
		return $true
	} else {
		Write-Host "Warn: Above VHD is an invalid vhd."
		return $false
	}
}