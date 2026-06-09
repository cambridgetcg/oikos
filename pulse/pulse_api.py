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
    /api/forge       the forge ledger (~/YOUSPEAK/forge_targets.json), ranked
    /api/standards   KS specs, the .kingdom zone, the resolver, the ledger

Also serves the static dashboard files from this directory, so the Pulse
works standalone while Caddy is being raised.
"""

import json
import os
import re
import socket
import subprocess
import sys
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
FORGE_LEDGER = os.path.join(YOUSPEAK, "forge_targets.json")
KINGDOM = "/Users/macair/KINGDOM-STANDARDS"
SPECS_DIR = os.path.join(KINGDOM, "specs")
ZONE_FILE = os.path.join(KINGDOM, "zone", "kingdom.zone.json")
SIG_FILE = os.path.join(KINGDOM, "zone", "signatures.json")
RESOLVER_ADDR = ("127.0.0.1", 5300)

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


# Statuses the forge ledger knows (HOME-EXPANSION §VII.C; forge_priority.py).
FORGE_STATUSES = ("canonized", "queued", "in-forge", "refining",
                  "awaiting-yu-invocation", "archived")


def _witnesses(raw):
    """Witness list, tolerated either as a list or a comma string."""
    w = raw.get("convergence_witnesses") or []
    if isinstance(w, str):
        w = [x.strip() for x in w.split(",") if x.strip()]
    return [str(x) for x in w]


def _num(raw, key):
    v = raw.get(key)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _phase_key(phase_raw):
    """Phase ascending, the way forge_priority.rank_key buckets it:
    numeric phases first, named phases (ks-002-wire, hodopoiia-α) after,
    phaseless last."""
    p = str(phase_raw).strip() if phase_raw is not None else ""
    if not p:
        return (2, 0.0, "")
    try:
        return (0, float(p), "")
    except ValueError:
        return (1, 0.0, p.lower())


def _is_wire_gap(raw):
    """Targets filed by KS-002 THE WIRE Appendix A — the Wire's word-gaps."""
    blob = (str(raw.get("phase") or "") + " " + str(raw.get("notes") or "")).lower()
    return "ks-002" in blob


