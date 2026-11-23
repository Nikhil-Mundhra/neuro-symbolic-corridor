# Commercial Telemetry API Discovery & Integration Specification

> **Scope**: Commercial telemetry provider evaluation and Go/Python ingestion contract for the Neuro-Symbolic Corridor Solver (`INNSA` -> `AEFJR` / `OMSOH` / `OMSLL` / `AEJEA` -> `AEKHL` / `AEAUH` / `AEDWC` -> `EUFRA`).
> **Target Codebase Surfaces**: `services/solver-py/app/models.py` (`DisruptionState`, `CorridorEdge`, `ShipmentSpec`), `services/solver-py/app/network.py`, and `services/gateway-go/main.go` (`GatewayServer.Routes`).

## Epistemic & Documentation Boundary Policy

All provider claims below distinguish strictly between:
1. **Publicly Documented**: Endpoints, authentication headers, payload keys, status codes, and operational limits explicitly published in vendor developer portals or public OpenAPI/GraphQL references retrieved during discovery.
2. **Enterprise-Gated / NDA-Only**: Private webhook JSON schemas, exact USD contract pricing, tenant-specific rate-limit ceilings, and live sandbox credentials that are only exposed post-NDA or via customer portal onboarding. These are explicitly marked **`Requires commercial onboarding / sandbox verification`** and are never fabricated.

---

## 1. AIS & Port Congestion: Spire Maritime vs. MarineTraffic

Operational relevance to Gulf corridors (`INNSA` -> `AEJEA` via Strait of Hormuz vs. bypass ports `AEFJR`, `OMSOH`, `OMSLL`):
- **Strait of Hormuz & Inverse Congestion Trap**: AIS monitoring across Hormuz, Fujairah (`AEFJR`), and Jebel Ali (`AEJEA`) demonstrates that direct vessel wait times alone can mislead routing solvers. During severe Hormuz transit restrictions, `AEJEA` can display deceptively *low* anchorage wait times (~0.37 days) solely because mainline carriers suspended direct Gulf loops, whereas bypass terminals like `AEFJR` absorb diverted transshipment volume and spike to **7–8.8+ days** vessel waiting time and **12–15 days** onward landside transfer delays. Consequently, ingestion must track both **anchorage/berth wait hours** and **vessel arrival count / Hormuz transit throughput drops**.

### 1.1 Spire Maritime (acquired by Kpler)

| Dimension | Verified Public Detail / Boundary Status |
| :--- | :--- |
| **Docs & Portals** | GraphQL Endpoint: `https://api.spire.com/graphql` (Maritime 2.0)<br>Consolidated Portal (post-Kpler acquisition): `https://developers.kpler.com` (legacy `docs.spire.com` transitioning to Kpler) |
| **Protocols** | GraphQL-first (`Maritime 2.0`), focused REST endpoints (vessel particulars, fleet ops, port data), and raw TCP/NMEA streams |
| **Authentication** | GraphQL: `Authorization: Bearer <TOKEN>`<br>REST: `X-API-Key: <API_KEY>` |
| **Publicly Documented Schema Fields** | **`vessels` GraphQL node**: `id`, `updateTimestamp`, `staticData` (`aisClass`, `flag`, `name`, `callsign`, `imo`, `mmsi`, `shipType`), `position` / `lastPosition` (`latitude`, `longitude`, `speed`, `course`, `heading`, `timestamp`), `voyageData` (`destination`, `eta`, `draught`)<br>**`port` / `matchedPort`**: `unlocode` (e.g., `AEJEA`, `AEFJR`, `OMSOH`, `OMSLL`), `name`, `centerPoint { latitude longitude }`, `matchScore` |
| **Port Congestion / Berth Wait Keys** | Port Events & congestion analytics endpoints exist under Kpler/Spire geofenced port boundaries, but exact congestion aggregation field names (e.g., berth vs. anchorage dwell breakdown) **require commercial onboarding / sandbox verification** on `developers.kpler.com` |
| **Update Cadence** | Near real-time terrestrial + LEO satellite AIS (sub-minute message processing and high-frequency polling depending on contract tier) |
| **Rate Limits** | Contract-tier specific; HTTP throttling errors returned on breach. Exact req/min or GraphQL query-cost caps **require commercial onboarding / sandbox verification** |
| **Pricing Tiers** | Custom enterprise contracts scaled by AoI (Area of Interest) filters, vessel count, historical depth, and streaming vs. polling. No public self-serve price sheet |
| **Developer Sandbox** | Evaluation/demo tokens available selectively via sales/portal request; no open self-serve global satellite sandbox |

