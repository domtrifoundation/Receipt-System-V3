# Per-service venvs and import resolution

This document exists because `docs/PROCESS_TOPOLOGY.md` §1, §2 and §7 assert — three times, as
established fact — that every one of the 32 Core APIs "owns its own venv," and
`v3-deepdive-38-supervisor.md` §2 states that Supervisor "launches each service from the correct
per-user-channel release's own **per-service venv**" — while **no document in this corpus ever
said who creates those venvs, from what, or how service code becomes importable inside one.**

That gap was load-bearing, not cosmetic. A venv is an isolated `site-packages`; `core/ocr/` and
`common/` are not installed into it by any step the corpus described, so a service launched from
its own venv would have failed at `import common.frozen_dict` before reaching a line of its own
logic. This document is the missing mechanism.

**Scope note.** This is the *mechanism*. The policy it serves — one process per Core API, and
why — is `docs/PROCESS_TOPOLOGY.md`'s, and that document stays authoritative where the two
touch. The install-directory placement rules are `docs/PRINCIPLES.md` §1.6's. Nothing here
overrides either; this fills the space between them.

---

## 1. What the corpus already committed to, and what it left open

Committed, and not reopened here:

- **One venv per service, per clone.** `docs/PROCESS_TOPOLOGY.md` §1 gives the reason and it is
  a real one: "Every Core API in this project has a genuinely different, sometimes conflicting
  dependency footprint (OCR's OpenCV/Tesseract/PaddleOCR stack has nothing to do with Auth's
  Authlib, and bundling them into one shared environment would be a real version-pinning
  conflict risk)."
- **Every update is a fresh `git clone` into a new `<version>_<commit-hash>` directory — never a
  pull, never in-place mutation** (`v3-deepdive-24-update-deployment-api.md` §3). This is what
  makes concurrent multi-channel operation possible at all: a release directory being actively
  served is never mutated underneath its own running process.
- **Several release directories can be genuinely, simultaneously serving traffic** — in hosted
  multi-tenant mode "multiple channels are a standing state, not a transient rollout window"
  (same §3).
- **`.github/scripts/check_stripped_content_list.py`** already classifies `requirements.txt` as
  shipped precisely because "Update API installs per-service venvs from it on every clone." The
  intent was recorded in CI before the mechanism existed.

Left open, and resolved here: **§2** (where venvs live), **§3** (how imports resolve), **§4**
(what gets installed into each), **§5** (who provisions them and when).

---

## 2. Layout — venvs live inside the clone they serve

```
<install-root>/                          # top-level, docs/PRINCIPLES.md §1.6
  config/  data/  models/                # shared, siblings to every clone, never inside one
  supervisor/                            # Supervisor's own minimal venv — permanent, outside
  start.bat  start.sh
  releases/
    x02.01.03_a1b2c3d/                   # a release clone — Stable, say
      common/  core/  services/  ...     # the code, exactly as cloned
      .venvs/
        core.persistence/
        core.auth/
        core.ocr/
        services.gateway/
        ...
    x02.02.00_e4f5g6h/                   # Beta — a wholly independent clone, own .venvs/
      .venvs/...
```

**Venvs go inside the clone, not at the top level.** This follows directly from the two facts
above rather than being a fresh preference: a venv is pinned to the exact dependency versions
that clone's code expects, so a Beta clone whose `core/auth/requirements.txt` moved to
`authlib>=1.4` must not share an environment with the Stable clone still on `1.3`. Sharing venvs
across clones would reintroduce, at fleet scale, precisely the version-conflict problem
per-service venvs exist to solve. It would also break the never-mutate-a-served-release
guarantee — provisioning a new clone's dependencies would be writing into an environment a
running process is currently importing from.

**The corollary is a real cost, stated plainly rather than buried:** venvs multiply as
*services × simultaneously-active clones*. Four active channels is 4 × 32 venvs. §4 is what
keeps that survivable — it is the reason per-service requirements are worth the bookkeeping, not
a tidiness exercise. Without the split, every one of those 128 environments would carry OCR's
multi-GB stack.

**`.venvs/` is generated, never committed.** It is a build product of the clone, like the webapp
bundle `build_webapp()` produces in the same finalize routine (`v3-deepdive-11-setup-api.md`
§7.4).

