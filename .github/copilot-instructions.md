# Copilot instructions for this repository

Purpose: quick-reference for AI coding agents to be immediately productive in this mono-repo.

Big picture
- `byoint_core/core.py` — Flask app exposing a small API and (optionally) a scheduler. It dynamically imports and runs datapull functions from `byoint_core/datapull.py`.
- `byoint_core/datapull.py` — data-pull templates, DB upserts, secrets management, and datapull API routes.
- `byoint_core/` — engine helpers; `data_output.py` provides EDL output from Mongo.
- `byoint_core/all_connects.py` — central Mongo connector and API-key helpers (reads `MONGO_*` env vars).
- `byoint-web/` — Vue 3 frontend; separate dev lifecycle (`npm install`, `npm run serve`).
- Docker / compose — repo contains `Dockerfile` and `docker-compose.yml` (containers expect service code under `/app/byoint_core`).

Data & runtime conventions (discoverable patterns)
- MongoDB database name: `byoint_core_data` (hard-coded in code). Collections used: `indicators`, `datapull_workflows`, `apikeys`.
- Environment variables used for DB creds: `MONGO_USERNAME`, `MONGO_PASSWORD`, `MONGO_HOST`, `MONGO_PORT` (both `byoint_core/all_connects.py` and `byoint_core/datapull.py`).
- API auth: requests must include header `Authorization: Bearer <API_KEY>`. Keys are looked up via `all_connects.return_apikeys()` against the `apikeys` collection.
- Datapull templates: add new templates by extending mappings and handlers in `byoint_core/datapull.py` and ensure datapull payload keys match template `ufield_args`.
- Indexing: code creates unique indexes (`indicators.create_index('value')`, `apikeys.create_index('apikey')`) — keep these semantics when modifying DB access.

Common developer workflows (how to run & test)
- Run the engine API locally (simplest): set Mongo env vars, then run:

```powershell
$env:MONGO_HOST="<host>"; $env:MONGO_PORT="27017"; $env:MONGO_USERNAME="user"; $env:MONGO_PASSWORD="pass"
python core.py
```

- Run the frontend: `cd byoint-web && npm install && npm run serve` (see [docs/byoint-web/README.md](docs/byoint-web/README.md)).
- Docker: repo includes compose files; containers expect application code paths appended in `byoint_core/core.py` (see `sys.path.append(os.path.dirname(__file__))`). Use `docker compose up -d --build` when coordinating services (copy `.env.example` to `.env` first).

API examples (concrete)
- Create a datapull (POST):

```bash
curl -X POST http://localhost:5000/api/datapull/create \
  -H "Authorization: Bearer <API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"source_name":"feed1","source_category":"feeds","source_template_type":"generic_url_text","datapull_payload":{"url_to_extract":"https://rules.emergingthreats.net/blockrules/compromised-ips.txt"}}'
```

Architecture notes / gotchas for contributors
- Custom template and enrichment snippets never run in the app. They go through `byoint_core/snippet_sandbox.py` to the `snippet_runner` container (`snippet_runner.py` / `snippet_child.py`, stdlib only) and are gated by the `allow_custom_snippet` core config (default off). Don't add `exec`/`eval` of user code anywhere else, and keep the runner files free of app imports.
- Under Docker Compose only nginx publishes a host port (443); Flask (5000) is reachable only on the compose network. Use `https://localhost/...` in examples for the Compose setup.
- Multiple modules rely on environment variables for DB access; tests or local runs must set those env vars.
- `byoint_core/datapull.py` defines template mappings and performs DB upserts — changing shape of `datapull_payload` requires coordinated updates to those mappings and any UI forms.
- The codebase is lightweight and does not include unit tests — add small focused tests when changing DB logic.

Key files to inspect for specific behavior
- [byoint_core/core.py](byoint_core/core.py)
- [byoint_core/all_connects.py](byoint_core/all_connects.py)
- [byoint_core/datapull.py](byoint_core/datapull.py)
- [byoint_core/data_output.py](byoint_core/data_output.py)
- [byoint_core/config.yaml](byoint_core/config.yaml)
- [docs/byoint-web/README.md](docs/byoint-web/README.md) and [byoint-web/package.json](byoint-web/package.json)

When coding pull requests
- Preserve DB collection names and indexing semantics unless you update DB migration scripts and the Docker setup.
- Use existing helpers (`connect_mongodb`, `return_apikeys`, `update_indicators`) instead of re-implementing connection logic.
- When adding new datapull templates, add mapping entries in `byoint_core/datapull.py` and include a minimal example payload in tests or docs.

If anything above is unclear or you'd like more detail (e.g., a sequence diagram or example DB documents), tell me which area to expand.