### 1.2 MarineTraffic (Kpler Group)

| Dimension | Verified Public Detail / Boundary Status |
| :--- | :--- |
| **Docs & Portals** | Service Portal: `https://www.marinetraffic.com/en/ais-api-services`<br>Service Docs: `https://servicedocs.marinetraffic.com/` |
| **Protocols & Key Services** | REST JSON/XML endpoints organized by alphanumeric service codes:<br>• **`PS07`**: Single Vessel Positions<br>• **`EV01`**: Port Calls (arrivals/departures)<br>• **`VI06`**: Port Congestion Analytics (`/port-congestion/{api_key}`)<br>• **`Expected Arrivals`**: (`/expectedarrivals/{api_key}`) |
| **Authentication** | API Key via header (`X-API-Key: <API_KEY>`) or URL path/query parameter depending on endpoint version |
| **Publicly Documented Schema Fields** | **`VI06` Port Congestion**: `PORT_ID` / `port_id`, `PORT_NAME`, `UNLOCODE`, `YEAR` / `WEEK` (`ISO_WEEK`), `MARKET` / `SHIP_CLASS`, `VESSEL_COUNT` / `vessels_waiting`, `CALL_COUNT`, `MEDIAN_ANCHORAGE_TIME`, `MEDIAN_PORT_TIME` (`IN_PORT_TIME`), derived from 4 geofenced timestamps (anchorage arrival/departure, port arrival/departure)<br>**Expected Arrivals**: `SHIP_ID`, `MMSI`, `IMO`, `SHIP_NAME`, `SHIP_TYPE` / `SHIP_CLASS`, `ORIGIN_PORT_ID` / `FROM_PORT`, `DEST_PORT_ID`, `ETA` (UTC), `PREDICTED_ETA` / `VI07_ETA`, `SPEED` (`knots x10`), `DRAUGHT`, `NAV_STATUS`<br>*(Exact full field matrix for all `VI06` percentile buckets requires service-specific parameter testing in sandbox)* |
| **Update Cadence** | **2-minute minimum refresh interval** (entity-level cache window) for standard polling endpoints (`PS07`, port feeds); repeat queries inside the refresh window return cached responses at **0 credit cost** |
| **Rate Limits & Quotas** | Technical safety cap typically **max 100 requests/minute per API key** alongside contract-tier successful-call caps; returns `402 Not Enough Credits` (`notEnoughCredits`) or `429 Too Many Requests` (`quotaExceeded` / `throttled`) |
| **Pricing Tiers** | Prepaid **credit-consumption model** (credits per response row/object; `msg_type=extended` consumes more credits). API plans are sold separately from web subscriptions (Basic / Essential / Enterprise quotes via sales) |
| **Developer Sandbox** | New API accounts receive an initial allocation of **free trial credits** for testing `PS07`/`EV01`/`VI06`, plus OpenAPI schema inspection in the portal; heavy analytics endpoints require commercial sales scoping |

---

## 2. Container Milestones & Ocean Visibility: Project44 vs. Vizion

Operational relevance: Detecting transshipment rollovers, port-call omissions, Change of Destination (`COD`) eligibility windows, and container-level ETA slippage before customs filings (`Mirsal 2`, `ATLP`, Oman `Bayan` e-TIR) lock in.

### 2.1 Project44 (Ocean Visibility API v4)

