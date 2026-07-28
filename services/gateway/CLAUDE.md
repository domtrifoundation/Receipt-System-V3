# Gateway API

Gateway is the FastAPI REST/WebSocket layer in front of the gRPC core, exposed via Cloudflare Tunnel. It owns: translating browser HTTP/WebSocket calls into internal gRPC calls, serving the webapp's static build, session-cookie authentication at the edge, and request-layer defense-in-depth (rate limiting, input validation). Like Interface API, Gateway is a detachable client of the core process, not part of it — `docs/PRINCIPLES.md` §1.7's process-separation-via-gRPC principle applies here identically, which is exactly why the third bullet below is possible at all.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. V2's `llm_server.py` served the local model over HTTP to V2's own processes — an internal model host, not a product-facing authenticated API surface. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a01.00.00`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-19-gateway-api.md`](../../docs/apis/v3-deepdive-19-gateway-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **contain business logic** — every route is a thin translation to a gRPC call; Gateway doesn't decide what a request means, only authenticates it and forwards it.
- **own file-content scanning** — that's Content Security's job; Gateway's job is the network/request layer, not payload inspection.
- **run in self-hosted single-user installs that don't need it** — since all real logic lives in the gRPC core, a self-hosted single-user install can skip running Gateway entirely and talk to the core directly if it has no need for the webapp.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

Webapp and API share one origin, deliberately: the webapp calls `/api/v1/...` as relative same-origin paths, which removes CORS entirely and keeps `SameSite=Lax` viable. Gateway serves the webapp's static build in *every* deployment mode — that is what guarantees a user's frontend and backend are the same channel version, and it is a corrected decision, not a default. Cloudflare's edge protection does not replace Gateway's own rate limiting and input validation; both exist on purpose.
