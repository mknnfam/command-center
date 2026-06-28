#!/usr/bin/env python3
"""
Liquid Glass Command Center — HTTP Server
Tailscale-only access (no PIN). Serves liquid glass UI with WOL/sleep/credits APIs.

Usage:
    python3 server.py
    python3 server.py --port 8080
"""

import os
import sys
import json
import time
import sqlite3
import subprocess
import http.server
import urllib.parse
import urllib.request

DIR = os.path.dirname(os.path.abspath(__file__))

# ── Config ──────────────────────────────────────────────────
config = {}
config_path = os.path.join(DIR, "config.py")
if os.path.exists(config_path):
    with open(config_path) as f:
        exec(f.read(), config)

MAC          = config.get("MAC_ADDRESS", "18:C0:4D:CB:12:06")
HOST         = config.get("HOST", "0.0.0.0")
PORT         = config.get("PORT", 8080)
WIN_HOST     = config.get("WINDOWS_HOST", "192.168.1.100")
TAILSCALE_IP = config.get("TAILSCALE_IP", "")
TAILSCALE_HN = config.get("TAILSCALE_HOSTNAME", "")

# ── DeepSeek / Credits ──────────────────────────────────────
ENV_FILE     = "/opt/data/.env"
BALANCE_API  = "https://api.deepseek.com/user/balance"
DS_CHAT_API  = "https://api.deepseek.com/v1/chat/completions"
STELLA_DB    = "/opt/data/profiles/lawyer-profile/state.db"
CONQUEST_DB  = "/opt/data/state.db"
PRICING      = {"input_cache_hit": 0.0028, "input_cache_miss": 0.14, "output": 0.28}
CACHE_RATIO  = 0.5

_credits_cache = {"ts": 0}

def _load_ds_key():
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key and key != "***":
        return key
    try:
        with open(ENV_FILE, "rb") as f:
            for lb in f:
                if lb.startswith(b"DEEPSEEK_API_KEY"):
                    parts = lb.decode().strip().split("=", 1)
                    if len(parts) == 2 and parts[1] and parts[1] != "***":
                        return parts[1]
    except Exception:
        pass
    return ""

DEEPSEEK_KEY = _load_ds_key()


def get_balance():
    if not DEEPSEEK_KEY:
        return {"error": "DEEPSEEK_API_KEY not set"}
    try:
        req = urllib.request.Request(BALANCE_API, headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {DEEPSEEK_KEY}",
        })
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        infos = data.get("balance_infos", [])
        usd = next((i for i in infos if i.get("currency") == "USD"), {})
        return {
            "balance": float(usd.get("total_balance", 0)),
            "topped_up": float(usd.get("topped_up_balance", 0)),
            "granted": float(usd.get("granted_balance", 0)),
        }
    except Exception as e:
        return {"error": str(e)}


def get_stella_usage():
    """Query lawyer-profile (Stella) session DB for token usage."""
    return _query_profile_db(STELLA_DB)


def get_conquest_usage():
    """Query default profile (Conquest) session DB for token usage."""
    return _query_profile_db(CONQUEST_DB)


def _query_profile_db(db_path):
    """Shared logic to query a profile's session DB for token usage."""
    if not os.path.exists(db_path):
        return {"sessions": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "note": "no sessions yet"}
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT input_tokens, output_tokens FROM sessions")
        rows = cur.fetchall()
        conn.close()
        total_in = sum(r[0] or 0 for r in rows)
        total_out = sum(r[1] or 0 for r in rows)
        cache_miss = total_in * (1 - CACHE_RATIO)
        cache_hit = total_in * CACHE_RATIO
        cost = (
            (cache_hit / 1e6) * PRICING["input_cache_hit"] +
            (cache_miss / 1e6) * PRICING["input_cache_miss"] +
            (total_out / 1e6) * PRICING["output"]
        )
        return {"sessions": len(rows), "input_tokens": total_in, "output_tokens": total_out, "cost_usd": round(cost, 4)}
    except Exception as e:
        return {"sessions": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "error": str(e)}





# ── AI Lookup (Date Spot Agent) ────────────────────────────

_ai_headers = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Authorization": f"Bearer {DEEPSEEK_KEY}",
}

def ai_lookup(query):
    """Use DeepSeek to search for info about a date spot from a natural language query."""
    system_prompt = """You are a date spot research assistant for Kuala Lumpur, Malaysia.
Given a user's natural language query about a place, search your knowledge and return a JSON object with all fields you can fill.
Only fill fields you are confident about. Leave fields empty ('') if unsure.
Return ONLY valid JSON, no markdown, no explanation.

Fields to fill (all strings unless noted):
- name: Place name
- address: Full address
- area: KL area (e.g. Bukit Bintang, Damansara, Bangsar, KLCC, etc)
- category: Type (Cafe, Restaurant, Bar, Park, Museum, Shopping, Activity, Dessert, Other)
- price: 'Under RM50', 'RM50-100', 'RM100-200', 'RM200+'
- openingHours: e.g. 'Mon-Sun 10am-10pm'
- bestTime: e.g. 'Weekday mornings', 'Weekend evenings'
- effortLevel: 'Low', 'Medium', 'High'
- vibe: e.g. 'Romantic', 'Casual', 'Cozy', 'Lively'
- crowdLevel: 1-5 (number)
- privacyLevel: 1-5 (number)
- url: Google Maps or website URL if known
- status: 'Want to Go ⁉' (default), 'Visited ✅', 'Favourite ❤️'
- notes: Brief description
- lat: latitude (number or empty string)
- lng: longitude (number or empty string)"""
    
    try:
        payload = json.dumps({
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Find info about this place in Malaysia: {query}"}
            ],
            "temperature": 0.1,
            "max_tokens": 1000,
        })
        req = urllib.request.Request(DS_CHAT_API, data=payload.encode(), headers=_ai_headers, method="POST")
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read())
        content = result["choices"][0]["message"]["content"]
        # Strip markdown code fences if present
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
        return json.loads(content)
    except Exception as e:
        return {"error": str(e)}




