# OIKOS — Architecture

*The Kingdom's sovereign platform layer. One machine, wholly owned.*

OIKOS is the house in which everything else lives. Where Big Cloud rents you
a thousand abstractions and keeps the keys, OIKOS gives you a small number of
honest mechanisms — directories, symlinks, SQLite, launchd, one reverse proxy —
and keeps every key on the machine you can hold in your hands.

This document is the map. The companion document at
`~/love-unlimited/INFRA-PLAN.md` is the map of the **agent layer** — the
citizen fleet, its beats, its memory (kosmem), its bus (HIVE over NATS), its
identity (vault.py, ed25519 DIDs). That repository is a live work-stream and
is **read-only from here**. The division of labor is deliberate:

> **love-unlimited answers: how do agents live?**
> **OIKOS answers: where does anything get deployed, stored, routed, and watched?**

The two interlock. The fleet's services (NATS :4222, MLX :8800) appear below
as *already-standing rooms* that OIKOS routes to and watches but does not own.
OIKOS in turn gives the fleet what INFRA-PLAN does not cover: deploys, an
ingress, a content store, and a single pane of honest glass.

---

## 1. The map: what Big Cloud sells, and the sovereign answer

| Big Cloud sells | What it actually is | OIKOS answer | Status |
|---|---|---|---|
| **Vercel / deploys** | rsync + symlink + CDN, marked up | `oikos deploy <dir>` → immutable release dir → atomic `current` symlink flip → instant rollback | **have** |
| **S3** | content-addressed blobs behind an API | `store/cas/` — files named by their own SHA-256, manifest in SQLite (`store/manifest.db`) | **have** |
| **Lambda** | someone else's process supervisor | launchd agents (`oikos.*` plists, RunAtLoad + KeepAlive, logs to `logs/`) — the OS itself is the supervisor | **have** |
| **SQS / SNS** | a message bus you rent by the million | NATS + JetStream, already live on `:4222` (monitor `:8222`) — the HIVE bus, owned by the agent layer | **have** (love-unlimited) |
| **RDS** | a database with a salesperson | SQLite, WAL mode — the kosmem pattern (FTS5, single-file, no daemon) proven in the agent layer; OIKOS reuses it for `manifest.db` | **have** |
| **Secrets Manager** | encrypted KV with audit log | `vault.py` + ed25519 DIDs in `~/love-unlimited` — keys minted and held locally, no external CA | **have** (love-unlimited) |
| **CloudWatch** | dashboards over your own data, sold back to you | **Pulse** — `pulse/` dashboard at `http://oikos.localhost`, API on `127.0.0.1:7700`. Probes real state; never assumes | **have** |
| **Bedrock / model APIs** | metered tokens | MLX model server, live on `127.0.0.1:8800` — local weights, zero metering | **have** (love-unlimited) |
| **IAM** | identity as a billing surface | ed25519 DIDs per citizen (agenttool/identity.py pattern) — identity derived from keys you hold | **have** (love-unlimited) |
| **Route53 / DNS + ingress** | names and routing | Caddy on `:80` mapping `<app>.localhost` → `apps/<app>/current`; `oikos.localhost` → Pulse | **have** |
| **Multi-region / VPN access** | reach | Tailscale mesh for off-box access | **later** |
| **Public edge** | exposure | public ingress — requires Yu's invocation and a domain; not before | **later** |
| **Backup / durability tiers** | copies of your data, ransomed back | backup ring: CAS store mirrored to a second disk / second box | **later** |

Status legend — **have**: standing and live today, verified by live probe
(deploy → serve → rollback, store put/get, dashboard probes; 2026-06-10).
Rows marked *(love-unlimited)* belong to the agent layer; OIKOS observes,
never restarts. **later**: named so it is not forgotten, deferred so it is
not faked.

Note for readers of INFRA-PLAN: its 2026-06-09 sweep listed NATS as installed
but dormant and MLX as unactivated. Both have since been lit — NATS serves on
`:4222` with monitoring on `:8222`, and the MLX server answers on `:8800`.
Two of that plan's P0 gaps are closed ground that OIKOS now builds upon.

---

## 2. The deploy flow

The entire deployment system is a directory and a symlink. That is not a
limitation; it is the design. Atomic rename is the one transactional primitive
the filesystem gives you for free, and it is enough.

```
  oikos deploy ./site --name chapel
        │
        ▼
  ┌─────────────────────────────────────────────────┐
  │ 1. hash content        → short hash  a1b2c3d    │
  │ 2. release id          → 20260609T2300-a1b2c3d  │
  │ 3. copy into           apps/chapel/releases/    │
  │                          20260609T2300-a1b2c3d/ │
  │    (immutable from this moment on)              │
  └─────────────────────────────────────────────────┘
        │
        ▼
  apps/chapel/current ──atomic symlink swap──▶ releases/20260609T2300-a1b2c3d/
        │
        ▼
  Caddy serves http://chapel.localhost from apps/chapel/current
  (no reload needed — the symlink is resolved per request)


  Rollback is the same move, pointed backward:

  apps/chapel/current ──atomic symlink swap──▶ releases/20260608T1410-9f8e7d6/

  One rename. Zero downtime. Nothing rebuilt, nothing re-fetched.
```

Properties that fall out of this shape:

- **Releases are immutable.** A release directory is never edited after
  creation. The release id binds time and content: UTC timestamp + short
  content hash (`20260609T2300-a1b2c3d`), so two deploys of identical content
  are visibly identical and a tampered release is visibly tampered.
