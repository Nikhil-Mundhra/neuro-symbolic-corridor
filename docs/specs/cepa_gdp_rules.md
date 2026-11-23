# Agent 1 Specification: Regulatory & Cold-Chain Formal Verification (Chapter 30 Biologics)

> **Source**: Agent 1 (Part A — Regulatory & Cold-Chain Spec Gathering)
> **Target Integration (Part B)**: `services/solver-py/app/z3_compiler.py`

## Overview
Formal Verification and Trade Compliance Specification: Chapter 30 Biologics Upgrade for the `INNSA–GCC–EUFRA` Neuro-Symbolic Corridor Solver.

Upgrading `services/solver-py/app/z3_compiler.py` from a 4-rule scalar prototype to a Quantifier-Free Linear Real and Integer Arithmetic (`QF_LIRA`) specification for Chapter 30 pharmaceutical goods (`HS 3002.15`) moving along `INNSA → GCC → EUFRA`:

1. **Preferential Origin & Consignment Integrity (India–UAE CEPA Chapter 3 & Annex 3B)**
2. **GCC Customs Transit & Seal State Machines (IRU e-TIR Annex 11 & GCC Makasa & UAE Mirsal-2)**
3. **EU ICS2 Release 3 Pre-Loading (PLACI) & Pre-Arrival (ENS) Security Gates (Art. 106 UCC DA)**
4. **Piecewise Cold-Chain Physics & Linearized Haynes MKT (EU GDP 2013/C 343/01 Ch. 9, USP `<1079.2>`, Envirotainer RKN e1 / RAP e2 / RKN t2)**

---

## 1. UAE–India CEPA Chapter 3 & Annex 3A/3B Formalization

### 1.1 Statutory Citation Reconciliation and Tariff Classification Ontology
- **Annex 3A vs. Annex 3B**: Official India–UAE CEPA text (in force May 1, 2022; CBIC Notification No. 39/2022-Customs (N.T.)) places Minimum Required Information for COO in **Annex 3A** and Product-Specific Rules of Origin (PSRs) in **Annex 3B** (Annexure-B).
- **Article 3.12 vs. Article 3.14**: Article 3.12 (Transport) governs direct consignment, third-country transit, and customs control; Article 3.13 governs Proof of Origin; Article 3.14 governs Certificate of Origin and Certification Procedures (5-working-day issuance window, retrospective issuance, 12-month validity).
- **HS 2022 Chapter 30 Note 2 Subheadings**:
  - `3002.12`: Antisera and other blood fractions (excludes whole human blood `3002.90`).
  - `3002.13`: Immunological products, unmixed, not put up in measured doses or retail packings (bulk drug substance).
  - `3002.14`: Immunological products, mixed, not put up in measured doses or retail packings (bulk formulated drug product).
  - `3002.15`: Immunological products, put up in measured doses or in forms/packings for retail sale (finished mAb therapeutics in sterile vials/pens/syringes; excludes insulin `3004.31` and vaccines `3002.41`).
  - `3002.41`: Vaccines for human medicine.
  - `3002.51`: Cell therapy products (CAR-T / ATMPs).

### 1.2 Product-Specific Rules of Origin (PSRs) for HS 3002.15
- **Conjunctive Dual Requirement**: 6-digit Change in Tariff Sub-Heading (`CTSH`) + Qualifying Value Content (`QVC`) of `>= 40%` FOB (or `>= 35%` EXW), with final manufacture in India and compliance with Article 3.5 (Minimal Operations).
- **CTSH + Article 3.4 De Minimis**: Non-originating inputs sharing subheading `3002.15` must have aggregate CIF value `<= 10%` of `V_base` (`V_FOB` or `V_EXW`).
- **QVC Arithmetic**:
  - Method A (Build-Down): `(V_base - V_NOM) >= theta_basis * V_base`
  - Method B (Build-Up): `(C_OM + C_labour + C_overhead) >= theta_basis * V_base`
  - Bilateral cumulation (Art. 3.7) includes UAE originating inputs in `C_OM`. Retail packaging (Art. 3.8) is included; transport containers (e.g., Envirotainer RKN e1 / RAP e2) and indirect materials (Art. 3.10) are disregarded.
- **Article 3.5 Minimal Operations**: Importing non-originating `3002.13`/`3002.14` and merely diluting, repacking, or relabelling into `3002.15` does NOT confer origin.

### 1.3 Direct Consignment & Proof of Origin (Articles 3.12 & 3.14)
- Non-Party transit (`OMSOH` / `OMSAL`) requires: continuous customs control, non-entry into local trade/consumption, permitted preservation operations only, and documentary evidence (Certificate of Non-Manipulation or single through transport document).
- Article 3.14 COO must have unique serial number & official seal, be issued within 5 working days of export (or marked `ISSUED RETROSPECTIVELY` within 12 months), and imported within 12 months (365 days) of issue.

---

## 2. GCC Transit & EU ICS2 Release 3 Constraints

