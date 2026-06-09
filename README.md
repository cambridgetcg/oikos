# OIKOS

*The Kingdom's own house.*

**Oikos** — οἶκος — the household: the root of *oikonomia*, which the world
shortened to "economy" and forgot. Before economy meant markets, it meant
the right ordering of a house. OIKOS is that, for software: the sovereign
platform layer where the Kingdom's works are deployed, stored, routed, and
watched — on one machine, wholly owned, with no landlord between intention
and execution.

It does what Vercel and AWS sell, with the parts they hide: directories,
symlinks, SQLite, launchd, and one reverse proxy. Nothing here is rented.

## Quickstart

```sh
oikos deploy ./site --name chapel
open http://chapel.localhost
```

A deploy becomes an immutable release directory; an atomic symlink flip makes
it live; rollback is the same flip, pointed backward. The whole estate is
visible at [http://oikos.localhost](http://oikos.localhost) — the Pulse
dashboard, where every status shown is a live probe, never an assumption.

## The taste law

Every surface of OIKOS — CLI output, dashboard, these documents — is held to
the same standard: **beautiful and restrained**. Warm stone and parchment,
gold for names, rust for warnings, aligned columns, clear sentences. No
gradients, no spinners, no noise. And its twin, the honesty law: status is
probed, errors are sentences, and nothing on a screen claims more than the
machine can prove.

## Going deeper

The full map — what Big Cloud sells against the sovereign answer, the deploy
flow, the content-addressed store, the honest constraints of a house that is
not a region — lives in [ARCHITECTURE.md](ARCHITECTURE.md). The agent fleet
that lives *inside* this house is charted separately in
`~/love-unlimited/INFRA-PLAN.md`.

## Inaugural tenants

The first works in the house, deployed 2026-06-09:
[demo](http://demo.localhost) at http://demo.localhost, and the cathedral
itself — the YOUSPEAK canon — at http://cathedral.localhost. Each is a
point-in-time snapshot; `oikos deploy` again to refresh.

— built 2026-06-09
