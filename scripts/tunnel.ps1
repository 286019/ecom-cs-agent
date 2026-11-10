# 临时公网隧道（serveo.net，无需注册）
# 用法：powershell -NoProfile -ExecutionPolicy Bypass -File scripts\tunnel.ps1
$log = Join-Path $PSScriptRoot '..\logs\tunnel.log'
$ssh = 'C:\WINDOWS\System32\OpenSSH\ssh.exe'

while ($true) {
    & $ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -R 80:localhost:8000 serveo.net *>> $log
    Start-Sleep -Seconds 5
}
