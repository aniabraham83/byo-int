<template>
  <div class="arch-page">
    <div class="d-flex justify-content-between align-items-start flex-wrap gap-2 mb-3">
      <div>
        <h2 class="mb-1">Architecture</h2>
        <p class="text-muted mb-0">How a datapull becomes a feed: the five containers and the numbered path one pull takes from scheduler to consumer.</p>
      </div>
    </div>

    <figure class="mb-0">
      <div class="diagram-scroll">
        <svg class="d" viewBox="0 0 1200 1040" role="img" aria-label="BYO-INT architecture: the scheduler enqueues a job in Redis, a datapull worker pulls from an external source, detects types, upserts and enriches indicators in MongoDB, and the output builder caches a feed in Redis that firewalls, API clients and MCP clients fetch through Nginx.">
        <defs>
        <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path class="mk" d="M0,0 L10,5 L0,10 z"/></marker>
        <marker id="arra" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path class="mka" d="M0,0 L10,5 L0,10 z"/></marker>
        </defs>

        <!-- Clients -->
        <rect class="box" x="55" y="20" width="250" height="56" rx="8"/>
        <text class="t" x="71" y="44">Browser</text><text class="s" x="71" y="62">Admin UI · operators</text>
        <rect class="box" x="335" y="20" width="250" height="56" rx="8"/>
        <text class="t" x="351" y="44">Firewalls / NGFW</text><text class="s" x="351" y="62">Pull EDL text lists</text>
        <rect class="box" x="615" y="20" width="250" height="56" rx="8"/>
        <text class="t" x="631" y="44">API clients</text><text class="s" x="631" y="62">JSON feeds · API key</text>
        <rect class="box" x="895" y="20" width="250" height="56" rx="8"/>
        <text class="t" x="911" y="44">MCP clients</text><text class="s" x="911" y="62">AI agents · JSON-RPC</text>

        <line class="e" x1="180" y1="76" x2="180" y2="114" marker-end="url(#arr)"/>
        <text class="el" x="188" y="100">HTTPS · UI + /api</text>
        <line class="f" x1="460" y1="114" x2="460" y2="78" marker-end="url(#arra)"/>
        <g class="badge"><circle cx="477" cy="96" r="9"/><text x="477" y="96">9</text></g>
        <text class="fl" x="491" y="100">GET /feeds/&lt;name&gt;</text>
        <line class="e" x1="740" y1="76" x2="740" y2="114" marker-end="url(#arr)"/>
        <text class="el" x="748" y="100">GET /feeds/&lt;name&gt;</text>
        <line class="e" x1="1020" y1="76" x2="1020" y2="114" marker-end="url(#arr)"/>
        <text class="el" x="1028" y="100">POST /mcp/&lt;name&gt;</text>

        <!-- Edge -->
        <rect class="box" x="55" y="116" width="1090" height="66" rx="8"/>
        <text class="t" x="71" y="142">Nginx · vue_app container</text>
        <text class="s" x="71" y="160">TLS on :443 · certs/ mounted read-only</text>
        <rect class="chip" x="343" y="128" width="240" height="42" rx="6"/>
        <text class="m" x="463" y="153" text-anchor="middle">/api/*  →  flask:5000</text>
        <rect class="chip" x="617" y="128" width="240" height="42" rx="6"/>
        <text class="m" x="737" y="153" text-anchor="middle">/feeds/* · /mcp/*  →  flask:5000</text>
        <rect class="chip" x="891" y="128" width="240" height="42" rx="6"/>
        <text class="m" x="1011" y="153" text-anchor="middle">/  →  Vue 3 SPA (static)</text>

        <!-- Control plane -->
        <rect class="zone" x="40" y="204" width="1120" height="208" rx="12"/>
        <text class="zl" x="56" y="224">FLASK_APP · CONTROL PLANE (GUNICORN)</text>
        <line class="e" x1="463" y1="182" x2="463" y2="242" marker-end="url(#arr)"/>
        <line class="f" x1="737" y1="242" x2="737" y2="182" marker-end="url(#arra)"/>

        <rect class="box" x="64" y="244" width="250" height="60" rx="8"/>
        <text class="t" x="80" y="264">Auth &amp; RBAC</text>
        <text class="s" x="80" y="281">Sessions · API keys · OIDC SSO</text>
        <text class="s" x="80" y="296">Role-restricted pages</text>
        <rect class="box" x="338" y="244" width="250" height="60" rx="8"/>
        <text class="t" x="354" y="264">REST API</text>
        <text class="s" x="354" y="281">Workflows, templates, outputs,</text>
        <text class="s" x="354" y="296">enrichments, config, users</text>
        <rect class="box" x="612" y="244" width="250" height="60" rx="8"/>
        <text class="t" x="628" y="264">Feed &amp; MCP endpoints</text>
        <text class="s" x="628" y="281">/feeds/&lt;name&gt; · /mcp/&lt;name&gt;</text>
        <text class="s" x="628" y="296">Serve from cache, else build</text>
        <rect class="box" x="886" y="244" width="250" height="60" rx="8"/>
        <text class="t" x="902" y="264">Secrets</text>
        <text class="s" x="902" y="281">AES-GCM · master key from env</text>
        <text class="s" x="902" y="296">sec_* refs resolved at run time</text>

        <rect class="box" x="64" y="330" width="250" height="60" rx="8"/>
        <text class="t" x="80" y="350">Scheduler</text>
        <text class="s" x="80" y="367">APScheduler interval jobs</text>
        <text class="s" x="80" y="382">Enqueues due workflows</text>
        <rect class="box" x="338" y="330" width="250" height="60" rx="8"/>
        <text class="t" x="354" y="350">Bootstrap</text>
        <text class="s" x="354" y="367">mongo_init.json · init / reset</text>
        <text class="s" x="354" y="382">Seeds the admin user</text>
        <rect class="box" x="612" y="330" width="250" height="60" rx="8"/>
        <text class="t" x="628" y="350">Output builder</text>
        <text class="s" x="628" y="367">Category · guardrails · filters</text>
        <text class="s" x="628" y="382">Source, tag, score, enrichment</text>
        <rect class="box" x="886" y="330" width="250" height="60" rx="8"/>
        <text class="t" x="902" y="350">Audit &amp; change logs</text>
        <text class="s" x="902" y="367">Every API call, and who</text>
        <text class="s" x="902" y="382">created, changed or deleted what</text>

        <line class="e" x1="737" y1="304" x2="737" y2="328" marker-end="url(#arr)"/>
        <text class="el" x="745" y="321">cache miss</text>

        <!-- Step 1 and step 8 between control and execution -->
        <line class="f" x1="189" y1="390" x2="189" y2="460" marker-end="url(#arra)"/>
        <g class="badge"><circle cx="206" cy="420" r="9"/><text x="206" y="420">1</text></g>
        <text class="fl" x="220" y="424">enqueue job</text>
        <polyline class="f" points="737,390 737,420 262,420 262,460" marker-end="url(#arra)"/>
        <g class="badge"><circle cx="530" cy="438" r="9"/><text x="530" y="438">8</text></g>
        <text class="fl" x="544" y="442">build + cache feed (TTL 120s)</text>

        <!-- Execution plane -->
        <rect class="zone" x="40" y="430" width="1120" height="172" rx="12"/>
        <text class="zl" x="56" y="450">EXECUTION PLANE · DATAPULL_WORKER (SCALABLE)</text>

        <rect class="box" x="89" y="462" width="200" height="120" rx="8"/>
        <text class="t" x="105" y="484">Redis</text>
        <text class="s" x="105" y="502">redis:7 · internal only</text>
        <text class="m" x="105" y="524">job queue (list)</text>
        <text class="m" x="105" y="542">worker metrics</text>
        <text class="m" x="105" y="560">feed cache</text>

        <rect class="box" x="363" y="462" width="200" height="120" rx="8"/>
        <text class="t" x="379" y="484">Datapull worker</text>
        <text class="s" x="379" y="502">queue_worker.py · N replicas</text>
        <text class="s" x="379" y="524">Resolves secret refs</text>
        <text class="s" x="379" y="542">Logs every execution</text>
        <text class="s" x="379" y="560">Retries, dead-letter queue</text>

        <rect class="box" x="637" y="462" width="200" height="120" rx="8"/>
        <text class="t" x="653" y="484">Template executor</text>
        <text class="s" x="653" y="502">11 built-in pull functions</text>
        <text class="s" x="653" y="524">Custom snippet sandbox</text>
        <text class="s" x="653" y="542">Byte and row caps</text>
        <text class="s" x="653" y="560">Allow-listed imports</text>

        <rect class="box" x="911" y="462" width="200" height="120" rx="8"/>
        <text class="t" x="927" y="484">External sources</text>
        <text class="s" x="927" y="502">HTTP feeds · REST APIs</text>
        <text class="s" x="927" y="524">MySQL · MSSQL · Oracle</text>
        <text class="s" x="927" y="542">PostgreSQL · MongoDB</text>
        <text class="s" x="927" y="560">LDAP / AD · MCP servers</text>

        <line class="f" x1="289" y1="500" x2="361" y2="500" marker-end="url(#arra)"/>
        <g class="badge"><circle cx="304" cy="486" r="9"/><text x="304" y="486">2</text></g>
        <text class="fl" x="316" y="490">pop</text>
        <line class="e" x1="363" y1="556" x2="291" y2="556" marker-end="url(#arr)"/>
        <text class="el" x="303" y="572">metrics</text>
        <line class="f" x1="563" y1="500" x2="635" y2="500" marker-end="url(#arra)"/>
        <text class="fl" x="586" y="490">run</text>
        <line class="f" x1="837" y1="500" x2="909" y2="500" marker-end="url(#arra)"/>
        <g class="badge"><circle cx="852" cy="486" r="9"/><text x="852" y="486">3</text></g>
        <text class="fl" x="864" y="490">pull</text>
        <line class="e" x1="911" y1="556" x2="839" y2="556" marker-end="url(#arr)"/>
        <text class="el" x="851" y="572">rows, lines</text>

        <!-- Indicator pipeline -->
        <polyline class="f" points="737,582 737,611 189,611 189,650" marker-end="url(#arra)"/>
        <text class="fl" x="420" y="606">raw values</text>
        <rect class="zone" x="40" y="620" width="1120" height="140" rx="12"/>
        <text class="zl" x="56" y="640">INDICATOR PIPELINE · RUNS INSIDE THE WORKER</text>

        <rect class="box" x="89" y="652" width="200" height="84" rx="8"/>
        <g class="badge"><circle cx="107" cy="672" r="9"/><text x="107" y="672">4</text></g>
        <text class="t" x="123" y="676">Detect type</text>
        <text class="s" x="105" y="700">Workflow's source-type regex</text>
        <text class="s" x="105" y="717">from data_types, else ipv4</text>

        <rect class="box" x="363" y="652" width="200" height="84" rx="8"/>
        <g class="badge"><circle cx="381" cy="672" r="9"/><text x="381" y="672">5</text></g>
        <text class="t" x="397" y="676">Upsert indicator</text>
        <text class="s" x="379" y="700">Per-source entry · tag · score</text>
        <text class="s" x="379" y="717">Bulk write when insertmany</text>

        <rect class="box" x="637" y="652" width="200" height="84" rx="8"/>
        <g class="badge"><circle cx="655" cy="672" r="9"/><text x="655" y="672">6</text></g>
        <text class="t" x="671" y="676">Enrich</text>
        <text class="s" x="653" y="700">Built-in · custom snippet</text>
        <text class="s" x="653" y="717">Connector · MCP tool</text>

        <rect class="box" x="911" y="652" width="200" height="84" rx="8"/>
        <g class="badge"><circle cx="929" cy="672" r="9"/><text x="929" y="672">7</text></g>
        <text class="t" x="945" y="676">Recompute active</text>
        <text class="s" x="927" y="700">Values a source stopped</text>
        <text class="s" x="927" y="717">sending go inactive</text>

        <line class="f" x1="289" y1="694" x2="361" y2="694" marker-end="url(#arra)"/>
        <line class="f" x1="563" y1="694" x2="635" y2="694" marker-end="url(#arra)"/>
        <line class="f" x1="837" y1="694" x2="909" y2="694" marker-end="url(#arra)"/>

        <!-- Writes to storage -->
        <line class="e" x1="463" y1="736" x2="463" y2="810" marker-end="url(#arr)"/>
        <text class="el" x="471" y="776">indicators</text>
        <line class="e" x1="737" y1="736" x2="737" y2="810" marker-end="url(#arr)"/>
        <text class="el" x="745" y="776">enrichment fields</text>
        <line class="e" x1="1011" y1="736" x2="1011" y2="810" marker-end="url(#arr)"/>
        <text class="el" x="1019" y="776">indicator + run logs</text>

        <!-- Config bus: control plane <-> MongoDB -->
        <polyline class="e" points="40,300 22,300 22,890 62,890" marker-start="url(#arr)" marker-end="url(#arr)"/>
        <text class="el" transform="translate(16 640) rotate(-90)" text-anchor="middle">config, workflows, outputs (read / write)</text>

        <!-- Storage -->
        <rect class="zone" x="40" y="780" width="1120" height="196" rx="12"/>
        <text class="zl" x="56" y="800">STORAGE · MONGODB 8 · PORT 27017 PUBLISHED TO HOST</text>

        <rect class="box" x="64" y="812" width="340" height="150" rx="8"/>
        <text class="mt" x="80" y="836">byoint_core_config</text>
        <text class="m" x="80" y="858">datapull_templates · data_types</text>
        <text class="m" x="80" y="876">data_enrichments · tags</text>
        <text class="m" x="80" y="894">datapull_secrets (encrypted)</text>
        <text class="m" x="80" y="912">output_guardrails · basicconfigs</text>
        <text class="m" x="80" y="930">integration_capabilities</text>

        <rect class="box" x="430" y="812" width="340" height="150" rx="8"/>
        <text class="mt" x="446" y="836">byoint_core_data</text>
        <text class="m" x="446" y="858">indicators</text>
        <text class="m" x="446" y="876">datapull_workflows · outputs</text>
        <text class="m" x="446" y="894">users · browser_sessions</text>
        <text class="m" x="446" y="912">api_audit_logs</text>

        <rect class="box" x="796" y="812" width="340" height="150" rx="8"/>
        <text class="mt" x="812" y="836">byoint_opslogs</text>
        <text class="m" x="812" y="858">datapull_executions · datapull_jobs</text>
        <text class="m" x="812" y="876">scheduler_logs</text>
        <text class="m" x="812" y="894">indicator_logs</text>
        <text class="m" x="812" y="912">platform_change_logs</text>

        <!-- Legend -->
        <line class="f" x1="56" y1="1006" x2="96" y2="1006"/>
        <text class="el" x="104" y="1010">Numbered path of one datapull, from schedule to consumer</text>
        <line class="e" x1="470" y1="1006" x2="510" y2="1006"/>
        <text class="el" x="518" y="1010">Supporting calls: UI, API, metrics, storage</text>
        </svg>
      </div>
      <figcaption>Amber marks the path one scheduled datapull takes: queued in Redis, pulled by a worker, typed, stored, enriched, then built into a cached feed that a firewall fetches through Nginx. Grey lines are the supporting traffic around it.</figcaption>
    </figure>

    <div class="below">
    <section>
    <h2>The flow, step by step</h2>
    <ol class="flow">
    <li><span>The scheduler finds a due workflow and pushes a job onto the Redis queue.</span></li>
    <li><span>A datapull worker pops the job, loads the workflow and resolves its <code>sec_*</code> secret references.</span></li>
    <li><span>The template executor pulls from the source: a URL, a REST or MCP API, a SQL or Mongo query, or an LDAP search.</span></li>
    <li><span>Each value is matched against the workflow's data-type regex to decide what kind of indicator it is.</span></li>
    <li><span>Matches are upserted into <code>indicators</code> with a per-source entry carrying the workflow's tag and score.</span></li>
    <li><span>The workflow's selected enrichments add context such as resolved IPs or connector and MCP lookups.</span></li>
    <li><span>Values a source no longer sends are marked inactive for that source, and each indicator's active flag is recomputed.</span></li>
    <li><span>When an output is requested and not cached, the output builder applies its category, guardrails and filters and caches the result for 120 seconds.</span></li>
    <li><span>A firewall, API client or MCP client fetches the feed through Nginx at <code>/feeds/&lt;name&gt;</code> or <code>/mcp/&lt;name&gt;</code>.</span></li>
    </ol>
    </section>
    <section>
    <h2>Notes for reviewers</h2>
    <ul class="notes">
    <li>Only Nginx publishes a host port (443, on all interfaces, so feeds and MCP are reachable at the host's IP). MongoDB (27017) is published on <code>127.0.0.1</code> only, for local admin tools. Redis, Flask, the workers and the snippet runner are reachable only on the compose networks.</li>
    <li>Flask runs with its queue worker disabled; all pulls run in <code>datapull_worker</code>, which can be scaled from the Worker Scaling page.</li>
    <li>Credentials never sit in workflow payloads in plain text. A payload holds a <code>*_secret_ref</code>, and the worker decrypts it at run time.</li>
    <li>JSON and MCP outputs always require authentication. EDL text feeds can be public or require an API key per output.</li>
    <li>Custom snippets are off by default (<code>allow_custom_snippet</code> in the <code>core</code> config). When enabled, they run in the separate <code>snippet_runner</code> container, which has no app secrets, a read-only filesystem and no route to MongoDB or Redis. Allowed imports and built-ins are configured in <code>basicconfigs</code>.</li>
    </ul>
    </section>
    </div>
  </div>
</template>

<script>
// The diagram is shared with the published architecture page; keep both copies in sync when the platform changes.
export default {
  name: 'ArchitectureDiagram'
}
</script>

<style scoped>
.arch-page {
  --fg: #14213d;
  --muted: #5b6780;
  --zone: #e7ebf3;
  --zone-stroke: #cfd6e4;
  --box: #ffffff;
  --stroke: #9aa6bd;
  --accent: #c77700;
  --accent-ink: #9a5b00;
  --on-accent: #ffffff;
  --font-sans: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --font-mono: ui-monospace, "Cascadia Mono", Consolas, monospace;
  padding: 1.5rem;
  color: var(--fg);
}

.diagram-scroll {
  overflow-x: auto;
  background: #f7f8fa;
  border: 1px solid var(--zone-stroke);
  border-radius: 10px;
}

.diagram-scroll svg {
  display: block;
  width: 100%;
  min-width: 980px;
  height: auto;
}

figcaption {
  color: var(--muted);
  font-size: 0.85rem;
  margin-top: 0.6rem;
  max-width: 90ch;
}

.below {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
  gap: 2rem;
  margin-top: 2rem;
}

.below h2 {
  font-size: 1.1rem;
  margin-bottom: 0.6rem;
}

ol.flow {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 0.5rem;
  counter-reset: step;
}

ol.flow li {
  display: grid;
  grid-template-columns: 26px minmax(0, 1fr);
  gap: 0.6rem;
  align-items: start;
}

ol.flow li::before {
  counter-increment: step;
  content: counter(step);
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--accent);
  color: var(--on-accent);
  font: 600 12px/22px var(--font-mono);
  text-align: center;
  margin-top: 1px;
}

ul.notes {
  margin: 0;
  padding-left: 1.1rem;
  display: grid;
  gap: 0.5rem;
}

.d .zone { fill: var(--zone); stroke: var(--zone-stroke); stroke-width: 1; }
.d .zl { fill: var(--muted); font: 600 11px var(--font-mono); letter-spacing: 0.06em; }
.d .box { fill: var(--box); stroke: var(--stroke); stroke-width: 1.2; }
.d .chip { fill: var(--zone); stroke: var(--stroke); stroke-width: 1; }
.d .t { fill: var(--fg); font: 600 13px var(--font-sans); }
.d .s { fill: var(--muted); font: 400 11px var(--font-sans); }
.d .m { fill: var(--fg); font: 400 11px var(--font-mono); }
.d .mt { fill: var(--fg); font: 600 13px var(--font-mono); }
.d .e { stroke: var(--muted); stroke-width: 1.4; fill: none; }
.d .f { stroke: var(--accent); stroke-width: 2.2; fill: none; }
.d .el { fill: var(--muted); font: 400 11px var(--font-sans); }
.d .fl { fill: var(--accent-ink); font: 600 11px var(--font-sans); }
.d .mk { fill: var(--muted); }
.d .mka { fill: var(--accent); }
.d .badge circle { fill: var(--accent); }
.d .badge text { fill: var(--on-accent); font: 700 11px var(--font-mono); text-anchor: middle; dominant-baseline: central; }

@media (max-width: 820px) {
  .arch-page {
    padding: 1rem;
  }

  .below {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
