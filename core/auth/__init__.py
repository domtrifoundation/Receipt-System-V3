"""Auth & Tenancy API.

`contracts.py` is the only module other packages import from. Nothing outside this package
needs anything else here — `service.py` is reached over gRPC, and `assembly.build_servicer`
is how the process that hosts this API constructs it.

Deliberately empty of imports: this package's submodules pull in `grpc` and optionally
`authlib`/`webauthn`, and a consumer that only wants a `Role` enum should not pay for any of
that (`docs/PRINCIPLES.md` §3.3 point 5).
"""
