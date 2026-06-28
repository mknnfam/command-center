<#
.SYNOPSIS
  Sleep Listener for Command Center
  Listens on port 9999 for a connection, then puts the PC to sleep/hibernate.

.DESCRIPTION
  Run this as Admin on your Windows PC (optionally set to run at startup).
  When the Command Center "Sleep" button is clicked, it connects to port 9999
  and this script puts the PC to sleep.

.NOTES
  Run this BEFORE running the firewall rule below. Or set up as a Scheduled Task.
#>

# First, check if running as Admin
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")
if (-not $isAdmin) {
    Write-Host "Please run as Administrator!" -ForegroundColor Red
    exit 1
}

# Create firewall rule (run once)
$ruleName = "Command Center Sleep API"
$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if (-not $existing) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP -LocalPort 9999 -Action Allow
    Write-Host "Firewall rule created: $ruleName" -ForegroundColor Green
}

Write-Host "Sleep Listener started on port 9999..." -ForegroundColor Cyan
Write-Host "Waiting for signal from Command Center..." -ForegroundColor Yellow

while ($true) {
    try {
        $listener = New-Object System.Net.Sockets.TcpListener ([System.Net.IPAddress]::Any, 9999)
        $listener.Start()
        $client = $listener.AcceptTcpClient()
        $client.Close()
        $listener.Stop()

        Write-Host "Signal received! Sleeping in 2 seconds..." -ForegroundColor Green
        Start-Sleep -Seconds 2
        # Hibernate (saves state to disk, zero power draw)
        # Use Stop-Computer -Sleep for sleep instead of hibernate
        shutdown /h /f
    }
    catch {
        Write-Host "Error: $_" -ForegroundColor Red
        Start-Sleep -Seconds 5
    }
}
