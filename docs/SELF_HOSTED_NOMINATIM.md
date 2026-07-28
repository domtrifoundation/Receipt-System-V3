# Self-Hosted Nominatim Setup Guide

This guide covers standing up a self-hosted Nominatim instance to use as a `GeoProvider` in Geo/Address API's own Provider Registry (`v3-deepdive-16-geo-address-api.md` §3) — the unlimited-throughput option for a fully cloud-independent self-hosted install, or once the free-tier providers' (LocationIQ, Mapbox) rate limits become a real bottleneck at scale.

**Not required for a normal install.** LocationIQ + Mapbox are the enabled-by-default providers and cover this project's expected scale on their own free tiers. This guide is for an operator who specifically wants this option — surfaced in the TUI's own Geo/Address settings entry, linked from there rather than duplicated in-app.

---

## 1. Choosing a VPS

**Oracle Cloud's Always Free tier is the reference recommendation** — specifically the ARM-based Ampere A1 shape, which at the Always Free allocation (4 OCPUs, 24GB RAM) is genuinely enough for a country-sized OSM extract import and ongoing serving, at zero recurring cost. Any VPS with comparable specs works identically — Nominatim itself has no cloud-provider dependency; Oracle's free tier is just the best-value option for this specific workload as of this writing.

**Why RAM matters more than CPU here**: Nominatim's import process is memory-hungry (PostgreSQL's own working set during indexing), and running out of RAM mid-import is the single most common failure mode for a first-time setup — 24GB comfortably covers a full Philippines extract; a smaller instance (8GB or less) risks the import stalling or OOM-killing partway through, especially on the `IMPORT_STYLE=full` setting this project uses (§3 below).

---

## 2. Installing Docker
Standard Docker Engine install for your VPS's own OS (Ubuntu is the common Oracle Cloud default) — `curl -fsSL https://get.docker.com | sh` remains the standard bootstrap, followed by adding your user to the `docker` group so you don't need `sudo` for every command.

---

## 3. Running the import

**`mediagis/nominatim` is the current, de-facto, actively-maintained community Docker image** — confirmed as the standard choice, not assumed from memory. It bundles PostgreSQL + PostGIS + Nominatim + the full import pipeline behind one container, with sane defaults.

```bash
docker run -it \
  -e PBF_URL=https://download.geofabrik.de/asia/philippines-latest.osm.pbf \
  -e IMPORT_STYLE=full \
  -e THREADS=4 \
  -v nominatim-data:/var/lib/postgresql/16/main \
  -p 8080:8080 \
  --name nominatim \
  --restart unless-stopped \
  mediagis/nominatim:5.3
```
- **`PBF_URL`** points at Geofabrik's own Philippines-specific extract — a PH-only import, not the full planet, keeping both import time and ongoing storage genuinely small.
- **`IMPORT_STYLE=full`** is what you want — `admin` (a smaller style, boundaries only) is not useful for this project's actual receipt-address-lookup use case.
- **`THREADS=4`** matches the Ampere A1's 4-OCPU allocation from §1 — a safe default for that instance size; more threads means a faster but more contended import.
- **`-v nominatim-data:...`** persists the imported database in a named volume — without this, a container restart would mean re-running the entire import from scratch.
- This step takes hours, not minutes, for a country-sized extract. Watch the logs — real phases you'll see: `Downloading...`, `Importing...`, `Indexing...`, `Updating word counts...`. A healthy server listening on port 8080 is the completion signal.

---

## 4. Verifying it works
```bash
curl "http://localhost:8080/search?q=Ayala+Avenue+Makati&format=json"
curl "http://localhost:8080/reverse?lat=14.5547&lon=121.0244&format=json"
```
Both should return real, structured JSON results — a forward lookup for the search query, a reverse lookup resolving coordinates back to an address.

---

## 5. Exposing it — reverse proxy, not a bare open port
Don't point this project's own `nominatim_self_hosted.endpoint` config directly at `http://<vps-ip>:8080` in production — put a reverse proxy (Caddy is the simplest genuine option, automatic TLS with zero manual certificate management) in front, and reference the proxied HTTPS URL instead. This is the same "don't expose a bare internal service directly" instinct Tunnel Exposure's own deep-dive already applies to this project's own Gateway (`v3-deepdive-43-tunnel-exposure.md`) — worth the same care here even though this is a third-party service, not this project's own code.

---

## 6. Keeping the data current
OSM data changes continuously; a one-time import goes stale. Nominatim's own replication mechanism handles incremental updates without a full re-import:
```bash
# One-shot update
docker exec nominatim sudo -u nominatim nominatim replication --once

# Or run as a background daemon inside the container for continuous updates
docker exec -d nominatim sudo -u nominatim nominatim replication
```
A reasonable operational cadence: a scheduled one-shot update (daily or weekly, via the VPS's own cron) rather than the continuous daemon mode, unless address-level freshness genuinely matters at a sub-daily granularity for your specific use — it doesn't for typical receipt-processing volume.

---

## 7. Pointing this project at it
Once the endpoint is live and reverse-proxied:
```
geo_address:
  providers_enabled: [locationiq, mapbox, nominatim_self_hosted]
  nominatim_self_hosted:
    endpoint: "https://your-nominatim-domain.example.com"
```
Nominatim joins the corroboration set as a genuine peer alongside LocationIQ/Mapbox (Geo/Address deep-dive §3) — not a replacement for them unless you explicitly remove the others from `providers_enabled`.

---

## 8. Operational ownership — read this before committing to self-hosting this
**This is real infrastructure you're now responsible for** — VPS security updates, Docker image updates, disk space for the growing database, and the replication cadence in §6 all need ongoing attention, unlike LocationIQ/Mapbox where DOMTRI (or the provider itself) carries that burden. This guide gets you to a working instance; it doesn't make the instance maintain itself. If you don't want this ongoing operational responsibility, the default LocationIQ + Mapbox providers remain the right choice — self-hosting Nominatim is an option for operators who specifically want it, not a generally-recommended upgrade.