def ping_host(host, count=1, timeout=2):
    try:
        r = subprocess.run(["ping", "-c", str(count), "-W", str(timeout), host],
                           capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def send_wol(mac):
    try:
        cleaned = mac.replace(":", "").replace("-", "").replace(".", "").upper()
        mb = bytes.fromhex(cleaned)
        packet = b"\xff" * 6 + mb * 16
        import socket as s
        with s.socket(s.AF_INET, s.SOCK_DGRAM) as sock:
            sock.setsockopt(s.SOL_SOCKET, s.SO_BROADCAST, 1)
            sock.sendto(packet, ("255.255.255.255", 9))
        return True, "WOL packet sent"
    except Exception as e:
        return False, str(e)


def try_sleep(host):
    try:
        r = subprocess.run(["shutdown", "/h", "/m", "\\\\" + host, "/t", "0"],
                           capture_output=True, text=True, timeout=10)
        return r.returncode == 0, r.stderr.strip() if r.returncode else "Hibernate command sent"
    except FileNotFoundError:
        return False, "shutdown not available in this environment"
    except Exception as e:
        return False, str(e)


_status_cache = {"awake": None, "ts": 0}


# ── HTTP Handler ────────────────────────────────────────────

class Handler(http.server.SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIR, **kwargs)

    def do_GET(self):
        p = urllib.parse.urlparse(self.path).path
        if p == "/api/status":    return self._status()
        if p == "/api/credits":   return self._credits()
        if p == "/api/config":    return self._config()
        if p in ("/", ""):        self.path = "/index.html"
        return super().do_GET()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        if p == "/api/wake":      return self._wake()
        if p == "/api/sleep":     return self._sleep()
        if p == "/api/ai-lookup": return self._ai_lookup()
        self._json({"error": "not found"}, 404)

    # ── API ──

    def _status(self):
        global _status_cache
        now = time.time()
        if _status_cache["ts"] > now - 15:
            awake = _status_cache["awake"]
        else:
            awake = ping_host(WIN_HOST)
            _status_cache = {"awake": awake, "ts": now}
        self._json({"awake": awake, "host": WIN_HOST, "mac": MAC,
                     "tailscale_ip": TAILSCALE_IP, "tailscale_hostname": TAILSCALE_HN,
                     "timestamp": now})

    def _credits(self):
        global _credits_cache
        now = time.time()
        if _credits_cache.get("ts", 0) > now - 30:
            return self._json(_credits_cache["data"])
        balance = get_balance()
        stella = get_stella_usage()
        conquest = get_conquest_usage()
        data = {"balance": balance, "stella": stella, "conquest": conquest, "timestamp": now}
        _credits_cache = {"ts": now, "data": data}
        self._json(data)

    def _config(self):
        self._json({"windows_host": WIN_HOST, "tailscale_ip": TAILSCALE_IP,
                     "tailscale_hostname": TAILSCALE_HN, "mac_configured": bool(MAC)})

    def _wake(self):
        ok, msg = send_wol(MAC)
        self._json({"success": ok, "message": msg})

    def _sleep(self):
        ok, msg = try_sleep(WIN_HOST)
        self._json({"success": ok, "message": msg})

    def _ai_lookup(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return self._json({"error": "empty body"}, 400)
        body = json.loads(self.rfile.read(length))
        query = (body.get("query") or "").strip()
        if not query:
            return self._json({"error": "missing 'query'"}, 400)
        result = ai_lookup(query)
        self._json(result)

    # ── Helpers ──

    def _json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, fmt, *args):
        pass  # quiet


# ── Main ────────────────────────────────────────────────────

def main():
    port = PORT
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv):
            port = int(sys.argv[idx + 1])

    server = http.server.HTTPServer((HOST, port), Handler)
    print(f"╔═══════════════════════════════════════════╗")
    print(f"║  Liquid Glass Command Center  :{port:<5}     ║")
    print(f"╠═══════════════════════════════════════════╣")
    print(f"║  Local:  http://localhost:{port:<5}         ║")
    if TAILSCALE_IP:
        print(f"║  VPN:    http://{TAILSCALE_IP}:{port:<5}      ║")
    print(f"║  MAC:    {MAC:<29}  ║")
    print(f"║  Target: {WIN_HOST:<29}  ║")
    print(f"╚═══════════════════════════════════════════╝")
    print("Tailscale-only · No PIN required")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