| Dimension | Verified Public Detail / Boundary Status |
| :--- | :--- |
| **Docs & Portals** | `https://developers.project44.com/` (also referenced as `developer.project44.com/docs`) |
| **Protocols & Endpoints** | REST JSON:<br>• `GET /api/v4/ocean/shipments` & `/api/v4/ocean/shipments/{id}` & `.../statuses`<br>• `GET /api/v4/shipments/{shipmentId}/tracking/history` (requires `masterShipmentId`)<br>• `GET /api/v4/shipments/{shipmentId}/eventhistory`, `.../positionhistory`, `.../tracking`<br>• `PUT /api/v4/webhooks` (push registration) |
| **Authentication** | **OAuth 2.0 Client Credentials** (`client_id` + `client_secret` -> Bearer token); webhook callbacks support `API_KEY` (`authType: "API_KEY"`), `authenticationMethods`, or Azure SAS |
| **DCSA Alignment** | Aligns semantically with DCSA concepts, but **webhooks and REST envelopes use project44's Unified Shipment Schema** rather than native DCSA callback specifications |
| **Publicly Documented Schema Fields** | **Webhook Config (`PUT /api/v4/webhooks`)**: `authParams`, `authType`, `authenticationMethods` (`[{parameters, type}]`), `configName`, `id`, `method`, `methodParams`, `payloadFormat` (`"JSON"`), `url`, `version`<br>**`TrackedShipmentHistory`**: `states` (`TrackedShipmentState[]`), `events` (`TrackedShipmentEvent[]`, chronological ascending), `positions`<br>*(Granular/Unified delta webhook payload keys & exact COD/rollover enum strings **require commercial onboarding / sandbox verification**)* |
| **Update Cadence** | Event-driven push via Standard webhooks (full history object on change) or Granular/Unified delta webhooks with built-in retry logic; carrier/AIS polling cadence behind the scenes is not publicly fixed |
| **Rate Limits** | Enforced per consumer key / org tier (`429 Too Many Requests`). Exact req/sec numbers are **not publicly published**; docs mandate webhooks over `GET` polling |
| **Pricing Tiers** | B2B enterprise SaaS annual contract based on active container volume and multi-modal scope. No self-serve pricing table |
| **Developer Sandbox** | Sandbox provisioned only after enterprise/partner account onboarding (plus representative coordination to finalize `PUT /api/v4/webhooks`) |

### 2.2 Vizion (Container Tracking API)

| Dimension | Verified Public Detail / Boundary Status |
| :--- | :--- |
| **Docs & Portals** | `https://docs.vizionapi.com/` (ReadMe OpenAPI hub) |
| **Protocols & Endpoints** | REST JSON + Event-driven Webhooks:<br>• `POST /references` (subscribe via container + SCAC, Master B/L, or auto-carrier ID, passing `callback_url`)<br>• `GET /references/{reference_id}/updates` (fallback polling) |
| **Authentication** | REST: API key in request headers<br>Webhooks: Restricted source IP allowlisting + **HMAC HTTP signature** (TTL expiration, body digest hash, hex signature); Pro/Enterprise adds Basic Auth, Bearer, custom API key, or OAuth 2.0 Client Credentials |
| **DCSA Alignment** | Native **DCSA-compliant milestone & location mapping** toggleable at no extra cost in both sandbox and production |
| **Publicly Documented Schema Fields** | **Webhook Envelope**: `id`, `status` (`"data_received"`), `reference_id`, `organization_id`, `created_at`, `updated_at`, `parent_reference_id`, `payload`<br>**`payload` object**: `carrier_scac`, `container_id`, `container_iso`, `origin`, `destination`, `milestones[]`<br>**`milestones[]` item**: `timestamp`, `description`, `location`, `journey_event` (`journey_type`: `EQUIPMENT`/`TRANSPORT`/`SHIPMENT`; `event_classifier`: `ACT`/`EST`; `event_type`: `LOAD`/`DISC`/`ARRI`/`DEPA`; `empty_indicator`: `LADEN`/`EMPTY`; `transport_mode`: `VESSEL`/`RAIL`/`TRUCK`/`BARGE`; `facility_type`: e.g. `POTE`), `shipment_location.type_code` (`POL`, `POD`, `RTP`)<br>*(Exact internal keys for delay delta / Change of Destination flags beyond `RTP` transshipment & `EST`/`ACT` timestamps **require commercial onboarding / sandbox verification**)* |
| **Update Cadence** | Real-time asynchronous webhook push (`POST` to `callback_url`, requires `2XX` ack; auto-retry on non-`2XX`) sourced from carriers, terminals, customs, and terrestrial/satellite AIS. Exact SLA latency **requires commercial onboarding / sandbox verification** |
| **Rate Limits** | Tier-based throttling returning `429 Too Many Requests`; exact req/min thresholds **require commercial onboarding / sandbox verification** |
| **Pricing Tiers** | Tiered plans: **Starter / Free-to-Try** (small monthly container block), **Core** (ocean carriers, auto-ID, location enrichment, webhooks, DCSA codes), **Professional / Enterprise** (higher container caps, rail data, custom webhook auth). Exact USD rates are sales-quoted (not published on `docs.vizionapi.com`) |
| **Developer Sandbox** | Separate **Demo / Sandbox environment** with DCSA formatting enabled free of charge via support; local callback testing documented with webhook inspection utilities |

