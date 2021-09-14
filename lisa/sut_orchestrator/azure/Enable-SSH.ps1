# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
Param
(
    [String] $PublicKey = ""
)

# enable OpenSSH server on Windows a Windows machine. Refer to document for
# detail steps.

# install server package and enable firewall
Add-WindowsCapability -Online -Name OpenSSH.Server
New-NetFirewallRule -Name sshd -DisplayName 'OpenSSH Server' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 -Program "%WINDIR%\System32\OpenSSH\sshd.exe"

# Set sshd service from manual to automatic starts
Set-Service -Name sshd -StartupType Automatic

# copy public key file to administrators key file.
$PublicKey | Out-File C:\ProgramData\ssh\administrators_authorized_keys -Encoding "utf8"

# Set permission of 
$acl = Get-Acl C:\ProgramData\ssh\administrators_authorized_keys
$acl.SetAccessRuleProtection($true, $false)
$administratorsRule = New-Object system.security.accesscontrol.filesystemaccessrule("Administrators", "FullControl", "Allow")
$systemRule = New-Object system.security.accesscontrol.filesystemaccessrule("SYSTEM", "FullControl", "Allow")
$acl.SetAccessRule($administratorsRule)
$acl.SetAccessRule($systemRule)
$acl | Set-Acl

# start service to create sshd_config file.
Start-Service sshd

# enable key authentication and restart for effective.
$sshd_config = "C:\ProgramData\ssh\sshd_config" 
(Get-Content $sshd_config) -replace '#PubkeyAuthentication', 'PubkeyAuthentication' | Out-File -encoding ASCII $sshd_config
Restart-Service sshd