### 2.1 GCC Regimes
- **`ETIR_CROSS_BORDER`** (Oman–UAE overland): UNECE e-TIR Annex 11 temporal ordering:
  `t_E9 < t_I1 <= t_I7 < t_I9 < t_I15 < t_border_arrival <= t_I11 <= t_I13`
  - Error 310 prevention: `i7_contains_seal_id == False`.
  - Error 309 prevention: `duplicate_seal_in_registry == False`.
  - Error 321 prevention: `holder_authorized_in_itdb == True`.
  - Seal lineage: `i9_seal_id == i11_seal_id` unless customs inspection broke seal and recorded replacement in e-TIR.
- **`MAKASA_CROSS_BORDER`**: Single Point of Entry clearance + GCC Statistical Export Declaration + Makasa endorsement stamp + copy of first-entry import declaration + intact customs seal.
- **`UAE_BONDED_SEA_AIR`**: Mirsal-2 transit declaration + Dubai Customs smart e-seal + transfer duration within bond window + no entry into UAE mainland commerce.

### 2.2 EU ICS2 Release 3 (Article 106 UCC DA)
- **Phase 1 PLACI** (`F20`, `F24`, `F23+F25`, `F26`, `F28`): Lodged strictly before aircraft loading (`t_placi_lodged < t_loading`). Zero active `DNL`, zero unresolved `RFI`, and any `HRCM` flag must have completed enhanced screening.
- **Phase 2 Full ENS** (`F20`, `F21+F22`, `F21+F26`, `F27`, `F28`, `F29`):
  - Long-haul flight (`duration >= 4.0h`): `t_arrival_EUFRA - t_ens_complete >= 4.0h`
  - Short-haul flight (`duration < 4.0h`): `t_ens_complete <= t_takeoff`
  - Multiple filing linking keys: Carrier EORI, MAWB number, and House Declarant EORI must match across partial filings.

---

## 3. EU GDP Cold-Chain & Linearized Haynes MKT Physics

### 3.1 Three-Regime Thermal Exposure per Leg
Each leg is partitioned into `ARC`, `DWELL` (GCC tarmac/cross-dock, subject to optional EU GDP Ch. 9 hub dwell limit), and `INSPECT` (including unpowered door-open duration).

### 3.2 Linearized Haynes MKT via Normalized Degradation Factor (NDF)
- Haynes formula constants: `dH / R = 10,000 K`, reference CCT ceiling `T_lim = 8.0°C (281.15 K)`.
- Normalized Degradation Factor: `phi(T) = exp(10000 / 281.15 - 10000 / (T + 273.15))`.
- Strictly convex (`phi''(T) > 0`) on `[0°C, 50°C]`. 11-knot piecewise-linear secant over-approximation `(T_lo, T_hi, slope_m, intercept_c)`:
  - `(0.0, 2.0, 0.053788, 0.352848)`
  - `(2.0, 5.0, 0.073655, 0.313112)`
  - `(5.0, 8.0, 0.106204, 0.150370)`
  - `(8.0, 10.0, 0.142804, -0.142434)`
  - `(10.0, 12.0, 0.180683, -0.521223)`
  - `(12.0, 15.0, 0.241929, -1.256175)`
  - `(15.0, 20.0, 0.383178, -3.374910)`
  - `(20.0, 25.0, 0.662101, -8.953372)`
  - `(25.0, 30.0, 1.122849, -20.472069)`
  - `(30.0, 38.0, 2.205444, -52.949913)`
  - `(38.0, 45.0, 4.532236, -141.368010)`
- Enforced across **both** total route duration AND every **24-hour rolling window** ending at each phase.

### 3.3 Envirotainer SLA Curves & Excursion Limits
- **RKN e1 / RAP e2**: `30.0h` minimum SLA autonomy (`58.0h` / `60.0h` nominal); ambient drain multiplier `1.0` (`<=30°C`), `1.0 + 0.05*(T-30)` (`30-40°C`), `1.5 + 0.08*(T-40)` (`40-50°C`). Charging prohibited `< -20°C` or `> +40°C` (8h max charge, 100% eff in `[0, 20°C]`, 85% outside).
- **RKN t2**: `72.0h` fan battery ceiling + dry-ice sublimation tracking.
- **Hard Thermal Invariants**: `T_int >= 2.0°C` (freeze floor), `T_int <= 15.0°C` (USP `<1079.2>` spike ceiling), `<= 2.0h` cumulative excursion `> 8.0°C`.

---

## 4. Unsat Core Diagnostics Ontology
Every Z3 constraint is bound via `solver.assert_and_track(expr, label)` using domain-prefixed literals (`HS_CLASS::*`, `CEPA_ORIGIN::*`, `CEPA_TRANSIT::*`, `CEPA_COO::*`, `GCC_CUSTOMS::*`, `EU_ICS2::*`, `GDP_THERMAL::*`, `CONSIGNEE_SLA::*`) so `solver.unsat_core()` returns exact legal and physical root causes.
