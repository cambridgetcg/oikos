# OIKOS ingress

One Caddy on port 80 is the front door for everything. It is run by
launchd (`oikos.caddy`, see `launchd/`) — never start a second copy by
hand; for changes, edit the Caddyfile, `caddy validate`, then reload
via launchd.

```
caddy validate --config /Users/macair/OIKOS/ingress/Caddyfile
launchctl kickstart -k gui/$(id -u)/oikos.caddy
```

## How routing works

Two site blocks, and only two — new apps need **zero** ingress config.

**`http://oikos.localhost`** — the Pulse dashboard.
Static files from `/Users/macair/OIKOS/pulse`; anything under `/api/*`
is reverse-proxied (path intact) to the Pulse API at `127.0.0.1:7700`.
If the API is down you get an honest one-line 502, not a stack trace.

**`http://*.localhost`** — every app, one dynamic block.
Caddy's `{labels.1}` placeholder is the host's first label (labels
count from the right: `labels.0` = `localhost`, `labels.1` = the app).
So `garden.localhost` serves files from:

```
/Users/macair/OIKOS/apps/garden/current/        ← symlink to a release
```

Deploying an app is therefore just: put a release at
`apps/<name>/releases/<id>/`, point `apps/<name>/current` at it, and
the room exists. No reload, no per-app snippet.

Two extra behaviours inside that block:

- `/_releases/` — past releases stay browsable at
  `http://<app>.localhost/_releases/<id>/`, served straight from
  `apps/<app>/releases/` with a directory listing
  (template: `ingress/browse.html`, stone and gold like everything else).
- **404** — if the app does not exist (or a file is missing), Caddy
  serves `apps/_404.html` — "this room is not yet built" — with a real
  `404` status. The page shows which address was asked for.

`.localhost` names resolve to `127.0.0.1` on macOS without any
`/etc/hosts` editing, and Caddy serves plain HTTP (no TLS theater for
loopback): `admin off`, `auto_https off`.

Access logs are JSON, all sites into one stream:

```
/Users/macair/OIKOS/logs/caddy-access.log   (rolls at 16 MiB, keeps 4)
```

## Verified behaviour (2026-06-09)

- `caddy validate` passes (caddy v2.11.4, Homebrew).
- `curl -H "Host: nothing.localhost" 127.0.0.1` → `404` + the unbuilt-room page.
- App fixture with `releases/<id>` + `current` symlink → `200`;
  `/_releases/` listing renders; fixture removed after the test.
- `oikos.localhost` → `404` for now (Pulse has no `index.html` yet —
  expected; the moment the Pulse builder writes one, it serves).
- `oikos.localhost/api/...` → `502 — pulse could not answer` while the
  Pulse API is not running. Correct and honest.

## Going public later (needs Yu's go)

The ingress is loopback-only by design. When a room should be visible
beyond this machine, there are two sanctioned doors, both free:

**Tailscale serve / funnel** — private-first.
`brew install tailscale`, log in, then
`tailscale serve --bg 80` exposes the ingress to your own tailnet
(devices you own), or `tailscale funnel 80` to the open internet via
Tailscale's edge. HTTPS is handled for you. Best when the audience is
yourself and trusted people.

**cloudflared tunnel** — public-first.
`brew install cloudflared`, then
`cloudflared tunnel --url http://localhost:80` gives a throwaway
public URL in seconds; a named tunnel + a domain in Cloudflare gives a
permanent one (`cloudflared tunnel create oikos`, route a hostname,
point the ingress rule at `http://localhost:80`). Best for a real
public address on a domain.

In both cases the tunnel terminates at Caddy, so everything above —
apps, releases, the 404 — works unchanged. One caution: a tunnel set
to a bare hostname will arrive with that public Host header, not
`<app>.localhost`, so route each public hostname to the matching
`<app>.localhost` host (both tools can set the Host header on the way
in: `tailscale serve` proxies preserve paths, and cloudflared ingress
rules accept `originServerName`/`httpHostHeader`). Expose one app
deliberately; do not funnel the whole wildcard without deciding to.