**Naming is the dotted import path** (`core.ocr`, not `ocr`). `core/` and `services/` are
separate trees that can hold the same leaf name — `execution_core` exists in both today — so a
bare leaf name is genuinely ambiguous, and a directory named for the import path it serves is
self-describing when someone is staring at a broken install.

---

## 3. Import resolution — the clone root on `PYTHONPATH`

Supervisor launches each service as:

```
<clone>/.venvs/<service>/bin/python  -m core.ocr.service
      cwd = <clone>
      env: PYTHONPATH=<clone>
```

The venv supplies **third-party packages only**. First-party code — `common/`, `core/*`,
`services/*` — is resolved from the clone root on `PYTHONPATH`. Nothing installs the project
into any venv.

**Why `PYTHONPATH` rather than relying on `cwd`.** `python -m` does put the working directory on
`sys.path[0]`, so `cwd=<clone>` alone would appear to work. It is rejected because it is
positional state that any later `os.chdir` silently invalidates, and — the deciding reason —
**it does not survive the child worker processes this architecture actually spawns.**
`docs/PROCESS_TOPOLOGY.md` §4–§5 establishes three APIs that fork their own workers:
Preprocessing's `ProcessPoolExecutor`, Background Workers' `CPU_PROCESS` jobs, and Inference's
`PresetWorker` `multiprocessing.Process` children. An environment variable is inherited by every
one of those children automatically; a working directory is a weaker guarantee, and a
`spawn`-start-method child (the default on Windows, and increasingly elsewhere) re-executes the
interpreter and re-derives `sys.path` from the environment. `PYTHONPATH` is what makes those
grandchildren resolve `common/` without any of the three APIs writing bespoke path-fixing code.

**Why not install the project into each venv.** `pip install -e .` across N clones × 32 venvs
means N × 32 editable installs all pointing at different clone roots, with `.pth` files and
`__editable__` finders whose failure mode is importing *another clone's* code — the exact
cross-release contamination the clone-per-release model exists to prevent. A non-editable
install would copy the code into every venv, multiplying the whole tree per service. Neither is
worth a packaging layer this repo has deliberately lived without: there is no `pyproject.toml`
at the root today, and `check_stripped_content_list.py` already classifies one as dev-only if it
ever appears.

**Consequence worth being explicit about:** a service can *physically* import any sibling's
modules, because the whole clone is on the path. The rule that it must not — reach siblings
through gRPC and injected `Protocol` seams, never a direct `core.x` import
(`docs/PRINCIPLES.md` §1.1, §1.7) — stays an architectural rule enforced by review and by the
`contracts.py`-only convention. It is not, and was never, enforced by the venv boundary. Per-
service venvs isolate *dependencies*, not *namespaces*. Stating that plainly matters: someone
will otherwise assume the venv split is the enforcement mechanism and stop looking.

---

## 4. What gets installed — the two-part composition

Each service venv receives exactly two requirement sets, in order:

1. **`common/requirements.txt`** — the shared runtime base every service needs, because
   `common/` is the one package every service imports. Currently `grpcio`, `protobuf`, and
   `frozendict` under a `python_version < '3.15'` marker.
2. **`<service-dir>/requirements.txt`** — that service's own third-party dependencies, if the
   file exists. Absent file means "base only," which is the common case: of the sixteen
   packages implemented today, only five need anything beyond the base.

The base lives at `common/requirements.txt` rather than the repo root deliberately. The unit is
the code every service actually imports, so the dependency set is exactly what every service
genuinely needs — a root-level "install everything" list is the thing this whole split exists to
avoid.

**`protobuf` is declared explicitly in the base, and that line is load-bearing.** Verified
rather than assumed: `grpcio` does not depend on `protobuf` (its only link is an optional
`[protobuf]` extra that pulls `grpcio-tools`). The reason `google.protobuf` imports work in an
ordinary dev checkout is that `grpcio-tools` drags protobuf in as a side effect. A service venv
installing `grpcio` alone would import-fail on its own generated `*_pb2.py` stubs at startup.

**`grpcio-tools` is deliberately *not* in the runtime base.** It is the protoc code generator —
build-time tooling, belonging in the developer environment, not replicated across 32 services ×
every active clone.