---

## 3. Cold-Chain IoT Reefer Telemetry: ORBCOMM vs. Carrier Lynx

Operational relevance (`DisruptionState.reefer_fault`, `reefer_ambient_drift_c_per_hour`, `CorridorEdge.thermal_drift_c_per_hour`, `ShipmentSpec.initial_temp_c` / `max_temp_c`):
- For pharma/biologics (`HS 3004`, `2°C–8°C`), a compressor trip, shore-power loss during port transfer (`AEFJR` / `OMSOH`), or unsealed door event triggers `reefer_fault = True` and escalates `reefer_ambient_drift_c_per_hour` so Z3/HiGHS immediately prices spoilage exposure and shifts the shipment onto `ETIHAD_RAIL_BONDED` + `AIR_CARGO` (`AEAUH` -> `EUFRA`).

### 3.1 ORBCOMM (ReeferConnect / VesselConnect)

| Dimension | Verified Public Detail / Boundary Status |
| :--- | :--- |
| **Docs & Portals** | `https://www.orbcomm.com` and authenticated **ORBCOMMunity Portal** (OpenAPI/SDK specs are gated behind customer login) |
| **Protocols & Hardware** | Web services APIs for **ReeferConnect** (land/rail/yard) and **VesselConnect** (shipboard LoRa/gateway) paired with **CT 3500 / CT 3600** devices; DCSA IoT interoperability alignment |
| **Authentication** | Tenant/sub-account scoped server-to-server credentials (API keys / OAuth 2.0 / Basic Auth); exact header names **require commercial onboarding / sandbox verification** |
| **Publicly Documented Schema Fields** | Public product literature confirms telemetry coverage for: ISO container ID, GPS coordinates, supply/return air temperatures, ambient temperature, setpoint, humidity, O2/CO2 (CA), reefer ON/OFF & defrost state, alarm/fault codes, battery voltage, and door open/closed state.<br>**Exact JSON key names, webhook envelope, and fault code enums are NDA/portal-gated and require commercial onboarding / sandbox verification** |
| **Update Cadence** | Configurable reporting intervals typically **15 minutes to 1 hour** over global LTE/4G cellular (with optional satellite IoT fallback and shipboard VesselConnect gateway bridging at sea) |
| **Rate Limits & SLA** | Commercial uptime SLA target of **99%**; per-fleet polling/burst throttling is custom-configured per contract |
| **Pricing Tiers** | Custom enterprise quote tied to hardware units (CT 3500/3600), fleet size, and cellular/satellite data plans |
| **Developer Sandbox** | No public self-serve sandbox; staging credentials and mock device feeds provisioned via PoC/commercial agreement |

### 3.2 Carrier Transicold — Lynx Fleet API

