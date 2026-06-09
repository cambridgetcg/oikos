#!/usr/bin/env python3
"""OIKOS Pulse — the control-plane API.

Serves JSON on 127.0.0.1:7700 for the dashboard at http://oikos.localhost.
Every number returned here is probed, counted, or read from disk at the
moment of asking (with a 5-second cache). Nothing is assumed.

Endpoints:
    /api/services    live probes of the house's services + launchd heartbeats
    /api/apps        deployed apps under /Users/macair/OIKOS/apps
    /api/fleet       read-only glance at the citizen fleet (~/love-unlimited)
    /api/cathedral   read-only counts from the YOUSPEAK cathedral

Also serves the static dashboard files from this directory, so the Pulse
works standalone while Caddy is being raised.
"""

import json
import os
import re
import socket
import subprocess
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen

HOST, PORT = "127.0.0.1", 7700

OIKOS = "/Users/macair/OIKOS"
PULSE_DIR = os.path.join(OIKOS, "pulse")
APPS_DIR = os.path.join(OIKOS, "apps")
LOVE = os.path.expanduser("~/love-unlimited")
FORGE = "/Users/macair/_forge"
YOUSPEAK = os.path.expanduser("~/YOUSPEAK")

PROBE_TIMEOUT = 0.25   # seconds — probes must never hang the API
CACHE_TTL = 5.0


# ---------------------------------------------------------------- probes

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def port_open(host, port, timeout=PROBE_TIMEOUT):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def tiny_http(host, port, path="/", host_header=None, timeout=PROBE_TIMEOUT):
    """Raw one-shot HTTP GET; returns the status code or None."""
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            s.settimeout(timeout)
            hh = host_header or "%s:%d" % (host, port)
            req = "GET %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n" % (path, hh)
            s.sendall(req.encode("ascii"))
            head = s.recv(256).decode("latin-1", "replace")
            m = re.match(r"HTTP/\d\.\d (\d{3})", head)
            return int(m.group(1)) if m else None
    except OSError:
        return None


def fetch_json(url, timeout=0.4):
    try:
        with urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def count_md(path, exclude_readme=True):
    """Count .md files directly inside path; None if unreadable."""
    try:
        names = os.listdir(path)
    except OSError:
        return None
    n = 0
    for name in names:
        if not name.endswith(".md"):
            continue
        if exclude_readme and name.lower() == "readme.md":
            continue
        if os.path.isfile(os.path.join(path, name)):
            n += 1
    return n


# ------------------------------------------------------------- endpoints

def api_services():
    services = []

    # caddy — ingress on :80
    up = port_open("127.0.0.1", 80)
    status = tiny_http("127.0.0.1", 80, host_header="oikos.localhost") if up else None
    detail = "answering on :80" + (" · http %d" % status if status else "") if up \
        else "nothing listening on :80"
    services.append({"name": "caddy", "role": "ingress", "addr": ":80",
                     "up": up, "detail": detail})

    # nats — the nerve, :4222, monitor on :8222
    up = port_open("127.0.0.1", 4222)
    if up:
        varz = fetch_json("http://127.0.0.1:8222/varz")
        if varz:
            detail = "%s connection%s · up %s" % (
                varz.get("connections", "?"),
                "" if varz.get("connections") == 1 else "s",
                varz.get("uptime", "?"))
        else:
            detail = "port answers; monitor on :8222 is quiet"
    else:
        detail = "nothing listening on :4222"
    services.append({"name": "nats", "role": "nerve", "addr": ":4222",
                     "up": up, "detail": detail})

    # mlx — the local mind on :8800
    up = port_open("127.0.0.1", 8800)
    status = tiny_http("127.0.0.1", 8800) if up else None
    detail = "answering on :8800" + (" · http %d" % status if status else "") if up \
        else "nothing listening on :8800"
    services.append({"name": "mlx", "role": "mind", "addr": "127.0.0.1:8800",
                     "up": up, "detail": detail})

    # pulse — this very API
    services.append({"name": "pulse", "role": "this dashboard",
                     "addr": "127.0.0.1:7700", "up": True,
                     "detail": "answering — you are reading it"})

    # launchd heartbeats of the kingdom
    heartbeats = []
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True,
                             text=True, timeout=2).stdout
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) != 3 or parts[2] == "Label":
                continue
            pid, code, label = parts
            if not re.search(r"oikos|love|true-love", label):
                continue
            if pid != "-":
                state = "running"
            elif code == "0":
                state = "idle"
            else:
                state = "exit %s" % code
            heartbeats.append({"label": label,
                               "pid": None if pid == "-" else int(pid),
                               "status": code, "state": state})
    except Exception:
        heartbeats = []
    heartbeats.sort(key=lambda h: (h["pid"] is None, h["label"]))

    return {"ok": True, "generated": now_iso(),
            "services": services, "heartbeats": heartbeats}


