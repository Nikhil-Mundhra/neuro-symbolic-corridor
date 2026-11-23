# Agent 3 Specification: DCSA eBL 3.0, IATA ONE Record, and GCC Customs Contracts

> **Source**: Agent 3 (Part A — External EDI & JSON Schema Lookup)
> **Target Integration (Part B)**: `services/solver-py/app/models.py`, `services/solver-py/app/parser.py`, `services/solver-py/app/customs_payloads.py`, `services/gateway-go/workflow.go`, `apps/command-center/src/types.ts`

## Overview
Upgrading ingestion, validation, and GCC customs contracts to decouple internal shipment records from carrier-specific wire formats and enforce the Zero Regulatory Hallucination Invariant (no silent fallback HS codes or CEPA origin percentages).

### Key 2026 Regulatory Shifts
1. **12-Digit HS Tariff Codes**: UAE Federal Customs Authority (Mirsal 2) and Oman Customs (Bayan) enforce 12-digit HS codes (`^\d{12}$`) in 2026; legacy 6/8-digit codes cannot be zero-padded and must be rejected/held on GCC legs.
2. **Dual UAE Single Windows**: No unified UAE national customs single window exists as of mid-2026; Dubai Trade (**Mirsal 2**) and Abu Dhabi (**ATLP / Maqta Gateway**) operate separate stacks. UAE Pass authentication became mandatory for Mirsal 2 on 10 May 2026 alongside Digital MAKASA Phase 1 (25 Jan 2026) and MPCI 72h pre-load checks.
3. **IATA ONE Record + XFWB Bridge**: IATA ONE Record (JSON-LD under `https://onerecord.iata.org/ns/cargo#`, API 2.2.0 / Cargo Data Model 3.2) became IATA's preferred voluntary standard on 1 Jan 2026, while customs filings still require Cargo-XML XFWB / EU ICS2 bridging.
4. **DCSA eBL 3.0**: OpenAPI 3.0.x REST conventions (`PascalCase` objects, `camelCase` fields, `UPPER_SNAKE_CASE` enums, RFC 3339 timestamps, ISO 6346 container IDs).

### Schema Verification Boundaries (Require Partner B2G Artifacts)
- Private B2G XML/JSON schemas for **Mirsal 2**, **Maqta Gateway ATLP**, and **Etihad Rail**.
- Full **UNECE eTIR v4.3** XSD element tree beyond `I7/I8 /Declaration/Consignment`.
- Exact **DCSA eBL 3.0** OpenAPI property names beyond `TransportDocument`, `documentParties`, and `utilizedTransportEquipments`.
- EU EORI country-specific regexes and 7-digit IMO ship check-digit verification.

---

## Canonical Data Contracts & Validation Invariants
- **Canonical Wire Schema**: `ShipmentRequest` (with `PartyIdentification`, `ConsignmentItem`, `OriginPreferenceSpec`, `ReeferSpecification`, `HazmatSpecification`, `UtilizedTransportEquipment`, `TransportLeg`, `ChangeOfDestinationSpec`) and blocking response `ValidationHold` / `MissingComplianceField` — mirrored 1:1 in Python (`models.py`), TypeScript (`contracts.ts` / `types.ts`), and Go (`workflow.go`).
- **Deterministic Checksums & Formats**:
  - `validate_iso6346`: 11-char `^[A-Z]{3}[UJZ]\d{7}$` with base-2 positional weighting and mod-11 check digit (remainder 10 -> 0).
  - `hs_code_gcc12`: `^\d{12}$` (mandatory on `AE*` / `OM*` legs); `hs_code_wco6`: `^\d{6}$`.
  - `uae_trn`: `^100\d{12}$` (15 digits starting with `100`, plus `uae_trn_fta_verified`).
  - `dubai_customs_code`: `^AE-\d{7}$`.
  - `stowage_baplie_pos`: `^\d{7}(?:[A-Z]{2})?$` (SMDG `BBBRRTT[DD]`).
  - `ChangeOfDestinationSpec`: validates `vessel_imo` (`^IMO\d{7}$`), `container_iso6346`, `stowage_baplie_pos`, `accessible_without_restow` consistency with `estimated_restow_moves == 0`, and `cod_request_submitted_utc <= carrier_cod_cutoff_utc`.

---

## Zero-Hallucination Parser State Machine (`parser.py`)
Five-state pipeline:
1. `RAW_INGESTED`: Normalize text encoding and identify document roles (Invoice, Packing List, B/L, AWB).
2. `FIELD_EXTRACTION`: Extract candidate tokens across documents **with zero fallback defaults**; retain multiplicity to detect cross-document conflicts.
3. `STRUCTURAL_VALIDATION`: Pydantic v2 `ShipmentRequest.model_validate`, mapping `ValidationError` into `MissingComplianceField`.
4. `COMPLIANCE_GATE`:
   - Tariff Classification Gate (WCO 6 globally; GCC 12-digit on `AE*`/`OM*` legs).
   - Cross-Document Consistency Gate (`CONFLICTING_DOCUMENT_VALUES`).
   - Origin & CEPA Gate (`certificate_of_origin_no` mandatory on GCC; `cepa_value_add_pct` mandatory if `preferential_cepa_claimed=True`).
   - Cold-Chain & Hazmat Gate (`reefer_spec` bounds; `msds_document_ref` & `un383_certified` for DG).
   - TRN & EORI Gate (`uae_trn` for `AE` parties; `eori_number` for EU-bound/EU-established parties).
   - MOFAIC Invoice Attestation Gate (`mofaic_attested_invoice=True` when Dubai clearance value `>= AED 10,000`).
5. `READY_FOR_DISPATCH / VALIDATION_HOLD`: Any issue returns `ValidationHold(autonomous_dispatch_blocked=True, requires_human_review=True)`.

---

## Customs & Carrier Payload Builders (`customs_payloads.py`)
1. `build_mirsal2_declaration`: Dubai Trade / Mirsal 2 (`UAE_PASS` session, `AE-XXXXXXX`, MPCI preload ref, Digital MAKASA flag, 12-digit HS items, MOFAIC attestation).
2. `build_atlp_etihad_rail_manifest`: Maqta Gateway ATLP + Etihad Rail (AEO sharing ID, inland rail customs clearance point, wagon-to-ISO6346 container map).
3. `build_oman_bayan_and_etir_manifest`: Oman Royal Customs Bayan (`OMSOH`/`OMSAL` transit, OMR 15.000 fee, CR number, insured guarantee bank) + UNECE eTIR v4.3 `I7_RecordDeclarationData` skeleton.
4. `build_iata_one_record_and_xfwb_bridge`: IATA ONE Record JSON-LD `@graph` (`cargo:Waybill`, `cargo:Booking`, `cargo:TransportMovement`, `cargo:Shipment`, `cargo:Piece` with XFWB `goodsDescription` granularity rule) + `Cargo-XML_XFWB3_and_EU_ICS2` regulatory bridge.