| Dimension | Verified Public Detail / Boundary Status |
| :--- | :--- |
| **Docs & Portals** | Developer Portal: `https://portal.fleet.lynx.carrier.io`<br>API Docs Host: `https://doc-api.fleet.lynx.carrier.io` (OpenAPI 3.0.0 specs behind authenticated portal login) |
| **Protocols & Endpoints** | REST OpenAPI 3.0.0 + **Lynx Push API (Webhooks)** for Truck/Trailer TRU (`APX` controls) and Marine Container telemetry |
| **Authentication** | Incoming Push API webhook payloads carry the documented header **`x-lynx-api-key`**; REST portal calls use tenant-provisioned token auth |
| **Publicly Documented Schema Fields** | Documented sensor/stream domains & gateway-parsed structure:<br>• **Envelope**: `eventId`, `eventType` (e.g., `TRU_STATUS_UPDATE`, `ALARM_TRIGGERED`, `LOCATION_CHANGE`, `GEOFENCE_EVENT`), `timestamp` (ISO 8601), `version`<br>• **Asset/Location**: `assetId`, `deviceId`, `assetName`/`unitNumber`, `location` (`latitude`, `longitude`, `speed`, `heading`, `timestamp`)<br>• **Refrigeration (`truData`/`refrigeration`)**: `operatingMode`, `setPointTemp`, `returnAirTemp`, `supplyAirTemp`, `ambientTemp`, `batteryVoltage`, `fuelLevel`, `alarmStatus`<br>• **Alarms**: `alarms[]` (`alarmCode`, `description`, `severity`, `active`)<br>*(Note: Exact property casing/nesting in Carrier's private marine container OpenAPI 3.0.0 schema beyond `x-lynx-api-key` and sensor categories **requires commercial onboarding / sandbox verification**; onboarding lead time is typically **2–4 weeks** via `lynx-support@carrier.com`)* |
| **Update Cadence** | Event-driven Push API recommended by Carrier for **sub-30-minute** ingestion requirements (e.g., pharma cold chain); instant push on temperature excursion, door open, or alarm triggers |
| **Rate Limits** | Enforced per tenant API key; exact req/min ceilings are surfaced dynamically in the authenticated portal profile |
| **Pricing Tiers** | Bundled with active Carrier Lynx Fleet telematics hardware/service subscriptions; high-frequency enterprise pipelines quoted via Carrier Transicold |
| **Developer Sandbox** | Interactive portal explorer available to provisioned tenants; live simulated TRU/container push streams require coordination with `lynx-support@carrier.com` |

---

## 4. Freight Rates, Surcharges & Air Capacity: Xeneta vs. WebCargo (by Freightos)

Operational relevance: Parameterizing `DisruptionState.red_sea_surcharge_usd`, `CorridorEdge.base_cost_per_teu_usd`, and live air-bridge capacity/rate for `E_AEAUH_EUFRA_AIR` (`AEAUH` -> `EUFRA`, plus `AEDWC` RFS feeder option).

### 4.1 Xeneta (Ocean & Air Freight Market Intelligence API v3)

| Dimension | Verified Public Detail / Boundary Status |
| :--- | :--- |
| **Docs & Portals** | `https://xeneta.readme.io/reference` |
| **Protocols & Endpoints** | Standard **REST over HTTPS** returning JSON (no GraphQL API):<br>• `GET /v3/ocean/market-rates`<br>• `GET /v3/ocean/surcharges`<br>*(Exact sub-paths for air benchmarks & regional sub-filters require portal key verification)* |
| **Authentication** | API Key header (`apiKey` or Bearer token configured in portal) |
| **Publicly Documented Schema Fields** | **Query Params**: `origin` & `destination` (UN/LOCODE or region), `market` (`short-term`, `long-term`), `container_type` (`40HC`, `20DC`, reefer), `surcharge_types` (`fuel` [BAF], `red-sea`, `eu-ets`, `congestion`, `pss`)<br>**Response Spread**: Market dispersion quantiles (`low`, `mid_low`, `average`, `mid_high`, `high`) for freight rates and independent surcharge objects (`type`, `name`, `values`), plus `currency`, `updated_at`<br>*(Note: Xeneta explicitly models `red-sea` surcharges independently from all-in rates because carrier surcharge applicability varies dynamically)* |
| **Update Cadence** | **Daily** dataset refresh aggregating crowdsourced shipper/forwarder contract & spot data (plus 3-month and 6-month market outlook) |
| **Rate Limits** | Enforced per enterprise agreement; exact req/min limits **require commercial onboarding / sandbox verification** |
| **Pricing Tiers** | Paid enterprise SaaS subscription; no public self-serve pricing or free tier |
| **Developer Sandbox** | No open public sandbox with live rate data; sandbox/production tokens provisioned via Xeneta commercial contract |

### 4.2 WebCargo by Freightos (`developers.freightos.com`)

| Dimension | Verified Public Detail / Boundary Status |
| :--- | :--- |
| **Docs & Portals** | `https://developers.freightos.com/` (also `https://developer.freightos.com`) |
| **Protocols & Capabilities** | REST JSON APIs split between:<br>• **Public / Index APIs**: Carbon calculator, **FAX (Freightos Air Index)** spot benchmark<br>• **Partner-Gated Transactional APIs**: Live airline capacity search, dynamic spot & contract rates, allotment lookups, **eBooking** & auto-AWB/eAWB execution across 55–75+ airlines (including **Etihad Cargo** via IBS iCargo for **`AUH`**, **`DWC`** Road Feeder Service, and EU destinations such as **`FRA`**) |
| **Authentication** | App registration in Freightos Developer Portal (`My Apps`) -> approved API Keys / OAuth credentials |
| **Publicly Documented Schema Fields** | Because WebCargo's transactional rate/capacity and eBooking OpenAPI specs are partner-gated behind portal approval, **exact REST paths and JSON request/response keys for `AUH`/`DWC` -> `FRA` spot search and eBooking require commercial onboarding / sandbox verification** |
| **Update Cadence** | Real-time airline host queries (live dynamic spot pricing, flight/RFS schedules, ULD availability, temperature-controlled capability) for transactional calls; periodic index updates for FAX |
| **Rate Limits** | Strict request throttling per registered app tier returning `429 Too Many Requests`; docs advise caching static schedules because live airline queries are expensive |
| **Pricing Tiers** | Partner / forwarder commercial agreement with Freightos (`support@freightos.com`); public carbon/index APIs available on portal |
| **Developer Sandbox** | Dedicated staging/sandbox credentials provisioned case-by-case for approved forwarder/TMS partners to test rate search and eBooking without booking live capacity |

---

## 5. Side-by-Side Comparison & Phase-1 vs. Phase-3 Recommendation

| Category | Provider A | Provider B | Auth & Protocol | Update Cadence | Sandbox / Self-Serve | Recommendation |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. AIS & Port Congestion** | **Spire Maritime (Kpler)** | **MarineTraffic (Kpler)** | Spire: GraphQL (`Bearer`) / REST (`X-API-Key`)<br>MT: REST (`X-API-Key`) | Spire: Sub-min LEO+terrestrial AIS<br>MT: **2-min cache window** (`VI06` / `PS07`) | Spire: Sales demo only<br>MT: **Free trial credits on signup** | **MVP / Phase-1: MarineTraffic** (`VI06` + `EV01` + `PS07` trial credits, explicit `UNLOCODE` congestion/wait-time metrics for `AEFJR`, `AEJEA`, `OMSOH`, `OMSLL`).<br>**Phase-3: Spire/Kpler GraphQL** for continuous LEO satellite fleet-wide Hormuz dark-vessel/AIS anomaly streams. |
| **2. Container Milestones** | **Project44** | **Vizion** | p44: OAuth 2.0 + `PUT /api/v4/webhooks`<br>Vizion: API Key + HMAC signed webhooks | Both: Event-driven webhooks (p44 also Granular deltas) | p44: Enterprise onboarding only<br>Vizion: **Demo sandbox + free DCSA toggle** | **MVP / Phase-1: Vizion** (native DCSA `journey_event`/`shipment_location` codes `LOAD`/`DISC`/`ARRI`/`DEPA` & `POL`/`POD`/`RTP`, HMAC webhooks, transparent Starter/Core path).<br>**Phase-3: Project44** for multi-modal inland truck/rail + enterprise shipper ERP integration. |
| **3. Cold-Chain Reefer IoT** | **ORBCOMM** | **Carrier Lynx Fleet** | ORBCOMM: Portal-gated API Key/OAuth<br>Lynx: OpenAPI 3.0.0 + Push (`x-lynx-api-key`) | ORBCOMM: 15–60 min (cell/sat/VesselConnect)<br>Lynx: **Sub-30 min Push API** | ORBCOMM: PoC/sales only<br>Lynx: Portal explorer + `lynx-support@carrier.com` (2–4 wk setup) | **MVP / Phase-1: Carrier Lynx Push API** (sub-30-min event-driven webhooks with `x-lynx-api-key` verification for pharma `2°C–8°C` alarms).<br>**Phase-3: ORBCOMM** (`VesselConnect` + `CT 3500/3600`) for cross-carrier deep-sea satellite reefer coverage. |
| **4. Rates & Air Capacity** | **Xeneta** | **WebCargo (Freightos)** | Xeneta: REST v3 (`apiKey`)<br>WebCargo: Portal App Key / OAuth (partner-gated) | Xeneta: **Daily** market & surcharge refresh<br>WebCargo: **Real-time** airline spot/capacity | Xeneta: Enterprise contract only<br>WebCargo: Partner-gated sandbox + public FAX index | **MVP / Phase-1: WebCargo/Freightos** (FAX air index + partner-gated Etihad Cargo `AUH`/`DWC` -> `FRA` capacity & e-AWB booking) **paired with cached daily Xeneta** (`red-sea` + `short-term` ocean benchmarks).<br>**Phase-3: Dual live integration** with automated contract-vs-spot arbitrage in HiGHS MILP. |

---

## 6. Integration Architecture (`services/gateway-go` -> `services/solver-py`)

### 6.1 Latency SLA Invariant (`<400ms P99`)
Per `AGENTS.md`, the synchronous `/api/v1/solve` pipeline must stay under **400ms P99** (with Stage 1 Go Gateway ingest `<10ms` and Stage 4 Z3+HiGHS `<200ms`). **External telemetry APIs must never be called inline during `POST /api/v1/solve`.** Instead:
1. `services/gateway-go` maintains an **in-memory + checkpointed `TelemetrySnapshot` store** (protected by `sync.RWMutex` alongside `WorkflowStore` in `services/gateway-go/workflow.go`).
2. External providers push events asynchronously via webhooks or are polled on background timers (`2m` for MarineTraffic `VI06`/`EV01`; `daily` for Xeneta; on-demand cached lookup for WebCargo) and folded into the latest `DisruptionState` and `CorridorEdge` overrides.
3. Every snapshot update triggers an SSE broadcast (`event: telemetry_update`) on `GET /api/v1/events` so `apps/command-center` updates live radar overlays and re-triggers `/api/v1/solve` in `<400ms`.

### 6.2 Proposed Endpoints in `services/gateway-go/main.go`

Following the Go 1.22+ `http.ServeMux` method-routing style in `GatewayServer.Routes()`:

```go
// Inbound push webhooks (external provider -> gateway-go)
mux.HandleFunc("POST /api/v1/telemetry/webhooks/vizion", g.handleVizionWebhook)       // Verifies HMAC signature + 200 OK ack
mux.HandleFunc("POST /api/v1/telemetry/webhooks/carrier-lynx", g.handleLynxWebhook)  // Verifies x-lynx-api-key header
mux.HandleFunc("POST /api/v1/telemetry/webhooks/project44", g.handleP44Webhook)      // Verifies API_KEY / bearer auth

// Telemetry state & background poll trigger (command-center / cron -> gateway-go)
mux.HandleFunc("GET /api/v1/telemetry/state", g.handleGetTelemetryState)             // Returns current DisruptionState + EdgeOverrides
mux.HandleFunc("POST /api/v1/telemetry/refresh", g.handleRefreshPollingProviders)    // Triggers async MarineTraffic VI06 / Xeneta poll
```

### 6.3 Field Mapping: External Telemetry -> `DisruptionState` & `CorridorEdge`

Target models in `services/solver-py/app/models.py`:
- `DisruptionState`: `hormuz_delay_hours` (`0..240`), `jebel_ali_congestion_hours` (`0..168`), `red_sea_surcharge_usd` (`0..10000`), `reefer_fault` (`bool`), `reefer_ambient_drift_c_per_hour` (`0..5.0`), `require_cepa_zero_tariff` (`bool`).
- `CorridorEdge`: `base_hours`, `base_cost_per_teu_usd`, `thermal_drift_c_per_hour`, `capacity_teu`, `active_cold_chain`.

| Source Provider & Verified Field / Signal | Transformation / Normalization Rule | Target Field in `models.py` | Affected Corridor Nodes / Edges (`network.py`) |
| :--- | :--- | :--- | :--- |
| **MarineTraffic `VI06` & `EV01`**<br>`UNLOCODE="AEJEA"`, `MEDIAN_ANCHORAGE_TIME`, `MEDIAN_PORT_TIME`, `CALL_COUNT` | Convert median anchorage + dwell hours; **if `CALL_COUNT` drops >50% vs 30d baseline at `AEJEA`**, flag Hormuz blockade risk rather than zero congestion | `DisruptionState.jebel_ali_congestion_hours`<br>`DisruptionState.hormuz_delay_hours` | `AEJEA`, `E_INNSA_AEJEA_SEA` (`passes_hormuz=True`, `touches_jebel_ali=True`) |
| **MarineTraffic `VI06`**<br>`UNLOCODE in {"AEFJR","OMSOH","OMSLL"}`, `MEDIAN_ANCHORAGE_TIME`, `VESSEL_COUNT` | Convert hours at anchorage/berth; add delta above nominal port call baseline to edge transit time | `CorridorEdge.base_hours` (dynamic edge override) | `E_INNSA_AEFJR_SEA`, `E_INNSA_OMSOH_SEA`, `E_INNSA_OMSLL_SEA` |
| **Spire/Kpler GraphQL (`vessels`)**<br>`position.{latitude,longitude,speed}`, `voyageData.eta`, `port.unlocode` | Detect vessel loitering (`speed < 1.5 kn`) or AIS dark gaps in Strait of Hormuz bounding box (`lat 25.8–26.8, lon 55.8–57.0`) | `DisruptionState.hormuz_delay_hours` (clamped `0..240`) | `E_INNSA_AEJEA_SEA` |
| **Vizion Webhook (`milestones[]`)**<br>`journey_event.{event_classifier,event_type}`, `shipment_location.type_code=="RTP"`, `timestamp` | Compare `EST` vs `ACT` arrival/discharge timestamps at `RTP` (`AEFJR`/`OMSOH`/`AEJEA`); detect missed feeder cutoff or vessel omission | Updates active `CorridorEdge.base_hours` and triggers re-solve for `ShipmentSpec.max_transit_hours` | Active sea/rail handoff legs (`E_INNSA_*` -> `E_AEFJR_*` / `E_OMSOH_*`) |
| **Carrier Lynx Push API**<br>`truData.{returnAirTemp,supplyAirTemp,setPointTemp,ambientTemp}`, `alarms[].{alarmCode,severity,active}`, `eventType` | Set `reefer_fault = True` if `any(a.active and a.severity == "Critical")` or `returnAirTemp > ShipmentSpec.max_temp_c`; compute observed drift `dT/dt` clamped `0..5.0` | `DisruptionState.reefer_fault`<br>`DisruptionState.reefer_ambient_drift_c_per_hour`<br>`ShipmentSpec.initial_temp_c` | All active container legs; Z3 checks predicted arrival temp `<= ShipmentSpec.max_temp_c` |
| **ORBCOMM (`ReeferConnect`/`VesselConnect`)**<br>Temperature, power/compressor alarms, door-open telemetry *(exact keys gated)* | Same normalization pipeline via adapter layer; map ocean leg `VesselConnect` power-loss alert to `reefer_fault = True` | `DisruptionState.reefer_fault`<br>`CorridorEdge.thermal_drift_c_per_hour` | Deep-sea legs (`E_INNSA_*_SEA`, `E_AEJEA_EUFRA_SEA`, `E_AEKHL_EUFRA_SEA`) |
| **Xeneta REST v3 (`/v3/ocean/surcharges`, `/v3/ocean/market-rates`)**<br>`surcharges[type="red-sea"].values.average`, `freight_rate.average` | Map `red-sea` average USD/FEU (or scaled /TEU) into surcharge field (clamped `0..10000`); update sea leg spot cost | `DisruptionState.red_sea_surcharge_usd`<br>`CorridorEdge.base_cost_per_teu_usd` | `E_AEJEA_EUFRA_SEA`, `E_AEKHL_EUFRA_SEA` |
| **WebCargo by Freightos / FAX**<br>Etihad Cargo live spot rate & ULD availability for `AUH`/`DWC` -> `FRA` *(exact keys gated)* | Update air bridge unit cost (`USD/kg` converted to TEU-equivalent payload weight) and available ULD capacity | `CorridorEdge.base_cost_per_teu_usd`<br>`CorridorEdge.capacity_teu` | `E_AEAUH_EUFRA_AIR` (and `AEDWC` node expansion in Phase 1/2) |
