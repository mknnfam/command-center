#!/usr/bin/env python3
"""
Wake-on-LAN magic packet sender.
Sends a magic packet (6 bytes of 0xFF + MAC repeated 16x) via UDP broadcast.

Usage:
    python3 wol.py                      # uses MAC from config.py
    python3 wol.py <MAC_ADDRESS>        # override MAC on command line
"""

import socket
import sys
import os

# Default MAC — edit this or set MAC_ADDRESS env var
DEFAULT_MAC = os.environ.get("MAC_ADDRESS", "")


def validate_mac(mac: str) -> str:
    """Normalise and validate a MAC address."""
    cleaned = mac.replace(":", "").replace("-", "").replace(".", "").upper()
    if len(cleaned) != 12:
        raise ValueError(
            f"Invalid MAC '{mac}' — expected 12 hex digits after stripping separators, got {len(cleaned)}"
        )
    try:
        int(cleaned, 16)
    except ValueError:
        raise ValueError(f"Invalid MAC '{mac}' — non-hex characters")
    return cleaned


def send_wol(mac: str, broadcast: str = "255.255.255.255", port: int = 9):
    """
    Send WOL magic packet.

    Args:
        mac: MAC address in any common format (00:11:22:AA:BB:CC, 00-11-22-AA-BB-CC, 001122AABBCC)
        broadcast: Broadcast IP (default 255.255.255.255, use subnet broadcast for routed networks)
        port: Destination port (7=echo, 9=discard, default 9)
    """
    cleaned_mac = validate_mac(mac)
    mac_bytes = bytes.fromhex(cleaned_mac)

    # Magic packet: 6 bytes of 0xFF + MAC repeated 16 times
    magic_packet = b"\xff" * 6 + mac_bytes * 16

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(magic_packet, (broadcast, port))

    print(f"✅ WOL packet sent to {cleaned_mac} via {broadcast}:{port}")


def get_broadcast_address() -> str:
    """Try to detect the subnet broadcast address, fall back to global broadcast."""
    try:
        import subprocess
        result = subprocess.run(
            ["ip", "route"], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            parts = line.split()
            if "default" in parts:
                continue
            if len(parts) >= 3 and parts[0].count(".") == 3:
                # Found a route like: 172.17.0.0/16 dev eth0 proto kernel scope link src 172.17.0.2
                # The broadcast is usually the subnet broadcast
                return parts[0].rsplit(".", 1)[0] + ".255"
    except Exception:
        pass
    return "255.255.255.255"


if __name__ == "__main__":
    mac = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MAC

    if not mac:
        print("Usage: python3 wol.py <MAC_ADDRESS>")
        print("   or: export MAC_ADDRESS=00:11:22:AA:BB:CC && python3 wol.py")
        sys.exit(1)

    broadcast = get_broadcast_address()
    print(f"🌐 Broadcast target: {broadcast}")
    send_wol(mac, broadcast=broadcast)
    print("💤 PC should wake within a few seconds (if WOL is enabled in BIOS/NIC)")