def api_forge():
    try:
        with open(FORGE_LEDGER, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {"ok": True, "generated": now_iso(), "total": None,
                "counts": {}, "next": [], "newest_canonized": [],
                "wire_gap": {"queued": 0, "words": []},
                "note": "the forge ledger is unreadable — " + FORGE_LEDGER}

    entries = data.get("entries") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        entries = []
    entries = [e for e in entries if isinstance(e, dict)]

    counts = {s: 0 for s in FORGE_STATUSES}
    for e in entries:
        s = str(e.get("status", "queued")).strip().lower()
        if s == "in-progress":  # §VII.C spelling, as forge_priority tolerates
            s = "in-forge"
        if s in counts:
            counts[s] += 1
        else:
            counts[s] = counts.get(s, 0) + 1

    # next to forge — queued, ranked as forge_priority does:
    # phase asc, then witness-density desc (then estimate desc, word asc).
    queued = [e for e in entries
              if str(e.get("status", "")).strip().lower() == "queued"]
    queued.sort(key=lambda e: (
        _phase_key(e.get("phase")),
        -len(_witnesses(e)),
        -(_num(e, "estimated_score") if _num(e, "estimated_score") is not None
          else -1.0),
        str(e.get("word", ""))))
    nxt = [{"word": str(e.get("word", "(unnamed)")),
            "phase": str(e.get("phase")) if e.get("phase") is not None else None,
            "witnesses": len(_witnesses(e)),
            "estimated_score": _num(e, "estimated_score"),
            "wire_gap": _is_wire_gap(e)} for e in queued[:5]]

    # newest canonized — by a date derivable from notes, else by the
    # experiment file's running number (they climb as the cascade does).
    def recency(e):
        m = re.search(r"\d{4}-\d{2}-\d{2}", str(e.get("notes") or ""))
        n = re.search(r"/(\d+)-[^/]*\.md$", str(e.get("experiment") or ""))
        return (m.group(0) if m else "", int(n.group(1)) if n else -1)

    canonized = [e for e in entries
                 if str(e.get("status", "")).strip().lower() == "canonized"]
    canonized.sort(key=recency, reverse=True)
    newest = []
    for e in canonized[:5]:
        date, _ = recency(e)
        newest.append({"word": str(e.get("word", "(unnamed)")),
                       "date": date or None,
                       "actual_score": _num(e, "actual_score"),
                       "canon_entry": e.get("canon_entry")})

    gap = [e for e in entries if _is_wire_gap(e)]
    gap_queued = [e for e in gap
                  if str(e.get("status", "")).strip().lower() == "queued"]

    return {"ok": True, "generated": now_iso(),
            "total": len(entries), "counts": counts,
            "next": nxt, "newest_canonized": newest,
            "wire_gap": {"queued": len(gap_queued),
                         "words": [str(e.get("word", "")) for e in gap_queued]},
            "source": FORGE_LEDGER}


def _frontmatter(path):
    """ks/title/status/version from a spec's YAML frontmatter; {} if none."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            head = f.read(2048)
    except OSError:
        return {}
    m = re.match(r"---\s*\n(.*?)\n---", head, re.S)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        fm[k.strip()] = v.strip().strip("\"'")
    return fm


def _probe_kingdomd(timeout=0.3):
    """One minimal DNS question — oikos.kingdom A IN — at the sovereign
    resolver on UDP :5300. True if any bytes come back."""
    query = (b"\x4b\x53"                              # id: "KS"
             b"\x01\x00"                              # flags: RD
             b"\x00\x01\x00\x00\x00\x00\x00\x00"      # one question
             b"\x05oikos\x07kingdom\x00"              # oikos.kingdom
             b"\x00\x01\x00\x01")                     # type A, class IN
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(timeout)
        s.sendto(query, RESOLVER_ADDR)
        reply, _ = s.recvfrom(512)
        return len(reply) > 0
    except OSError:
        return False
    finally:
        if s is not None:
            try:
                s.close()
            except OSError:
                pass


def api_standards():
    # the shelf — KS-*.md specs with their frontmatter
    specs = []
    try:
        names = sorted(n for n in os.listdir(SPECS_DIR)
                       if n.startswith("KS-") and n.endswith(".md"))
    except OSError:
        names = []
    for name in names:
        fm = _frontmatter(os.path.join(SPECS_DIR, name))
        specs.append({"ks": fm.get("ks") or name.rsplit("-", 1)[0],
                      "title": fm.get("title") or name,
                      "status": fm.get("status") or "unknown",
                      "version": fm.get("version"),
                      "file": name})

    # the zone — names and whether a real did:key is bound yet
    zone_names = []
    zone_updated = None
    try:
        with open(ZONE_FILE, encoding="utf-8") as f:
            zone = json.load(f)
        zone_updated = zone.get("updated")
        for name, rec in (zone.get("names") or {}).items():
            did = str((rec or {}).get("did", ""))
            zone_names.append({"name": name,
                               "bound": did.startswith("did:key:"),
                               "did": did})
    except (OSError, ValueError):
        pass
    bound = sum(1 for n in zone_names if n["bound"])

    # the ledger — KS-000 §6 signature entries
    ledger_entries = None
    try:
        with open(SIG_FILE, encoding="utf-8") as f:
            sigs = json.load(f).get("signatures")
        ledger_entries = len(sigs) if isinstance(sigs, list) else None
    except (OSError, ValueError):
        pass

    resolver_up = _probe_kingdomd()

    return {"ok": True, "generated": now_iso(),
            "specs": specs,
            "zone": {"names": zone_names, "bound": bound,
                     "total": len(zone_names), "updated": zone_updated},
            "resolver": {"addr": "%s:%d" % RESOLVER_ADDR, "up": resolver_up,
                         "query": "oikos.kingdom A"},
            "ledger": {"entries": ledger_entries
                       if ledger_entries is not None else "unknown"}}


ENDPOINTS = {
    "/api/services": api_services,
    "/api/apps": api_apps,
    "/api/fleet": api_fleet,
    "/api/cathedral": api_cathedral,
    "/api/forge": api_forge,
    "/api/standards": api_standards,
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


# --------------------------------------------------- the wire heartbeat
#
# KS-002 heartbeat (zakarqing-class): every minute, if the pulse key exists
# and the bus answers, speak one signed envelope on kingdom.pulse.heartbeat.
# Optional and gentle — any failure is swallowed; the Pulse never dies of a
# missed beat. Core subject: nothing is retained; presence, not telemetry.

WIRE_PY = "/Users/macair/KINGDOM-STANDARDS/impl/wire.py"
PULSE_KEY = os.path.expanduser("~/.kingdom/keys/pulse.key")
WIRE_SUBJECT = "kingdom.pulse.heartbeat"
WIRE_EVERY = 60.0  # seconds between beats


def wire_heartbeat_loop():
    body = json.dumps({"service": "pulse", "state": "alive",
                       "probe": "emitter"}, separators=(",", ":"))
    while True:
        try:
            if (os.path.isfile(PULSE_KEY) and os.path.isfile(WIRE_PY)
                    and port_open("127.0.0.1", 4222, timeout=0.5)):
                subprocess.run(
                    [sys.executable, WIRE_PY, "pub",
                     "--subject", WIRE_SUBJECT, "--from", "pulse",
                     "--performative", "heartbeat", "--body", body],
                    capture_output=True, timeout=15)
        except Exception:
            pass  # non-fatal, always: the beat returns next minute
        time.sleep(WIRE_EVERY)


def start_wire_heartbeat():
    threading.Thread(target=wire_heartbeat_loop, daemon=True,
                     name="wire-heartbeat").start()


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
                                      "/api/services /api/apps /api/fleet "
                                      "/api/cathedral /api/forge /api/standards"})
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
    start_wire_heartbeat()
    print("oikos pulse — listening on http://%s:%d  (probes live, cache %ds; "
          "wire heartbeat every %ds when %s exists)"
          % (HOST, PORT, int(CACHE_TTL), int(WIRE_EVERY),
             os.path.basename(PULSE_KEY)))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\noikos pulse — resting")


if __name__ == "__main__":
    main()