def api_apps():
    apps = []
    note = None
    if not os.path.isdir(APPS_DIR):
        note = "no apps directory yet — nothing has been deployed"
    else:
        for name in sorted(os.listdir(APPS_DIR)):
            d = os.path.join(APPS_DIR, name)
            if not os.path.isdir(d):
                continue
            entry = {"name": name, "url": "http://%s.localhost" % name,
                     "release": None, "releases": [], "meta": None}
            cur = os.path.join(d, "current")
            if os.path.islink(cur):
                entry["release"] = os.path.basename(os.readlink(cur))
            rels = os.path.join(d, "releases")
            if os.path.isdir(rels):
                entry["releases"] = sorted(os.listdir(rels))
            aj = os.path.join(d, "app.json")
            if os.path.isfile(aj):
                try:
                    with open(aj, encoding="utf-8") as f:
                        entry["meta"] = json.load(f)
                except (OSError, ValueError):
                    entry["meta"] = None
            apps.append(entry)
        if not apps:
            note = "the shelves are clean — nothing deployed yet"
    return {"ok": True, "generated": now_iso(), "apps": apps, "note": note}


def _clean(line):
    return re.sub(r"[*_]{1,3}", "", line).strip()


def _last_beat_entry(path):
    """Tolerates both beat shapes seen in the fleet:
    append-only month ledgers ('## 2026-06-09 14:39 — ...') and
    one-file-per-beat notes ('# title' at the top)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    dated = list(re.finditer(r"(?m)^## +(\d{4}-\d{2}-\d{2}.*)$", text))
    if dated:
        heading = dated[-1].group(1).strip()
        rest = text[dated[-1].end():]
    else:
        first = re.search(r"(?m)^#{1,3} +(.+)$", text)
        if first:
            heading = first.group(1).strip()
            rest = text[first.end():]
        elif text.strip():
            lines = text.strip().splitlines()
            heading = _clean(lines[0])
            rest = "\n".join(lines[1:])
        else:
            return None
    body = [_clean(l) for l in rest.splitlines()
            if l.strip() and not l.startswith("#") and l.strip() != "---"][:2]
    return {"heading": _clean(heading), "lines": body}


def api_fleet():
    citizens_dir = os.path.join(LOVE, "citizens")
    citizens = None
    try:
        citizens = sorted(n for n in os.listdir(citizens_dir)
                          if os.path.isdir(os.path.join(citizens_dir, n)))
    except OSError:
        citizens = None

    forge_count = None
    try:
        forge_count = sum(1 for n in os.listdir(FORGE)
                          if not n.startswith("_")
                          and os.path.isdir(os.path.join(FORGE, n)))
    except OSError:
        pass

    beats_today = None
    last_beat = None
    if citizens is not None:
        beats_today = 0
        month = time.strftime("%Y-%m")
        today = "## " + time.strftime("%Y-%m-%d")
        newest = (0, None, None)  # mtime, citizen, path
        for c in citizens:
            bdir = os.path.join(citizens_dir, c, "beats")
            try:
                files = os.listdir(bdir)
            except OSError:
                continue
            for fn in files:
                if not fn.endswith(".md"):
                    continue
                p = os.path.join(bdir, fn)
                try:
                    mt = os.path.getmtime(p)
                except OSError:
                    continue
                if mt > newest[0]:
                    newest = (mt, c, p)
                if fn == month + ".md":
                    try:
                        with open(p, encoding="utf-8", errors="replace") as f:
                            for line in f:
                                if line.startswith(today):
                                    beats_today += 1
                    except OSError:
                        pass
        if newest[2]:
            entry = _last_beat_entry(newest[2])
            if entry:
                name = newest[1]
                if name.startswith("citizen-"):
                    name = name[len("citizen-"):]
                when = time.strftime("%Y-%m-%d %H:%M", time.localtime(newest[0]))
                last_beat = {"citizen": name, "when": when, **entry}

    return {"ok": True, "generated": now_iso(),
            "citizens": len(citizens) if citizens is not None else "unknown",
            "forge_rows": forge_count if forge_count is not None else "unknown",
            "beats_today": beats_today if beats_today is not None else "unknown",
            "last_beat": last_beat,
            "source": citizens_dir if citizens is not None else "unreadable"}


def api_cathedral():
    canon = os.path.join(YOUSPEAK, "canon")
    counts = {
        "core": count_md(os.path.join(canon, "core")),
        "mathema": count_md(os.path.join(canon, "mathema")),
        "worship_action": count_md(os.path.join(canon, "worship-action")),
        "root": count_md(canon),
    }
    known = [v for v in counts.values() if isinstance(v, int)]
    total = sum(known) if known else None

    exp_dir = os.path.join(YOUSPEAK, "labs", "logos", "experiments", "core")
    experiments = count_md(exp_dir, exclude_readme=False)
    latest = []
    try:
        files = [(os.path.getmtime(os.path.join(exp_dir, n)), n)
                 for n in os.listdir(exp_dir) if n.endswith(".md")]
        latest = [n for _, n in sorted(files, reverse=True)[:3]]
    except OSError:
        pass

    liturgy = None
    try:
        liturgy = sum(1 for n in os.listdir(os.path.join(YOUSPEAK, "liturgy"))
                      if n.startswith("session-") and n.endswith(".md"))
    except OSError:
        pass

    def honest(v):
        return v if v is not None else "unknown"

    return {"ok": True, "generated": now_iso(),
            "canon": {k: honest(v) for k, v in counts.items()},
            "canon_total": honest(total),
            "experiments": honest(experiments),
            "liturgy_sessions": honest(liturgy),
            "latest_experiments": latest}


ENDPOINTS = {
    "/api/services": api_services,
    "/api/apps": api_apps,
    "/api/fleet": api_fleet,
    "/api/cathedral": api_cathedral,
}

_cache = {}
_cache_lock = threading.Lock()


def cached(key, fn):
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_TTL:
            return hit[1]
    value = fn()
    with _cache_lock:
        _cache[key] = (time.time(), value)
    return value


# --------------------------------------------------------------- server

STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".otf": "font/otf",
    ".woff2": "font/woff2",
    ".svg": "image/svg+xml",
    ".png": "image/png",
}


class PulseHandler(BaseHTTPRequestHandler):
    server_version = "oikos-pulse/1"

    def log_message(self, fmt, *args):  # keep the terminal quiet
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, payload):
        self._send(code, json.dumps(payload, indent=1).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ENDPOINTS:
            try:
                self._json(200, cached(path, ENDPOINTS[path]))
            except Exception as e:
                self._json(500, {"ok": False,
                                 "error": "the pulse stumbled answering %s: %s"
                                          % (path, e.__class__.__name__)})
            return
        if path.startswith("/api/"):
            self._json(404, {"ok": False,
                             "error": "no such endpoint; the pulse knows "
                                      "/api/services /api/apps /api/fleet /api/cathedral"})
            return
        self._static(path)

    def _static(self, path):
        if path == "/":
            path = "/index.html"
        full = os.path.realpath(os.path.join(PULSE_DIR, path.lstrip("/")))
        if not full.startswith(os.path.realpath(PULSE_DIR) + os.sep):
            self._send(403, b"outside the house\n", "text/plain; charset=utf-8")
            return
        if not os.path.isfile(full) or full.endswith(".py"):
            self._send(404, b"not here\n", "text/plain; charset=utf-8")
            return
        ctype = STATIC_TYPES.get(os.path.splitext(full)[1],
                                 "application/octet-stream")
        with open(full, "rb") as f:
            self._send(200, f.read(), ctype)


def main():
    server = ThreadingHTTPServer((HOST, PORT), PulseHandler)
    print("oikos pulse — listening on http://%s:%d  (probes live, cache %ds)"
          % (HOST, PORT, int(CACHE_TTL)))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\noikos pulse — resting")


if __name__ == "__main__":
    main()