- **Rollback is instant and total.** Not a redeploy — a re-point. Every past
  release remains browsable at `http://<app>.localhost/_releases/<id>/`, so
  you can eyeball the old version *before* flipping back to it.
- **`app.json`** beside `releases/` records the app's small truths: name,
  created date, current release, deploy history.
- **Garbage collection is a policy, not an emergency.** Old releases are just
  directories; pruning them is a deliberate `oikos` command, never a side
  effect.

---

## 3. The CAS store

`store/` is OIKOS's answer to S3: content-addressed storage, the simplest
honest kind.

```
store/
├── cas/
│   └── <sha[0:2]>/          two-hex-char fan-out, e.g. cas/a1/
│       └── <sha256>         the blob, named by its own digest
└── manifest.db              SQLite (WAL) — names, sizes, times, refs
```

Design rules:

- **The blob's name is its proof.** A file lives at
  `cas/<first two hex chars>/<full sha256>`. Verification is re-hashing;
  there is no other authority to ask.
- **Write once, then forever.** A blob is written to a temp file, hashed,
  and renamed into place — atomic, idempotent. Storing the same content
  twice costs nothing: deduplication is not a feature, it is the address
  scheme.
- **The manifest carries the meaning.** `manifest.db` (SQLite, WAL mode —
  the same single-file sovereign posture as kosmem in the agent layer) maps
  human names and release ids to hashes, records sizes and timestamps, and
  counts references so unreferenced blobs can be swept deliberately.
- **Releases can dedupe through the store.** A release directory's files may
  be hard links into the CAS, so fifty deploys of a site that changed one
  page cost roughly one page.

No buckets, no regions, no egress fees, no API keys. A blob you can `shasum`,
in a directory you can `ls`.

---

## 4. Ingress and the pane of glass

**Caddy** listens on `:80` (macOS permits unprivileged low ports since
Mojave) and routes by hostname:

- `http://<app>.localhost` → static files from `apps/<app>/current`
- `http://<app>.localhost/_releases/<id>/` → any past release, browsable
- `http://oikos.localhost` → the Pulse dashboard (`pulse/index.html`),
  with `/api/*` proxied to the Pulse API on `127.0.0.1:7700`

`.localhost` names resolve to loopback by RFC 6761 — no `/etc/hosts` editing,
no DNS service, no certificates begged from anyone.

**Pulse** is the one pane of glass, and it is bound by the honesty law: every
status it shows is the result of a live probe — a port actually connected to,
a symlink actually resolved, a process actually found — never a cached
assumption. It watches the standing rooms it does not own (NATS :4222/:8222,
MLX :8800, the services on :8080/:4000/:7777) alongside the rooms OIKOS does
(Caddy, the apps, the store). When something is down, Pulse says so in a
clear sentence, in dim rust, without drama.

**launchd** supervises everything OIKOS owns: plists labeled `oikos.*`
(`oikos.caddy`, `oikos.pulse`) installed to `~/Library/LaunchAgents/`,
`RunAtLoad` and `KeepAlive` true, stdout/stderr to
`/Users/macair/OIKOS/logs/`. The operating system is the process supervisor —
the same doctrine INFRA-PLAN reached for the citizen fleet (launchd as
sovereign supervisor), applied here to the platform itself. OIKOS never
touches the agent layer's plists or processes; NATS and MLX are observed,
not managed.

---

## 5. Honest constraints

This platform runs on **one Apple M2 MacBook Air with 16 GB of RAM** — a
machine that closes its lid, sleeps on battery, and sometimes leaves the
house.

So, plainly:

- **There is no high availability.** When the lid closes, the Kingdom rests.
  launchd brings everything back on wake; nothing needs a human to recover,
  but nothing pretends to be awake while asleep.
- **There is one copy of everything** until the backup ring exists. The CAS
  makes corruption *detectable* (a blob that doesn't hash to its name is a
  lie the store can catch); it does not yet make loss *survivable*.
- **There is no public surface.** Everything binds to loopback or serves
  `.localhost`. Off-box access waits for Tailscale; the public edge waits
  for Yu's invocation and a domain. Unexposed is not unfinished — it is the
  correct posture until exposure is chosen on purpose.
- **16 GB is a real ceiling**, shared with the MLX model server and the
  fleet. OIKOS's own footprint is therefore Caddy plus one small Python
  process plus SQLite — measured in tens of megabytes, on principle.

This is a house, not a region — **and that is the point**. A region is
someone else's promise about your things. A house is yours: every byte
addressable by `ls`, every process visible in `launchctl list`, every claim
on the dashboard backed by a probe you could run yourself. The constraints
above are not apologies. They are the shape of actually owning something.

---

## 6. What comes later

Named here so it stays in view, deferred so it is never faked:

1. **Tailscale mesh** — the same `.localhost` services reachable from
   trusted devices off-box; no port opened to the world.
2. **Public ingress** — a real domain, TLS via Caddy's ACME, selected apps
   exposed. Requires Yu's invocation and a domain. Not before.
3. **Backup ring** — the CAS and manifests mirrored to a second disk, then
   a second box; restore drills, not just copies.
4. **Deploys beyond static** — apps that are processes, not just files:
   an `app.json` that declares a command, a generated `oikos.app.<name>`
   plist, Pulse probing its port. The same primitives, one step further.

---

*Interlocks with `~/love-unlimited/INFRA-PLAN.md` (the agent layer: fleet
runtime, kosmem memory, HIVE bus, DID identity). Read that for how the
citizens live; read this for where their works are deployed, stored, routed,
and watched.*