**The root `requirements.txt` keeps its shipped classification and becomes the aggregate/dev
convenience** — what a contributor installs into one venv so the full test suite runs in a
single environment. It is not what production venvs are built from; §5's provisioner composes
from the two files above. `check_stripped_content_list.py`'s comment on that entry is updated in
the same commit as this document.

---

## 5. Who provisions, and when

Provisioning is **shared plumbing with two callers**, exactly like `strip_development_content()`
before it (`docs/PRINCIPLES.md` §1.5, and `v3-deepdive-11-setup-api.md` §4.1's own statement of
that pattern):

- **Setup API** provisions the *first* clone's venvs, as a step in the finalize routine
  (`v3-deepdive-11-setup-api.md` §7.4). Setup §1 already claims "dependency installation" in its
  scope; this is the mechanism that claim was missing.
- **Update API's `release_manager.py`** provisions every *subsequent* clone's venvs, since every
  update is a fresh clone and a fresh clone has no `.venvs/` yet.

Both call one shared implementation rather than each growing their own, for the same reason the
strip list is shared: two independent copies drift.

**Provisioning must complete before Supervisor's Boot Sequence launches anything.** A service
whose venv is half-built is not a degraded service, it is an import error — this is one of the
few genuinely fail-closed paths outside security (`docs/PRINCIPLES.md` §4.2 governs the security
case; this is the same posture for a different reason). A clone whose provisioning failed is not
eligible for cutover, and Supervisor keeps serving the prior release, which is exactly the
rollback path §3 of its own document already describes.

**Provisioning is per-service independent and parallelisable.** One service's failed venv fails
that service's readiness, not the whole clone's — but since Boot Sequence health-gates every
service anyway, a clone with any service unprovisioned never reaches cutover. The distinction
matters for *reporting*: "core.ocr failed to provision: no tesseract wheel for this platform" is
actionable; "provisioning failed" is not.

---

## 6. Forward-Compatibility Pattern applicability

**Yes, and in a specific way worth naming.** The base's `frozendict; python_version < '3.15'`
marker is the pattern's first point (`docs/PRINCIPLES.md` §3.3): on a newer interpreter the
older dependency is not merely unused, it is never installed. Because each service venv is
built independently, this evaluates per venv — which is correct, and also means a mixed-
interpreter install (a service pinned to 3.14 while the rest run 3.15) resolves each
environment correctly rather than sharing one wrong answer.

The known live instance of this: `grpcio` has no prebuilt wheel for 3.15 and building it from
source against 3.15 beta failed outright in this project's own environment — tracked in
`docs/MAINTENANCE.md` §8.1, and the reason `noxfile.py`'s `forward_compat` session installs a
narrow explicit set rather than the runtime base. That is a real Day-0 gap in an upstream
dependency, not a reason to change the design here.

---

## 7. Testing hooks

- The composition in §4 (base then service, absent-file means base-only) deserves a direct test:
  it is the piece a future change is most likely to get subtly wrong.
- **A test that the base genuinely carries `protobuf`** — the `grpcio`-does-not-pull-protobuf
  finding above is exactly the kind of fact that gets "cleaned up" as redundant by someone who
  checks `pip list` in a dev venv where `grpcio-tools` is present.
- A test pinning the **non**-finding that a service directory with no `requirements.txt` is
  valid and yields the base alone — the common case, and the one an over-eager validation pass
  would turn into an error.

---

## 8. Open questions

- **Where `.venvs/` sits relative to garbage collection.** Update API GCs release directories
  past a retention window (§3 of its own document). A clone's `.venvs/` is inside it and goes
  with it, which is correct — but the disk-space accounting that GC policy was reasoned about
  predates venvs being counted, and a release directory is now substantially larger than "the
  repo at that commit." Worth revisiting the retention window against real measured sizes rather
  than assuming the existing window still fits.
- **Whether provisioning can share a pip cache across clones.** Safe in principle (the cache is
  keyed by package version, and wheels are immutable), and it would cut the multi-clone cost in
  §2 substantially. Not designed here because the cache's own placement interacts with §1.6's
  top-level rules, which deserves its own decision rather than an assumption.
