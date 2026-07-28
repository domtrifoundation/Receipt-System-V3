# V3 Deep Dive: Tunnel Exposure (Gateway sub-API)

**Parent:** `v3-deepdive-19-gateway-api.md` §5. Requested directly — "Cloudflared in of itself needs a sub API" — after noticing this corpus had asserted "exposed via Cloudflare Tunnel" throughout without ever actually designing it: no config/credential management, no swappable-provider treatment despite this project's own standing modularity pledge, no health monitoring of the tunnel itself.

**Companion files:** `v3-deepdive-20-health-api.md` §3 (where tunnel health folds into the live diagnostic layer), `v3-deepdive-11-setup-api.md` §7 (first-run tunnel setup, self-hosted only).

**Status:** New dedicated document. No prior design existed beyond the vendor name.

---

## 1. Scope & boundary

Tunnel Exposure owns getting Gateway reachable from the public internet without the operator opening inbound firewall ports — for a self-hosted install specifically; DOMTRI's own hosted service has its own existing production ingress and doesn't use this sub-API's own provider selection at all. It does not:
- **cover every use of Cloudflare's platform in this project** — this sub-API is specifically about network exposure (the tunnel); the Webapp Assistant (`v3-deepdive-54-webapp-assistant.md`) separately uses Cloudflare Workers AI and a Cloudflare Worker for a genuinely different purpose (a chat backend), not this sub-API's own concern and not built on top of it.
- **replace Gateway's own defense-in-depth** — Gateway's rate limiting and request validation (its deep-dive §7) stay in place regardless of which tunnel provider is active; the tunnel is network-edge exposure, not the whole security posture.
- **own DNS beyond what a given provider's own setup requires** — Cloudflare Tunnel's own CNAME record creation is part of *that* provider's own config flow, not a generic DNS-management capability this sub-API offers independently of the active provider.

---

## 2. Package layout

```
services/gateway/tunnel_exposure/
  __init__.py
  contracts.py             # TunnelHandle, TunnelStatus, error types
  providers/
    __init__.py
    base.py                     # TunnelProvider Protocol
    cloudflare.py                  # the default — see §3
    manual_reverse_proxy.py          # the "no managed tunnel at all" option — see §4
  errors.py
```

---

## 3. `TunnelProvider` — a real Provider Registry, Cloudflare Tunnel as the default

```python
class TunnelProvider(Protocol):
    async def start(self, local_port: int, hostname: str) -> TunnelHandle: ...
    async def stop(self, handle: TunnelHandle) -> None: ...
    async def get_status(self, handle: TunnelHandle) -> TunnelStatus: ...
    async def is_configured(self) -> bool: ...    # has this provider's own credentials/config actually been set up
```

**`CloudflareTunnelProvider`**, the default: wraps the `cloudflared` binary as a managed subprocess (started/monitored the same way any other externally-managed process in this project is — Watchdog-adjacent supervision, not a fire-and-forget spawn), owns its own config file (`config.yml`) and credentials JSON obtained through Cloudflare's own `cloudflared tunnel login` flow during first-run setup (Setup deep-dive §7, self-hosted only, skipped entirely for the hosted service and for `setup-dev`'s bare-bones philosophy), and creates the CNAME record pointing the operator's chosen hostname at the tunnel via Cloudflare's own API. **Credentials live in the top-level config directory** (`docs/PRINCIPLES.md` §1.6) — genuinely shared, persistent state, never tied to any one release clone, since a tunnel's own identity shouldn't need re-establishing on every update.

---

## 4. Structurally-accommodated alternatives — real extension points, not fully designed here

Consistent with `docs/PRINCIPLES.md` §1.3's swappable-never-hardcoded discipline, a self-hosted operator who doesn't want Cloudflare's specific managed tunnel has real alternatives behind the same `TunnelProvider` interface:
- **`NgrokProvider`** — a second managed-tunnel option, same shape as Cloudflare's, for an operator who already has an ngrok account/workflow.
- **`TailscaleFunnelProvider`** — for an operator already inside a Tailscale network who wants to reuse that existing setup rather than adding a second, unrelated tunnel vendor.
- **`ManualReverseProxyProvider`** — the "no managed tunnel service at all" option, for an operator running their own nginx/Caddy reverse proxy with their own port-forwarding — this provider's `start()`/`stop()` are effectively no-ops (the operator's own infrastructure is already there); `get_status()` does a real reachability check against the configured public hostname rather than querying a tunnel daemon that doesn't exist in this configuration.

None of the three above are fully designed in this document — named as real, structurally-available extension points (the same honesty this project already applies elsewhere, e.g. Setup's `StartupRegistrar` naming a macOS `LaunchdRegistrar` as accommodated-but-undesigned) rather than asserted as complete.

---

## 5. Tunnel health — folded into Health API's existing live diagnostic layer, not a new mechanism
Whether the active tunnel provider is actually connected and passing traffic is exactly the kind of "is this dependency actually healthy right now" question Health API's own live diagnostic layer already exists for (its deep-dive §3) — `TunnelProvider.get_status()` is polled the same way any other external dependency's health gets folded into that layer, not a separate, bespoke monitoring path invented just for this one sub-API.

---

## 6. Asyncio and profiling
`cloudflared` (or an equivalent provider's own binary) runs as a managed subprocess — this sub-API's own work is starting/stopping/polling that process, genuinely I/O-bound (subprocess management, HTTP calls to whichever provider's own API), no compute-bound work of its own. **Forward-compatibility check, explicit rather than assumed**: no new Python dependency is introduced beyond whatever thin HTTP-client wrapper calls a given provider's own API (already-tracked dependencies cover this); the `cloudflared` binary itself is an external, independently-versioned tool, not a Python package, so it sits outside this project's own Python-version forward-compatibility pledge entirely — worth noting explicitly rather than leaving ambiguous whether it needed tracking the same way a PyPI dependency would.

---

## 7. gRPC surface

```protobuf
service TunnelExposureService {
  rpc GetTunnelStatus(StatusRequest) returns (TunnelStatusResponse);
  rpc SwitchProvider(SwitchProviderRequest) returns (SwitchProviderResponse);   // owner-only, self-hosted only
}
```

---

## 8. Testing hooks
- **Provider-swap test**: confirms switching from `CloudflareTunnelProvider` to `ManualReverseProxyProvider` (or back) doesn't require touching Gateway's own code — the concrete validation that this is a genuine Provider Registry, not a hardcoded assumption with an interface bolted on afterward.
- **Credential-persistence-across-update test**: confirms tunnel credentials survive an Update API clone cutover untouched — direct validation of §3's top-level-placement claim.

---

## 9. Open questions for this deep-dive (logged, not guessed at)
- **`NgrokProvider`/`TailscaleFunnelProvider`'s actual implementation** — named as real extension points (§4), genuinely deferred, not designed beyond that; not blocking, since Cloudflare Tunnel is the shipping default and these are for an operator who specifically wants a different provider.
- **Automatic tunnel-provider failover, resolved: no, always requires explicit operator action.** Changing how the whole instance is publicly reachable is exactly the kind of consequential action that shouldn't happen automatically and silently — an owner gets notified the active provider is down (the same Health-diagnostic-layer integration §5 already establishes) and makes the call themselves, never an automatic switch to a backup provider they didn't explicitly confirm.
