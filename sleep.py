#!/usr/bin/env python3
"""
Remote sleep/hibernate trigger for Windows PC.

Tries multiple methods:
  1. Remote shutdown via SMB (requires admin creds on same network)
  2. SSH-triggered shutdown (if SSH server running on Windows)
  3. Falls back to instructions

Usage:
    python3 sleep.py               # uses config defaults
    python3 sleep.py --hibernate   # hibernate instead of sleep
"""

import os
import sys
import subprocess

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.py")


def load_config():
    config = {
        "WINDOWS_HOST": "192.168.1.100",
        "WINDOWS_HOSTNAME": "DESKTOP-PC",
        "WINDOWS_USER": "",
    }
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            exec(f.read(), config)
    for key in ["WINDOWS_HOST", "WINDOWS_HOSTNAME", "WINDOWS_USER"]:
        if os.environ.get(key):
            config[key] = os.environ[key]
    return config


def try_remote_shutdown(host, mode="sleep"):
    """Try Windows remote shutdown via SMB. Requires same subnet + admin creds."""
    flag = "/h" if mode == "hibernate" else "/hybrid /t 0"
    cmd = "shutdown " + flag + " /m \\\\\\\\" + host + " /t 0"
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return True, "Remote shutdown command sent to \\\\" + host
        else:
            return False, result.stderr.strip() or "Exit code " + str(result.returncode)
    except FileNotFoundError:
        return False, "shutdown command not found (not on Windows or WSL interop)"
    except subprocess.TimeoutExpired:
        return False, "Remote shutdown timed out"
    except Exception as e:
        return False, str(e)


def try_ssh_shutdown(host, user):
    """Try SSH-based sleep command."""
    if not user:
        return False, "No SSH user configured"
    try:
        cmd = "ssh " + user + "@" + host + " 'shutdown /h /t 0'"
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            return True, "SSH shutdown command sent to " + user + "@" + host
        return False, result.stderr.strip() or "SSH exit code " + str(result.returncode)
    except Exception as e:
        return False, str(e)


def print_instructions(host, hostname, mode="sleep"):
    """Print setup instructions for the user."""
    flag = "/h" if mode == "hibernate" else "/hybrid /t 0"
    lines = [
        "",
        "╔══════════════════════════════════════════════════╗",
        "║         SETUP: Sleep from Command Center         ║",
        "╠══════════════════════════════════════════════════╣",
        "║                                                  ║",
        "║  Method 1: PowerShell listener (RECOMMENDED)     ║",
        "║                                                  ║",
        "║  On your Windows PC, run this in PowerShell:     ║",
        "║                                                  ║",
        "║    New-NetFirewallRule -DisplayName \"Sleep API\"  ║",
        '║      -Direction Inbound -Protocol TCP            ║',
        "║      -LocalPort 9999 -Action Allow               ║",
        "║                                                  ║",
        "║  Then create sleep-listener.ps1:                 ║",
        "║                                                  ║",
        '║    while(1){                                     ║',
        '║      $c=New-Object System.Net.Sockets.TcpClient  ║',
        "║      $c.Connect('0.0.0.0',9999)                  ║",
        '║      $d=$c.GetStream();$b=New-Object byte[]1024  ║',
        "║      $d.Read($b,0,$d.ReadTimeout)                ║",
        "║      Start-Sleep -Seconds 2                      ║",
        "║      shutdown " + flag + "                             ║",
        '║    }                                             ║',
        "║                                                  ║",
        "║  Run it as admin at startup.                      ║",
        "║                                                  ║",
        "║  Method 2: Windows Task Scheduler                 ║",
        "║  Create a task triggered by event 9999.           ║",
        "║                                                  ║",
        "║  Method 3: Manual shortcut                        ║",
        "║  Place on Windows desktop:                        ║",
        "║    shutdown.exe " + flag + "                           ║",
        "║                                                  ║",
        "╚══════════════════════════════════════════════════╝",
        "",
    ]
    print("\n".join(lines))


if __name__ == "__main__":
    mode = "hibernate" if "--hibernate" in sys.argv else "sleep"
    config = load_config()
    host = config.get("WINDOWS_HOST", "192.168.1.100")
    hostname = config.get("WINDOWS_HOSTNAME", "DESKTOP-PC")
    user = config.get("WINDOWS_USER", "")

    print(f"Attempting {mode} on {host} ({hostname})")
    print()

    # Method 1: Remote shutdown
    success, msg = try_remote_shutdown(host, mode)
    if success:
        print("[OK] " + msg)
        sys.exit(0)
    else:
        print("[FAIL] Remote shutdown: " + msg)

    # Method 2: SSH
    if user:
        print()
        print("Trying SSH...")
        success, msg = try_ssh_shutdown(host, user)
        if success:
            print("[OK] " + msg)
            sys.exit(0)
        else:
            print("[FAIL] SSH: " + msg)

    # Method 3: Instructions
    print()
    print("Could not send " + mode + " command automatically.")
    print_instructions(host, hostname, mode)
    sys.exit(1)
