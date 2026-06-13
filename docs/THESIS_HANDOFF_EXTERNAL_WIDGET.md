# External Chatbot Widget — Architecture & Onboarding

The platform's two trust pillars — the **Smart Routing System** (kNN router picks
the cheapest model that clears a quality floor) and **RAG-with-Citation**
(grounded answers with verifiable sources) — were only reachable through the
internal V07 SPA. This subsystem exposes them as an **embeddable chatbot** that a
company drops onto its own public website. Visitors ask questions; the bot
auto-selects the best model per query **and** answers with citations grounded in
that company's knowledge base. Each deployment is re-themed per company with
**no code changes** — a config edit only.

## The fusion (why this needed new code)

Grounded chat used to bypass the router: a fixed free-model list generated every
grounded answer. The public chat handler now does both in one flow —

1. `model_router.route(query)` → selected model (decision brain, no tokens).
2. `grounded_collection_service.answer_query(..., generation_mode="gateway", answer_model_id=selected_id)` → the routed model generates the grounded, cited answer.

`answer_model_id` was threaded end-to-end in commit `3c5df4f`
(`GroundedRAGService.answer_query` → `GatewayAnswerGenerator.generate` via
`model_id_override`); the widget forces `generation_mode="gateway"` so the routed
model is used even for a collection ingested in heuristic mode.

## File map

| Concern | File |
|--------|------|
| Per-company config store + schema | `src/layer4_platform/bot_registry.py` |
| Abuse guard (rate limits) | `src/layer4_platform/widget_rate_limit.py` |
| Public API (config + fused chat) + loader.js + preview | `src/interfaces/http/routes/widget.py` |
| `/widget/*`-scoped CORS shim | `src/interfaces/http/middleware/widget_cors.py` |
| Admin CRUD + debug-chat | `src/interfaces/http/routes/admin_bots.py` |
| Website crawler | `src/layer3_domain/web_crawler.py` |
| Crawl endpoint | `src/interfaces/http/routes/grounded_documents.py` (`/collections/{id}/crawl`) |
| Settings (kill switch, rate/crawl caps) | `src/shared/config.py` (`WIDGET_*`) |
| Wiring (routers + outermost CORS) | `src/interfaces/http/main.py` |
| Tests | `tests/widget/` |

## Data model

A **company = tenant + grounded collection + one `BotConfig`**. Two projections:

- `BotConfig` (server-side, full): `bot_id`, `tenant_id`, `collection_id`,
  `display_name`, `greeting`, `suggested_prompts`, `theme`, `allowed_origins`,
  `grounded_domain`, `grounded_top_k`, `enabled`.
- `PublicBotConfig` (browser-safe): `bot_id`, `display_name`, `greeting`,
  `suggested_prompts`, `theme` **only**. Never carries `tenant_id`,
  `collection_id`, or `allowed_origins` — a leaked `bot_id` (it sits in the page
  source) yields branding, never the knowledge base or origin policy.

Configs persist as JSON snapshots under `.runtime/bot_configs/<bot_id>.json`
(gitignored), mirroring the collection store but resolving the directory from
`__file__`.

## Endpoints

**Public (`/widget/*`, credential-less CORS, cross-origin):**
- `GET  /widget/{bot_id}/config` → `PublicBotConfig`.
- `POST /widget/{bot_id}/chat` `{message}` → `{answer, grounded, sources[]}` —
  origin-enforced, rate-limited; routing/cost internals never appear in the body.
- `GET  /widget/loader.js` → the embeddable loader.
- `GET  /widget/preview?bot_id=…` → a local host page (hostile global CSS, to eyeball Shadow-DOM isolation).

**Admin (main app, strict CORS, internal):**
- `POST/GET/PUT/DELETE /admin/bots[/{bot_id}]` → CRUD (returns embed snippet + warnings).
- `POST /admin/bots/{bot_id}/debug-chat` → the **full** internal view (selected
  vs executed model, retrieval count, citations with internal ids).

## Theming — re-skin a company with zero code

The widget mounts a **Shadow DOM** (host CSS can't leak in or out) and writes the
company's `theme` into `--bot-*` CSS custom properties; every rule references
them. Re-skinning is purely editing `BotConfig.theme`:
`primary_color`, `accent_color`, `surface_color`, `text_color`,
`user_bubble_color`, `font_family`, `font_url`, `logo_url`, `launcher_icon_url`,
`launcher_position`, `corner_radius_px`, `dark_mode`. Plus `display_name`,
`greeting`, and `suggested_prompts` (the use-case/FAQ chips).

## Embedding

```html
<script src="https://APP/widget/loader.js" data-bot-id="bot_xxx" data-api-base="https://APP" async></script>
```

## Knowledge sources

- **Upload:** `POST /grounded-documents/collections/upload` (PDF/text, existing).
- **Crawl:** `POST /grounded-documents/collections/{id}/crawl` `{start_url, max_pages, max_depth, …}`
  — same-domain BFS, robots-aware, page/depth/byte-capped (ceilings in `Settings`).
  Each page keeps its URL as the citation source.
  - **Known limitation — JS-rendered sites.** No JS is executed, so SPAs
    (React/Vue/Angular) return near-empty pages; those are detected as "thin" and
    reported in the crawl `warnings`. Static/SSR sites only; SPA support would
    need a headless browser (Playwright) — future work.

## Security posture

- `bot_id` is public and `Origin`/`Referer` are spoofable, so the chat endpoint
  enforces **per-bot allowed origins in the handler** (CORS is advisory) and
  **per-IP + per-bot rate limits with a daily cap** (`Settings`, in-process;
  Redis is the multi-process upgrade). An enabled bot must declare ≥1 origin
  (default-deny). Admin endpoints have no auth (consistent with the rest of the
  platform) and are expected to be network-restricted.

## Onboarding walkthrough

```bash
# 1. seed knowledge (upload or crawl)
curl -X POST .../grounded-documents/collections/acme-kb/crawl \
  -d '{"start_url":"https://acme.com","tenant_id":"acme","max_pages":20,"max_depth":2}'
# 2. create the bot (capture bot_id + embed_snippet)
curl -X POST .../admin/bots -d '{"tenant_id":"acme","collection_id":"acme-kb",
  "display_name":"Acme","allowed_origins":["https://acme.com"],"theme":{"primary_color":"#0a7"}}'
# 3. paste the embed snippet on the site. Test internals via:
curl -X POST .../admin/bots/<bot_id>/debug-chat -d '{"message":"..."}'
```

## Verification status

- `tests/widget/` (23 tests, torch-free): no-leak projection, default-deny
  origins, origin matching, rate-limit windows/caps, crawler robots+caps+thin
  warning, `/widget/*` CORS scoping.
- Loader executed in jsdom against a mocked API (builds the Shadow DOM, applies
  theme variables, opens, renders greeting/chip, POSTs the prompt, renders the
  cited answer).
- Live-verified via the running API: config omits internal ids; grounded fused
  answer with sources (debug-chat shows selected==executed routed model);
  small-talk replies conversationally without grounding; forbidden/missing origin
  → 403; CORS preflight echoes origin with credentials false; crawl → grounded
  answer citing the live URL.
- Not yet automated: a real-browser screenshot of visual Shadow-DOM CSS isolation
  (jsdom doesn't paint) — open `/widget/preview?bot_id=…` to confirm by eye.

## Future work

- Headless rendering for JS/SPA sites (Playwright).
- Background execution for large crawls (currently synchronous, small caps).
- Redis-backed rate limiting for multi-process deployments.
- Streaming responses in the widget.
