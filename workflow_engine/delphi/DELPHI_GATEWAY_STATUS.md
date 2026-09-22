# Delphi `WfEngineSrv` gateway status

**Status:** Deprecated. The production middle tier is the Python gateway.

The Delphi HTTP gateway (`WfEngineSrv` / `MethylWfGateway` Windows service) is not deployed. The supported gateway is Python `goliath-gateway` (`methyl-gateway` remains a one-cycle alias), implemented in [`../rest/gateway.py`](../rest/gateway.py). Do not add routes, OpenAPI parity work, or production installs for `WfEngineSrv`.

## Scope when frozen

- Worker and admin REST subset only (OpenAPI `/v1/*` routes implemented in DMVC controllers).
- Dual-database connection helpers (Azure SQL + PostgreSQL, managed identity) remain in `WfEngine.Connection.pas` for historical comparison with Python.
- **No new routes**, OpenAPI parity work, or production deployment changes are planned.

## Build (manual, Win64)

`WfEngineSrv` is **excluded** from the default `WfEngine.groupproj` `Build` target. Build the package and tests via the group project; build the gateway executable only when needed:

1. Open `WfEngine.groupproj` in RAD Studio.
2. Build **WfEnginePkg** and **WfEngineTests** (default group `Build`).
3. For the gateway host: right-click **WfEngineSrv** → Build (Win64).

Or MSBuild:

```text
msbuild WfEngineSrv.dproj /p:Platform=Win64 /t:Build
```

## Development modes (optional)

```text
WfEngineSrv /console port=8080
WfEngineSrv /install
```

See [`WORKFLOW_ENGINE_DELPHI.md`](WORKFLOW_ENGINE_DELPHI.md) for Delphi runtime notes.

## Do not delete

Keep `WfEngineSrv.dproj`, DMVC units, and integration tests for Windows debugging and contract archaeology. CI (`.github/workflows/db-parity.yml`) exercises the **Python** gateway only.
