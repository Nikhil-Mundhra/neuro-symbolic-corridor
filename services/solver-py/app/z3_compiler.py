"""Z3 SMT Symbolic Regulatory & Cold-Chain Compliance Compiler."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

import z3

from app.models import (
    CorridorEdge,
    DisruptionState,
    ShipmentSpec,
    TransportMode,
    Z3ProofCertificate,
    Z3RuleCheck,
)

# UAE-India CEPA Art. 3.15 requires >= 40% origin value-add for 0% preferential duty;
# non-qualifying shipments fall back to the 5% GCC MFN common external tariff.
CEPA_MIN_VALUE_ADD_PCT = 40.0
CEPA_MFN_PENALTY_RATE = 0.05
DWELL_THERMAL_DRIFT_C_PER_HOUR = 0.005

# 11-knot piecewise-linear secant over-approximation of Haynes Normalized Degradation Factor
# phi(T) = exp(10000/281.15 - 10000/(T + 273.15)) around T_lim = 8.0 C (docs/specs/cepa_gdp_rules.md).
HAYNES_NDF_KNOTS: tuple[tuple[float, float, float, float], ...] = (
    (0.0, 2.0, 0.053788, 0.352848),
    (2.0, 5.0, 0.073655, 0.313112),
    (5.0, 8.0, 0.106204, 0.150370),
    (8.0, 10.0, 0.142804, -0.142434),
    (10.0, 12.0, 0.180683, -0.521223),
    (12.0, 15.0, 0.241929, -1.256175),
    (15.0, 20.0, 0.383178, -3.374910),
    (20.0, 25.0, 0.662101, -8.953372),
    (25.0, 30.0, 1.122849, -20.472069),
    (30.0, 38.0, 2.205444, -52.949913),
    (38.0, 45.0, 4.532236, -141.368010),
)


@dataclass(frozen=True)
class Z3ConflictAnalysis:
    """Minimal conflict-set analysis extracted from Z3 unsat core for Benders lazy cuts."""

    is_global_infeasible: bool
    minimal_conflict_edge_sets: list[list[str]]
    unsat_core_labels: list[str]
    requires_dwell_for_violation: bool


def _haynes_secant_coeffs(temp_c: float) -> tuple[float, float]:
    """Return (slope, intercept) of the piecewise Haynes NDF secant containing temp_c."""
    clamped = max(0.0, temp_c)
    for _, t_hi, slope, intercept in HAYNES_NDF_KNOTS[:-1]:
        if clamped <= t_hi:
            return slope, intercept
    _, _, slope, intercept = HAYNES_NDF_KNOTS[-1]
    return slope, intercept


def _edge_arc_physics(
    edge: CorridorEdge,
    shipment: ShipmentSpec,
    disruption: DisruptionState,
) -> tuple[float, float]:
    """Return (arc_hours, arc_temp_delta_c) for a single corridor edge."""
    arc_hours = edge.base_hours
    if edge.passes_hormuz:
        arc_hours += disruption.hormuz_delay_hours
    if edge.touches_jebel_ali:
        arc_hours += disruption.jebel_ali_congestion_hours

    arc_temp_delta = 0.0
    if shipment.is_temp_sensitive:
        drift = edge.thermal_drift_c_per_hour
        if disruption.reefer_fault and edge.mode == TransportMode.SEA:
            # Maritime reefer fault drifts ambient heat until offloaded at Fujairah/Oman
            drift += disruption.reefer_ambient_drift_c_per_hour
        elif edge.mode in (
            TransportMode.GREEN_CORRIDOR_TRUCK,
            TransportMode.ETIHAD_RAIL_BONDED,
            TransportMode.AIR_CARGO,
        ):
            # Active shore power / PharmaLife active cooling stabilizes thermal excursion
            drift = edge.thermal_drift_c_per_hour
        arc_temp_delta = drift * arc_hours

    return arc_hours, arc_temp_delta


def compute_route_physics(
    edges: list[CorridorEdge],
    shipment: ShipmentSpec,
    disruption: DisruptionState,
    dwell_hours: float = 0.0,
) -> tuple[float, float, bool]:
    """Compute deterministic transit hours, arrival temperature, and continuous seal flag."""
    total_hours = dwell_hours
    temp_c = shipment.initial_temp_c
    if shipment.is_temp_sensitive and dwell_hours > 0.0:
        temp_c += DWELL_THERMAL_DRIFT_C_PER_HOUR * dwell_hours
    continuous_seal = True

    for edge in edges:
        arc_hours, arc_temp_delta = _edge_arc_physics(edge, shipment, disruption)
        total_hours += arc_hours
        temp_c += arc_temp_delta
        if not edge.has_continuous_customs_seal:
            continuous_seal = False

    return round(total_hours, 2), round(temp_c, 2), continuous_seal


def _extract_minimal_conflict_sets(
    edges: list[CorridorEdge],
    arc_hours_list: list[float],
    arc_temp_deltas: list[float],
    shipment: ShipmentSpec,
    disruption: DisruptionState,
    dwell_hours: float,
    has_valid_hs: bool,
    seal_ok: bool,
    cepa_ok: bool,
    temp_ok: bool,
    sla_ok: bool,
) -> tuple[bool, list[list[str]], bool]:
    """Extract subset-minimal conflicting edge sets and detect dwell-only violations."""
    global_cepa_fail = (
        disruption.require_cepa_zero_tariff and shipment.cepa_value_add_pct < CEPA_MIN_VALUE_ADD_PCT
    )
    global_temp_fail = shipment.is_temp_sensitive and shipment.initial_temp_c > shipment.max_temp_c
    if not has_valid_hs or global_cepa_fail or global_temp_fail:
        return True, [], False

    conflict_sets: list[list[str]] = []
    requires_dwell = False

    # 1. Unbonded edges individually break GCC e-TIR seal continuity (and CEPA non-manipulation)
    if not seal_ok or not cepa_ok:
        for edge in edges:
            if not edge.has_continuous_customs_seal:
                conflict_sets.append([edge.id])

    # 2. Monotonic thermal excursion minimal edge subset
    if not temp_ok and shipment.is_temp_sensitive:
        temp_no_dwell = shipment.initial_temp_c + sum(arc_temp_deltas)
        if temp_no_dwell > shipment.max_temp_c:
            indexed = sorted(
                ((arc_temp_deltas[i], edges[i].id) for i in range(len(edges))),
                key=lambda item: item[0],
                reverse=True,
            )
            acc = shipment.initial_temp_c
            subset: list[str] = []
            for delta, eid in indexed:
                if delta <= 0.0:
                    continue
                if eid not in subset:
                    subset.append(eid)
                acc += delta
                if acc > shipment.max_temp_c:
                    break
            if subset and subset not in conflict_sets:
                conflict_sets.append(subset)
        else:
            requires_dwell = True

    # 3. Monotonic SLA transit-window minimal edge subset
    if not sla_ok:
        hours_no_dwell = sum(arc_hours_list)
        if hours_no_dwell > shipment.max_transit_hours:
            indexed_h = sorted(
                ((arc_hours_list[i], edges[i].id) for i in range(len(edges))),
                key=lambda item: item[0],
                reverse=True,
            )
            acc_h = 0.0
            subset_h: list[str] = []
            for hrs, eid in indexed_h:
                if hrs <= 0.0:
                    continue
                if eid not in subset_h:
                    subset_h.append(eid)
                acc_h += hrs
                if acc_h > shipment.max_transit_hours:
                    break
            if subset_h and subset_h not in conflict_sets:
                conflict_sets.append(subset_h)
        elif dwell_hours > 0.0:
            requires_dwell = True

    return False, conflict_sets, requires_dwell


def verify_route_with_z3_and_core(
    route_id: str,
    route_name: str,
    edges: list[CorridorEdge],
    shipment: ShipmentSpec,
    disruption: DisruptionState,
    dwell_hours: float = 0.0,
) -> tuple[Z3ProofCertificate, Z3ConflictAnalysis]:
    """Formally prove or refute compliance using Z3 SMT with tracked unsat-core extraction."""
    arc_hours_list: list[float] = []
    arc_temp_deltas: list[float] = []
    for edge in edges:
        ah, atd = _edge_arc_physics(edge, shipment, disruption)
        arc_hours_list.append(ah)
        arc_temp_deltas.append(atd)

    total_hours, arrival_temp_c, continuous_seal = compute_route_physics(
        edges, shipment, disruption, dwell_hours=dwell_hours
    )
    touches_oman = any(e.touches_oman for e in edges)
    has_valid_hs = len(shipment.hs_code.replace(".", "")) >= 6

    solver = z3.Solver()

    # Symbolic Z3 variables
    z_hs_valid = z3.Bool("hs_code_valid")
    z_continuous_seal = z3.Bool("gcc_continuous_etir_seal")
    z_touches_oman = z3.Bool("non_party_oman_transit")
    z_require_cepa = z3.Bool("require_cepa_zero_tariff")
    z_cepa_value_add = z3.Real("cepa_origin_value_add_pct")
    z_temp_sensitive = z3.Bool("gdp_pharma_cold_chain")
    z_arrival_temp = z3.Real("predicted_arrival_temp_c")
    z_max_temp = z3.Real("sla_max_temp_c")
    z_transit_hours = z3.Real("total_transit_hours")
    z_max_hours = z3.Real("sla_max_transit_hours")

    # Tracked per-edge SMT telemetry for exact unsat-core attribution
    z_edge_seals: list[z3.BoolRef] = []
    z_edge_omans: list[z3.BoolRef] = []
    z_edge_hours_vars: list[z3.ArithRef] = []
    z_edge_temp_vars: list[z3.ArithRef] = []
    z_ndf_terms: list[z3.ArithRef] = []

    running_temp = shipment.initial_temp_c
    if shipment.is_temp_sensitive and dwell_hours > 0.0:
        dwell_delta = DWELL_THERMAL_DRIFT_C_PER_HOUR * dwell_hours
        mid_dwell = running_temp + 0.5 * dwell_delta
        slope, intercept = _haynes_secant_coeffs(mid_dwell)
        z_ndf_terms.append(
            (
                z3.RealVal(str(round(slope, 6))) * z3.RealVal(str(round(mid_dwell, 4)))
                + z3.RealVal(str(round(intercept, 6)))
            )
            * z3.RealVal(str(round(dwell_hours, 4)))
        )
        running_temp += dwell_delta

    for idx, edge in enumerate(edges):
        z_es = z3.Bool(f"edge_seal_{idx}_{edge.id}")
        z_eo = z3.Bool(f"edge_oman_{idx}_{edge.id}")
        z_eh = z3.Real(f"edge_hours_{idx}_{edge.id}")
        z_et = z3.Real(f"edge_temp_delta_{idx}_{edge.id}")
        solver.assert_and_track(
            z_es == edge.has_continuous_customs_seal,
            z3.Bool(f"ARC_SEAL::{idx}::{edge.id}"),
        )
        solver.assert_and_track(
            z_eo == edge.touches_oman,
            z3.Bool(f"ARC_OMAN::{idx}::{edge.id}"),
        )
        solver.assert_and_track(
            z3.And(
                z_eh == z3.RealVal(str(round(arc_hours_list[idx], 4))),
                z_et == z3.RealVal(str(round(arc_temp_deltas[idx], 6))),
            ),
            z3.Bool(f"ARC_PHYS::{idx}::{edge.id}"),
        )
        z_edge_seals.append(z_es)
        z_edge_omans.append(z_eo)
        z_edge_hours_vars.append(z_eh)
        z_edge_temp_vars.append(z_et)

        if shipment.is_temp_sensitive:
            mid_temp = running_temp + 0.5 * arc_temp_deltas[idx]
            slope, intercept = _haynes_secant_coeffs(mid_temp)
            z_ndf_terms.append(
                (
                    z3.RealVal(str(round(slope, 6))) * z3.RealVal(str(round(mid_temp, 4)))
                    + z3.RealVal(str(round(intercept, 6)))
                )
                * z_eh
            )
            running_temp += arc_temp_deltas[idx]

    solver.assert_and_track(z_hs_valid == has_valid_hs, z3.Bool("HS_CLASS::VALID_6_DIGIT"))
    solver.assert_and_track(
        z_continuous_seal == (z3.And(*z_edge_seals) if z_edge_seals else z3.BoolVal(True)),
        z3.Bool("GCC_CUSTOMS::SEAL_AGGREGATE"),
    )
    solver.assert_and_track(
        z_touches_oman == (z3.Or(*z_edge_omans) if z_edge_omans else z3.BoolVal(False)),
        z3.Bool("CEPA_TRANSIT::OMAN_FLAG"),
    )
    solver.assert_and_track(
        z_require_cepa == disruption.require_cepa_zero_tariff,
        z3.Bool("CEPA_ORIGIN::REQUIRE_ZERO_TARIFF"),
    )
    solver.assert_and_track(
        z_cepa_value_add == z3.RealVal(str(shipment.cepa_value_add_pct)),
        z3.Bool("CEPA_ORIGIN::QVC_TELEMETRY"),
    )
    solver.assert_and_track(
        z_temp_sensitive == shipment.is_temp_sensitive,
        z3.Bool("GDP_THERMAL::SENSITIVITY_FLAG"),
    )
    dwell_temp_c = (
        DWELL_THERMAL_DRIFT_C_PER_HOUR * dwell_hours if shipment.is_temp_sensitive else 0.0
    )
    solver.assert_and_track(
        z_arrival_temp
        == z3.RealVal(str(shipment.initial_temp_c + dwell_temp_c))
        + (z3.Sum(*z_edge_temp_vars) if z_edge_temp_vars else z3.RealVal("0")),
        z3.Bool("GDP_THERMAL::TEMP_ACCUMULATION"),
    )
    solver.assert_and_track(
        z_max_temp == z3.RealVal(str(shipment.max_temp_c)),
        z3.Bool("GDP_THERMAL::SLA_CEILING"),
    )
    solver.assert_and_track(
        z_transit_hours
        == z3.RealVal(str(round(dwell_hours, 4)))
        + (z3.Sum(*z_edge_hours_vars) if z_edge_hours_vars else z3.RealVal("0")),
        z3.Bool("CONSIGNEE_SLA::HOURS_ACCUMULATION"),
    )
    solver.assert_and_track(
        z_max_hours == z3.RealVal(str(shipment.max_transit_hours)),
        z3.Bool("CONSIGNEE_SLA::MAX_HOURS"),
    )

    # Formal Regulatory & SLA Axioms (tracked for unsat-core extraction)
    axiom_gcc_seal = z3.And(z_hs_valid, z_continuous_seal)
    axiom_cepa_origin = z3.Implies(
        z_require_cepa,
        z3.And(
            z_cepa_value_add >= z3.RealVal(str(CEPA_MIN_VALUE_ADD_PCT)),
            z3.Implies(z_touches_oman, z_continuous_seal),
        ),
    )
    axiom_cold_chain = z3.Implies(z_temp_sensitive, z_arrival_temp <= z_max_temp)
    axiom_sla_deadline = z_transit_hours <= z_max_hours

    solver.assert_and_track(axiom_gcc_seal, z3.Bool("GCC_CUSTOMS::ETIR_SEAL_CONTINUITY"))
    solver.assert_and_track(axiom_cepa_origin, z3.Bool("CEPA_ORIGIN::VALUE_ADD_NON_MANIPULATION"))
    solver.assert_and_track(axiom_cold_chain, z3.Bool("GDP_THERMAL::ARRIVAL_TEMP_CEILING"))
    solver.assert_and_track(axiom_sla_deadline, z3.Bool("CONSIGNEE_SLA::DELIVERY_HORIZON"))

    # Piecewise-linear Haynes MKT check for Chapter 30 (<= 8.0 C) cold-chain shipments
    if shipment.is_temp_sensitive and shipment.max_temp_c <= 8.0 and z_ndf_terms:
        solver.assert_and_track(
            z3.Sum(*z_ndf_terms) <= z_transit_hours * z3.RealVal("1.0001"),
            z3.Bool("GDP_THERMAL::HAYNES_MKT_8C"),
        )

    result = solver.check()
    is_sat = result == z3.sat
    unsat_core_labels = [str(atom) for atom in solver.unsat_core()] if not is_sat else []

    # Individual rule diagnostics for transparent audit trail
    seal_ok = has_valid_hs and continuous_seal
    cepa_ok = (not disruption.require_cepa_zero_tariff) or (
        shipment.cepa_value_add_pct >= CEPA_MIN_VALUE_ADD_PCT
        and ((not touches_oman) or continuous_seal)
    )
    temp_ok = (not shipment.is_temp_sensitive) or (arrival_temp_c <= shipment.max_temp_c)
    sla_ok = total_hours <= shipment.max_transit_hours

    checks = [
        Z3RuleCheck(
            rule_id="GCC_CUSTOMS_ETIR_SEAL",
            law_reference="GCC Unified Customs Law Art. 98 / Green Corridor Bond",
            passed=seal_ok,
            detail=(
                "Continuous e-TIR customs seal verified across all corridor legs."
                if seal_ok
                else "VIOLATION: Unbonded spot transit breaks GCC customs transit bond."
            ),
        ),
        Z3RuleCheck(
            rule_id="UAE_INDIA_CEPA_ORIGIN",
            law_reference="UAE-India CEPA Art. 3.15 (Non-Manipulation & ≥40% Value-Add)",
            passed=cepa_ok,
            detail=(
                f"CEPA 0% preferential duty preserved ({shipment.cepa_value_add_pct:.1f}% value-add, sealed transit)."
                if cepa_ok
                else "VIOLATION: Unsealed non-party transit voids UAE-India CEPA 0% tariff."
            ),
        ),
        Z3RuleCheck(
            rule_id="GDP_COLD_CHAIN_INTEGRITY",
            law_reference="EU GDP / UAE MOHAP Cold-Chain Thermal Excursion Limit",
            passed=temp_ok,
            detail=(
                f"Arrival temp {arrival_temp_c:.1f}°C ≤ {shipment.max_temp_c:.1f}°C SLA ceiling."
                if temp_ok
                else f"VIOLATION: Thermal excursion {arrival_temp_c:.1f}°C > {shipment.max_temp_c:.1f}°C limit."
            ),
        ),
        Z3RuleCheck(
            rule_id="CONSIGNEE_SLA_WINDOW",
            law_reference="Contractual Delivery Horizon",
            passed=sla_ok,
            detail=(
                f"Transit {total_hours:.1f}h ≤ {shipment.max_transit_hours:.1f}h SLA deadline."
                if sla_ok
                else f"VIOLATION: Transit {total_hours:.1f}h breaches {shipment.max_transit_hours:.1f}h SLA."
            ),
        ),
    ]

    violations = [c.detail for c in checks if not c.passed]
    core_comment = f"\n; unsat-core: {', '.join(unsat_core_labels)}" if unsat_core_labels else ""
    smtlib_excerpt = (
        f"{solver.to_smt2().strip()}\n(check-sat) ; => {'sat' if is_sat else 'unsat'}{core_comment}"
    )

    cert = Z3ProofCertificate(
        route_id=route_id,
        route_name=route_name,
        edge_ids=[e.id for e in edges],
        status="SAT" if is_sat else "UNSAT",
        checks=checks,
        smtlib_excerpt=smtlib_excerpt,
        violation_summary=" | ".join(violations) if violations else None,
    )

    if is_sat:
        analysis = Z3ConflictAnalysis(
            is_global_infeasible=False,
            minimal_conflict_edge_sets=[],
            unsat_core_labels=[],
            requires_dwell_for_violation=False,
        )
    else:
        is_global, conflict_sets, needs_dwell = _extract_minimal_conflict_sets(
            edges=edges,
            arc_hours_list=arc_hours_list,
            arc_temp_deltas=arc_temp_deltas,
            shipment=shipment,
            disruption=disruption,
            dwell_hours=dwell_hours,
            has_valid_hs=has_valid_hs,
            seal_ok=seal_ok,
            cepa_ok=cepa_ok,
            temp_ok=temp_ok,
            sla_ok=sla_ok,
        )
        analysis = Z3ConflictAnalysis(
            is_global_infeasible=is_global,
            minimal_conflict_edge_sets=conflict_sets,
            unsat_core_labels=unsat_core_labels,
            requires_dwell_for_violation=needs_dwell,
        )

    return cert, analysis


def verify_route_with_z3(
    route_id: str,
    route_name: str,
    edges: list[CorridorEdge],
    shipment: ShipmentSpec,
    disruption: DisruptionState,
    dwell_hours: float = 0.0,
) -> Z3ProofCertificate:
    """Formally prove or refute compliance using Z3 SMT constraints."""
    cert, _ = verify_route_with_z3_and_core(
        route_id=route_id,
        route_name=route_name,
        edges=edges,
        shipment=shipment,
        disruption=disruption,
        dwell_hours=dwell_hours,
    )
    return cert


# ============================================================================
# Chapter 30 Biologics (HS 3002.15) QF_LIRA Formal Compliance Compiler
# ============================================================================

HAYNES_DH_OVER_R_KELVIN = 10000.0
MKT_REF_LIMIT_CELSIUS = 8.0
MKT_REF_LIMIT_KELVIN = 281.15
HAYNES_NDF_SECANT_SEGMENTS = HAYNES_NDF_KNOTS


class ValuationBasis(StrEnum):
    FOB = "FOB"
    EXW = "EXW"


class DossierCustomsRegime(StrEnum):
    EXPORT_ORIGIN = "EXPORT_ORIGIN"
    CEPA_DIRECT_SEA = "CEPA_DIRECT_SEA"
    OMAN_TRANSIT_PORT = "OMAN_TRANSIT_PORT"
    ETIR_CROSS_BORDER = "ETIR_CROSS_BORDER"
    MAKASA_CROSS_BORDER = "MAKASA_CROSS_BORDER"
    UAE_BONDED_SEA_AIR = "UAE_BONDED_SEA_AIR"
    EU_ICS2_AIR_ENTRY = "EU_ICS2_AIR_ENTRY"


CustomsRegime = DossierCustomsRegime


class DossierTransportMode(StrEnum):
    SEA = "SEA"
    ROAD = "ROAD"
    AIR = "AIR"


class ContainerType(StrEnum):
    ENVIROTAINER_RKN_E1 = "ENVIROTAINER_RKN_E1"
    ENVIROTAINER_RAP_E2 = "ENVIROTAINER_RAP_E2"
    ENVIROTAINER_RKN_T2 = "ENVIROTAINER_RKN_T2"


@dataclass
class BOMInputItem:
    """Material input incorporated into a finished Chapter 30 biologic product."""

    material_id: str
    hs6_code: int
    cif_value_usd: float
    is_originating_party: bool
    is_retail_packaging: bool = False


@dataclass
class CEPAOriginDossier:
    """Data payload for India-UAE CEPA Chapter 3 & Annex 3B evaluation."""

    hs_code_full: str
    is_immunological_note2_ch30: bool
    is_measured_dose_or_retail_pack: bool
    valuation_basis: ValuationBasis
    fob_value_usd: float
    exw_value_usd: float
    direct_labour_cost_usd: float
    direct_overhead_cost_usd: float
    transport_container_tare_value_usd: float
    bom_inputs: list[BOMInputItem]
    final_manufacture_in_india: bool
    only_minimal_operations_art3_5: bool
    has_valid_coo: bool
    coo_has_unique_serial_and_seal: bool
    export_date_day: float
    coo_issue_date_day: float
    coo_working_days_after_export: float
    coo_marked_issued_retrospectively: bool
    import_declaration_date_day: float
    fob_qvc_threshold: float = 0.40
    exw_qvc_threshold: float = 0.35


@dataclass
class ETIRLegTelemetry:
    """UNECE e-TIR Annex 11 message timestamps and seal telemetry for cross-border road legs."""

    holder_authorized_in_itdb: bool
    e9_advance_data_ts: float
    i1_accept_guarantee_ts: float
    i7_record_declaration_ts: float
    i7_contains_seal_id: bool
    i9_start_tir_ts: float
    i9_seal_id: str
    i15_notify_customs_ts: float
    border_arrival_ts: float
    i11_terminate_tir_ts: float
    i11_seal_id: str
    i13_discharge_tir_ts: float
    duplicate_seal_in_registry: bool = False
    customs_inspection_broke_seal: bool = False
    new_seal_recorded_in_etir: bool = False


@dataclass
class MakasaLegTelemetry:
    """GCC Customs Union Single Point of Entry (Al-Maqasa) telemetry."""

    first_entry_duty_cleared_or_exempt: bool
    has_gcc_statistical_export_decl: bool
    has_makasa_endorsement_stamp: bool
    has_copy_of_first_entry_import_decl: bool
    gcc_customs_seal_intact: bool


@dataclass
class Mirsal2SeaAirTelemetry:
    """UAE bonded Sea-Air transfer telemetry (AEJEA/AEKIZ -> AEDWC/AEAUH/AEDXB via Mirsal-2)."""

    mirsal2_transit_boe_lodged: bool
    dubai_customs_smart_eseal_active: bool
    transfer_duration_hours: float
    max_allowed_bond_window_hours: float = 24.0
    entered_uae_mainland_commerce: bool = False


@dataclass
class EUICS2Release3Telemetry:
    """EU ICS2 Release 3 & Article 106 UCC DA air cargo security and ENS telemetry."""

    placi_filing_code: str
    placi_lodged_ts: float
    aircraft_loading_ts: float
    has_active_dnl_flag: bool
    has_unresolved_rfi_flag: bool
    has_hrcm_flag: bool
    hrcm_enhanced_screening_completed: bool
    ens_complete_filing_code: str
    ens_complete_lodged_ts: float
    aircraft_takeoff_ts: float
    eu_first_port_arrival_ts: float
    is_multiple_filing: bool
    carrier_eori_matches: bool = True
    mawb_number_matches: bool = True
    house_declarant_eori_matches: bool = True


@dataclass
class ThermalPhaseInput:
    """One of the 3 thermal exposure regimes (ARC, DWELL, INSPECT) within a leg."""

    phase_name: str
    duration_hours: float
    ambient_temp_c: float
    active_cooling_drift_c_per_h: float = 0.0
    unpowered_exposure_hours: float = 0.0
    shore_power_plugged_in: bool = False
    charge_hours_requested: float = 0.0
    dry_ice_re_iced_kg: float = 0.0
    max_hub_dwell_limit_hours: float | None = None


@dataclass
class CorridorLegSpec:
    """Complete multi-domain specification for a single corridor leg."""

    leg_index: int
    origin_node: str
    dest_node: str
    mode: DossierTransportMode | TransportMode
    customs_regime: DossierCustomsRegime
    is_non_party_transit: bool
    remains_under_customs_control: bool = True
    entered_local_trade_or_consumption: bool = False
    undergoes_ops_beyond_preservation: bool = False
    has_non_manipulation_certificate: bool = False
    has_single_through_transport_doc: bool = True
    etir_telemetry: ETIRLegTelemetry | None = None
    makasa_telemetry: MakasaLegTelemetry | None = None
    mirsal2_telemetry: Mirsal2SeaAirTelemetry | None = None
    ics2_telemetry: EUICS2Release3Telemetry | None = None
    arc_phase: ThermalPhaseInput = field(
        default_factory=lambda: ThermalPhaseInput("ARC", 0.0, 20.0)
    )
    dwell_phase: ThermalPhaseInput = field(
        default_factory=lambda: ThermalPhaseInput("DWELL", 0.0, 38.0)
    )
    inspect_phase: ThermalPhaseInput = field(
        default_factory=lambda: ThermalPhaseInput("INSPECT", 0.0, 25.0)
    )


@dataclass
class ColdChainContainerConfig:
    """Configuration and SLA parameters for the cold-chain ULD."""

    container_type: ContainerType
    setpoint_temp_c: float = 5.0
    use_strict_sla_30h_autonomy: bool = True
    initial_battery_hours: float = 30.0
    initial_dry_ice_kg: float = 0.0
    passive_insulation_warmup_coeff: float = 0.18
    extreme_heat_overload_coeff: float = 0.08
    max_cumulative_excursion_hours_above_8c: float = 2.0
    consignee_sla_max_total_hours: float = 120.0


@dataclass
class VerificationResult:
    """Output returned by NeuroSymbolicCorridorCompiler.verify_corridor."""

    is_sat: bool
    status: str
    unsat_core: list[str]
    calculated_exact_mkt_c: float | None
    z3_upper_bound_ndf_ratio: float | None
    phase_temperatures_c: dict[str, float]
    phase_battery_rem_hours: dict[str, float]
    qvc_achieved_pct: float | None


def _ambient_battery_drain_multiplier(ambient_temp_c: float) -> float:
    """Envirotainer RKN e1 / RAP e2 battery drain multiplier lambda(T_amb) per Sec 2.2 & 2.3."""
    if ambient_temp_c <= 30.0:
        return 1.00
    if ambient_temp_c <= 40.0:
        return 1.00 + 0.05 * (ambient_temp_c - 30.0)
    return 1.50 + 0.08 * (ambient_temp_c - 40.0)


def _container_max_autonomy_hours(cfg: ColdChainContainerConfig) -> float:
    """Return rated battery autonomy ceiling (hours) for the configured Envirotainer ULD."""
    if cfg.container_type == ContainerType.ENVIROTAINER_RKN_E1:
        return 30.0 if cfg.use_strict_sla_30h_autonomy else 58.0
    if cfg.container_type == ContainerType.ENVIROTAINER_RAP_E2:
        return 30.0 if cfg.use_strict_sla_30h_autonomy else 60.0
    return 72.0


class NeuroSymbolicCorridorCompiler:
    """Compiles Chapter 30 Biologics compliance, GCC/EU customs, and MKT physics into QF_LIRA Z3."""

    def __init__(self) -> None:
        self.solver = z3.Solver()
        self.solver.set(unsat_core=True)
        self._tracked_assertions: list[str] = []
        self._base_assertions: list[z3.BoolRef] = []
        self._tracked_pairs: list[tuple[z3.BoolRef, str]] = []

    def _add_def(self, expr: z3.BoolRef) -> None:
        """Add an un-tracked variable definition and preserve it for iterative core extraction."""
        self.solver.add(expr)
        self._base_assertions.append(expr)

    def _track(self, constraint: z3.BoolRef, label: str) -> None:
        """Register a Z3 constraint with a named tracking literal for unsat_core()."""
        self.solver.assert_and_track(constraint, z3.Bool(label))
        self._tracked_assertions.append(label)
        self._tracked_pairs.append((constraint, label))

    def compile_cepa_origin_and_consignment(
        self,
        dossier: CEPAOriginDossier,
        legs: list[CorridorLegSpec],
    ) -> tuple[z3.ArithRef, z3.ArithRef]:
        """Encode HS 3002.15 classification, Annex 3B CTSH+QVC, Art. 3.4/3.5/3.12/3.14."""
        digits_only = "".join(ch for ch in dossier.hs_code_full if ch.isdigit())
        is_hs6_300215 = len(digits_only) >= 6 and int(digits_only[:6]) == 300215
        self._track(
            z3.And(
                z3.BoolVal(is_hs6_300215),
                z3.BoolVal(dossier.is_immunological_note2_ch30),
                z3.BoolVal(dossier.is_measured_dose_or_retail_pack),
            ),
            "HS_CLASS::CH30_NOTE2_3002_15_VALID",
        )

        v_base = z3.Real("cepa_v_base")
        theta_req = z3.Real("cepa_theta_req")
        if dossier.valuation_basis == ValuationBasis.FOB:
            self._add_def(v_base == z3.RealVal(dossier.fob_value_usd))
            self._add_def(theta_req == z3.RealVal(dossier.fob_qvc_threshold))
        else:
            self._add_def(v_base == z3.RealVal(dossier.exw_value_usd))
            self._add_def(theta_req == z3.RealVal(dossier.exw_qvc_threshold))

        nom_terms: list[z3.ArithRef] = [z3.RealVal(0.0)]
        om_terms: list[z3.ArithRef] = [z3.RealVal(0.0)]
        non_shift_terms: list[z3.ArithRef] = [z3.RealVal(0.0)]
        for item in dossier.bom_inputs:
            v_item = z3.RealVal(item.cif_value_usd)
            if item.is_originating_party:
                om_terms.append(v_item)
            else:
                nom_terms.append(v_item)
                if item.hs6_code == 300215:
                    non_shift_terms.append(v_item)

        v_nom_total = z3.Real("cepa_v_nom_total")
        v_om_total = z3.Real("cepa_v_om_total")
        v_nom_failing_ctsh = z3.Real("cepa_v_nom_failing_ctsh")
        self._add_def(v_nom_total == z3.Sum(nom_terms))
        self._add_def(v_om_total == z3.Sum(om_terms))
        self._add_def(v_nom_failing_ctsh == z3.Sum(non_shift_terms))

        self._track(
            z3.Or(
                v_nom_failing_ctsh == z3.RealVal(0.0),
                v_nom_failing_ctsh <= z3.RealVal("0.10") * v_base,
            ),
            "CEPA_ORIGIN::ANNEX_3B_CTSH_OR_ART_3_4_DEMINIMIS",
        )

        c_labour = z3.RealVal(dossier.direct_labour_cost_usd)
        c_overhead = z3.RealVal(dossier.direct_overhead_cost_usd)
        qvc_method1_val = z3.Real("cepa_qvc_method1_ratio")
        qvc_method2_val = z3.Real("cepa_qvc_method2_ratio")
        self._add_def(qvc_method1_val * v_base == v_base - v_nom_total)
        self._add_def(qvc_method2_val * v_base == v_om_total + c_labour + c_overhead)

        self._track(
            z3.Or(
                (v_base - v_nom_total) >= theta_req * v_base,
                (v_om_total + c_labour + c_overhead) >= theta_req * v_base,
            ),
            "CEPA_ORIGIN::ANNEX_3B_QVC_THRESHOLD_40FOB_35EXW",
        )
        self._track(
            z3.Not(z3.BoolVal(dossier.only_minimal_operations_art3_5)),
            "CEPA_ORIGIN::ART_3_5_NO_MINIMAL_OPERATIONS",
        )
        self._track(
            z3.BoolVal(dossier.final_manufacture_in_india),
            "CEPA_ORIGIN::ART_3_2_FINAL_MANUFACTURE_IN_INDIA",
        )

        for leg in legs:
            i = leg.leg_index
            self._track(
                z3.Not(z3.BoolVal(leg.undergoes_ops_beyond_preservation)),
                f"CEPA_TRANSIT::ART_3_12_NON_MANIPULATION_OPS_LEG_{i}",
            )
            if leg.is_non_party_transit:
                self._track(
                    z3.And(
                        z3.BoolVal(leg.remains_under_customs_control),
                        z3.Not(z3.BoolVal(leg.entered_local_trade_or_consumption)),
                    ),
                    f"CEPA_TRANSIT::ART_3_12_CUSTOMS_SUPERVISION_LEG_{i}",
                )
                self._track(
                    z3.Or(
                        z3.BoolVal(leg.has_non_manipulation_certificate),
                        z3.BoolVal(leg.has_single_through_transport_doc),
                    ),
                    f"CEPA_TRANSIT::ART_3_12_NON_MANIPULATION_CERT_LEG_{i}",
                )

        t_export = z3.RealVal(dossier.export_date_day)
        t_coo_issue = z3.RealVal(dossier.coo_issue_date_day)
        t_import = z3.RealVal(dossier.import_declaration_date_day)
        w_days = z3.RealVal(dossier.coo_working_days_after_export)

        self._track(
            z3.Or(
                w_days <= z3.RealVal(5.0),
                z3.And(
                    z3.BoolVal(dossier.coo_marked_issued_retrospectively),
                    (t_coo_issue - t_export) <= z3.RealVal(365.0),
                ),
            ),
            "CEPA_COO::ART_3_14_ISSUANCE_5_WORKING_DAYS",
        )
        self._track(
            z3.And(
                z3.BoolVal(dossier.has_valid_coo),
                z3.BoolVal(dossier.coo_has_unique_serial_and_seal),
                t_import >= t_coo_issue,
                (t_import - t_coo_issue) <= z3.RealVal(365.0),
            ),
            "CEPA_COO::ART_3_14_VALIDITY_12_MONTHS",
        )
        return qvc_method1_val, qvc_method2_val

    def compile_customs_and_ics2_constraints(self, legs: list[CorridorLegSpec]) -> None:
        """Encode e-TIR Annex 11, GCC Makasa, UAE Mirsal-2, and EU ICS2 Release 3 constraints."""
        for leg in legs:
            i = leg.leg_index
            regime = leg.customs_regime
            if regime == DossierCustomsRegime.ETIR_CROSS_BORDER:
                etir = leg.etir_telemetry
                if etir is None:
                    self._track(z3.BoolVal(False), f"GCC_CUSTOMS::ETIR_ANNEX11_MSG_SEQ_LEG_{i}")
                    continue
                self._track(
                    z3.And(
                        z3.BoolVal(etir.holder_authorized_in_itdb),
                        z3.RealVal(etir.e9_advance_data_ts)
                        < z3.RealVal(etir.i1_accept_guarantee_ts),
                        z3.RealVal(etir.i1_accept_guarantee_ts)
                        <= z3.RealVal(etir.i7_record_declaration_ts),
                        z3.RealVal(etir.i7_record_declaration_ts)
                        < z3.RealVal(etir.i9_start_tir_ts),
                        z3.RealVal(etir.i9_start_tir_ts) < z3.RealVal(etir.i15_notify_customs_ts),
                        z3.RealVal(etir.i15_notify_customs_ts) < z3.RealVal(etir.border_arrival_ts),
                        z3.RealVal(etir.border_arrival_ts) <= z3.RealVal(etir.i11_terminate_tir_ts),
                        z3.RealVal(etir.i11_terminate_tir_ts)
                        <= z3.RealVal(etir.i13_discharge_tir_ts),
                    ),
                    f"GCC_CUSTOMS::ETIR_ANNEX11_MSG_SEQ_LEG_{i}",
                )
                seal_matches = (
                    len(etir.i9_seal_id.strip()) > 0 and etir.i9_seal_id == etir.i11_seal_id
                )
                self._track(
                    z3.And(
                        z3.Not(z3.BoolVal(etir.i7_contains_seal_id)),
                        z3.Not(z3.BoolVal(etir.duplicate_seal_in_registry)),
                        z3.Or(
                            z3.And(
                                z3.Not(z3.BoolVal(etir.customs_inspection_broke_seal)),
                                z3.BoolVal(seal_matches),
                            ),
                            z3.And(
                                z3.BoolVal(etir.customs_inspection_broke_seal),
                                z3.BoolVal(etir.new_seal_recorded_in_etir),
                            ),
                        ),
                    ),
                    f"GCC_CUSTOMS::ETIR_ERROR_309_310_SEAL_LINEAGE_LEG_{i}",
                )
            elif regime == DossierCustomsRegime.MAKASA_CROSS_BORDER:
                mk = leg.makasa_telemetry
                self._track(
                    z3.BoolVal(False)
                    if mk is None
                    else z3.And(
                        z3.BoolVal(mk.first_entry_duty_cleared_or_exempt),
                        z3.BoolVal(mk.has_gcc_statistical_export_decl),
                        z3.BoolVal(mk.has_makasa_endorsement_stamp),
                        z3.BoolVal(mk.has_copy_of_first_entry_import_decl),
                        z3.BoolVal(mk.gcc_customs_seal_intact),
                    ),
                    f"GCC_CUSTOMS::MAKASA_STATISTICAL_DECL_STAMP_LEG_{i}",
                )
            elif regime == DossierCustomsRegime.UAE_BONDED_SEA_AIR:
                m2 = leg.mirsal2_telemetry
                self._track(
                    z3.BoolVal(False)
                    if m2 is None
                    else z3.And(
                        z3.BoolVal(m2.mirsal2_transit_boe_lodged),
                        z3.BoolVal(m2.dubai_customs_smart_eseal_active),
                        z3.RealVal(m2.transfer_duration_hours)
                        <= z3.RealVal(m2.max_allowed_bond_window_hours),
                        z3.Not(z3.BoolVal(m2.entered_uae_mainland_commerce)),
                    ),
                    f"GCC_CUSTOMS::UAE_MIRSAL2_SEA_AIR_BOND_LEG_{i}",
                )
            elif regime == DossierCustomsRegime.EU_ICS2_AIR_ENTRY:
                ics2 = leg.ics2_telemetry
                if ics2 is None:
                    self._track(
                        z3.BoolVal(False),
                        f"EU_ICS2::ART_106_PLACI_PRE_LOADING_FILING_LEG_{i}",
                    )
                    continue
                valid_placi = {"F20", "F24", "F23+F25", "F26", "F28"}
                self._track(
                    z3.And(
                        z3.BoolVal(ics2.placi_filing_code in valid_placi),
                        z3.RealVal(ics2.placi_lodged_ts) < z3.RealVal(ics2.aircraft_loading_ts),
                    ),
                    f"EU_ICS2::ART_106_PLACI_PRE_LOADING_FILING_LEG_{i}",
                )
                self._track(
                    z3.And(
                        z3.Not(z3.BoolVal(ics2.has_active_dnl_flag)),
                        z3.Not(z3.BoolVal(ics2.has_unresolved_rfi_flag)),
                        z3.Implies(
                            z3.BoolVal(ics2.has_hrcm_flag),
                            z3.BoolVal(ics2.hrcm_enhanced_screening_completed),
                        ),
                    ),
                    f"EU_ICS2::ART_106_NO_DNL_HRCM_RFI_BLOCK_LEG_{i}",
                )
                valid_ens = {"F20", "F21+F22", "F21+F26", "F27", "F28", "F29"}
                t_takeoff = z3.RealVal(ics2.aircraft_takeoff_ts)
                t_arrival = z3.RealVal(ics2.eu_first_port_arrival_ts)
                t_ens = z3.RealVal(ics2.ens_complete_lodged_ts)
                self._track(
                    z3.And(
                        z3.BoolVal(ics2.ens_complete_filing_code in valid_ens),
                        z3.If(
                            (t_arrival - t_takeoff) >= z3.RealVal(4.0),
                            (t_arrival - t_ens) >= z3.RealVal(4.0),
                            t_ens <= t_takeoff,
                        ),
                    ),
                    f"EU_ICS2::ART_106_ENS_PRE_ARRIVAL_LEAD_TIME_LEG_{i}",
                )
                self._track(
                    z3.Implies(
                        z3.BoolVal(ics2.is_multiple_filing),
                        z3.And(
                            z3.BoolVal(ics2.carrier_eori_matches),
                            z3.BoolVal(ics2.mawb_number_matches),
                            z3.BoolVal(ics2.house_declarant_eori_matches),
                        ),
                    ),
                    f"EU_ICS2::MULTI_FILING_EORI_MAWB_LINK_KEYS_LEG_{i}",
                )

    def compile_cold_chain_and_mkt_physics(
        self,
        legs: list[CorridorLegSpec],
        cfg: ColdChainContainerConfig,
    ) -> tuple[dict[str, z3.ArithRef], dict[str, z3.ArithRef], z3.ArithRef]:
        """Encode 3-regime thermal exposure, ULD autonomy curves, and linearized Haynes MKT."""
        max_cap_hours = _container_max_autonomy_hours(cfg)
        b_curr: z3.ArithRef = z3.RealVal(min(cfg.initial_battery_hours, max_cap_hours))
        ice_curr: z3.ArithRef = z3.RealVal(cfg.initial_dry_ice_kg)

        phase_temp_vars: dict[str, z3.ArithRef] = {}
        phase_batt_vars: dict[str, z3.ArithRef] = {}
        phase_records: list[tuple[str, int, str, float, z3.ArithRef, z3.ArithRef]] = []
        excursion_hour_terms: list[z3.ArithRef] = [z3.RealVal(0.0)]
        total_duration_hours = 0.0

        for leg in legs:
            i = leg.leg_index
            for p_obj in (leg.arc_phase, leg.dwell_phase, leg.inspect_phase):
                p_name = p_obj.phase_name
                key = f"L{i}_{p_name}"
                tau = p_obj.duration_hours
                t_amb = p_obj.ambient_temp_c
                total_duration_hours += tau

                if p_obj.max_hub_dwell_limit_hours is not None and tau > 0.0:
                    self._track(
                        z3.RealVal(tau) <= z3.RealVal(p_obj.max_hub_dwell_limit_hours),
                        f"GDP_THERMAL::HUB_DWELL_TIME_LIMIT_LEG_{i}_{p_name}",
                    )

                restored_batt = 0.0
                if p_obj.charge_hours_requested > 0.0:
                    charge_allowed = (
                        p_obj.shore_power_plugged_in
                        and (-20.0 <= t_amb <= 40.0)
                        and cfg.container_type
                        in {
                            ContainerType.ENVIROTAINER_RKN_E1,
                            ContainerType.ENVIROTAINER_RAP_E2,
                        }
                    )
                    self._track(
                        z3.BoolVal(charge_allowed),
                        f"GDP_THERMAL::ENVIROTAINER_CHARGING_TEMP_LIMIT_LEG_{i}_{p_name}",
                    )
                    eff = 1.0 if (0.0 <= t_amb <= 20.0) else 0.85
                    restored_batt = (p_obj.charge_hours_requested / 8.0) * max_cap_hours * eff

                drain_mult = _ambient_battery_drain_multiplier(t_amb)
                b_next = z3.Real(f"batt_rem_{key}")
                raw_batt = b_curr - z3.RealVal(drain_mult * tau) + z3.RealVal(restored_batt)
                self._add_def(
                    b_next
                    == z3.If(
                        raw_batt > z3.RealVal(max_cap_hours),
                        z3.RealVal(max_cap_hours),
                        raw_batt,
                    )
                )

                if cfg.container_type == ContainerType.ENVIROTAINER_RKN_T2:
                    sub_rate = max(0.8, 0.06 * max(0.0, t_amb - cfg.setpoint_temp_c))
                    ice_next = z3.Real(f"ice_rem_{key}")
                    self._add_def(
                        ice_next
                        == ice_curr
                        - z3.RealVal(sub_rate * tau)
                        + z3.RealVal(p_obj.dry_ice_re_iced_kg)
                    )
                    autonomy_ok: z3.BoolRef = z3.And(
                        b_next >= z3.RealVal(0.0), ice_next >= z3.RealVal(0.0)
                    )
                    ice_curr = ice_next
                else:
                    autonomy_ok = b_next >= z3.RealVal(0.0)

                self._track(
                    autonomy_ok, f"GDP_THERMAL::ULD_BATTERY_OR_DRY_ICE_AUTONOMY_LEG_{i}_{p_name}"
                )
                phase_batt_vars[key] = b_next
                b_curr = b_next

                t_int = z3.Real(f"T_int_{key}")
                unpowered_h = min(tau, p_obj.unpowered_exposure_hours)
                powered_h = max(0.0, tau - unpowered_h)
                passive_drift = (
                    cfg.passive_insulation_warmup_coeff
                    * (t_amb - cfg.setpoint_temp_c)
                    * unpowered_h
                )
                overload_drift = (
                    cfg.extreme_heat_overload_coeff * max(0.0, t_amb - 40.0) * powered_h
                )
                active_drift = p_obj.active_cooling_drift_c_per_h * powered_h
                deficit_warmup = z3.If(
                    b_next < z3.RealVal(0.0),
                    z3.RealVal(
                        cfg.passive_insulation_warmup_coeff * max(0.0, t_amb - cfg.setpoint_temp_c)
                    )
                    * (-b_next / z3.RealVal(drain_mult)),
                    z3.RealVal(0.0),
                )
                self._add_def(
                    t_int
                    == z3.RealVal(
                        cfg.setpoint_temp_c + active_drift + passive_drift + overload_drift
                    )
                    + deficit_warmup
                )
                phase_temp_vars[key] = t_int

                if tau > 0.0:
                    self._track(
                        t_int >= z3.RealVal(2.0),
                        f"GDP_THERMAL::USP_1079_2_FREEZE_LOWER_BOUND_2C_LEG_{i}_{p_name}",
                    )
                    self._track(
                        t_int <= z3.RealVal(15.0),
                        f"GDP_THERMAL::USP_1079_2_SPIKE_CEILING_15C_LEG_{i}_{p_name}",
                    )

                exc_h = z3.Real(f"exc_hours_{key}")
                self._add_def(
                    exc_h == z3.If(t_int > z3.RealVal(8.0), z3.RealVal(tau), z3.RealVal(0.0))
                )
                excursion_hour_terms.append(exc_h)

                phi_var = z3.Real(f"phi_ndf_{key}")
                secant_clauses: list[z3.BoolRef] = []
                last_seg_idx = len(HAYNES_NDF_SECANT_SEGMENTS) - 1
                for seg_idx, (t_lo, t_hi, m_k, c_k) in enumerate(HAYNES_NDF_SECANT_SEGMENTS):
                    upper_cmp = (
                        t_int <= z3.RealVal(t_hi)
                        if seg_idx == last_seg_idx
                        else t_int < z3.RealVal(t_hi)
                    )
                    in_seg = z3.And(t_int >= z3.RealVal(t_lo), upper_cmp)
                    secant_clauses.append(
                        z3.Implies(in_seg, phi_var == z3.RealVal(m_k) * t_int + z3.RealVal(c_k))
                    )
                _, _, m_last, c_last = HAYNES_NDF_SECANT_SEGMENTS[-1]
                secant_clauses.append(
                    z3.Implies(
                        t_int > z3.RealVal(45.0),
                        phi_var >= z3.RealVal(m_last) * t_int + z3.RealVal(c_last),
                    )
                )
                self._add_def(z3.And(secant_clauses))
                phase_records.append((key, i, p_name, tau, t_int, phi_var))

        total_exc_hours = z3.Real("total_excursion_hours_above_8c")
        self._add_def(total_exc_hours == z3.Sum(excursion_hour_terms))
        self._track(
            total_exc_hours <= z3.RealVal(cfg.max_cumulative_excursion_hours_above_8c),
            "GDP_THERMAL::SLA_CUMULATIVE_EXCURSION_MAX_2H_ABOVE_8C",
        )

        # USP <1079.2> Table 1 Controlled Cold Temperature (CCT) 24-Hour Rolling MKT Window
        for idx, (_key, leg_i, p_name, tau_curr, _t_int_curr, _) in enumerate(phase_records):
            if tau_curr <= 0.0:
                continue
            rem_window = 24.0
            win_terms: list[z3.ArithRef] = []
            win_hours = 0.0
            for back_idx in range(idx, -1, -1):
                _, _, _, tau_b, _, phi_b = phase_records[back_idx]
                if tau_b <= 0.0:
                    continue
                used_h = min(rem_window, tau_b)
                win_terms.append(z3.RealVal(used_h) * phi_b)
                win_hours += used_h
                rem_window -= used_h
                if rem_window <= 1e-9:
                    break
            self._track(
                z3.Sum(win_terms) <= z3.RealVal(win_hours),
                f"GDP_THERMAL::USP_1079_2_HAYNES_MKT_24H_WINDOW_LEG_{leg_i}_{p_name}",
            )

        total_ndf_ratio = z3.Real("total_route_ndf_ratio")
        total_weighted_ndf = z3.Sum(
            [z3.RealVal(tau) * phi_v for (_, _, _, tau, _, phi_v) in phase_records if tau > 0.0]
        )
        self._add_def(total_ndf_ratio * z3.RealVal(total_duration_hours) == total_weighted_ndf)
        self._track(
            total_weighted_ndf <= z3.RealVal(total_duration_hours),
            "GDP_THERMAL::USP_1079_2_HAYNES_MKT_TOTAL_ROUTE_MAX_8C",
        )
        self._track(
            z3.RealVal(total_duration_hours) <= z3.RealVal(cfg.consignee_sla_max_total_hours),
            "CONSIGNEE_SLA::MAX_TOTAL_TRANSIT_WINDOW_HOURS",
        )

        return phase_temp_vars, phase_batt_vars, total_ndf_ratio

    @staticmethod
    def _z3_real_to_float(val: z3.ExprRef) -> float:
        if z3.is_rational_value(val):
            return float(val.numerator_as_long()) / float(val.denominator_as_long())
        return float(str(val))  # pragma: no cover

    def verify_corridor(
        self,
        dossier: CEPAOriginDossier,
        legs: list[CorridorLegSpec],
        container_cfg: ColdChainContainerConfig,
    ) -> VerificationResult:
        """Compile all 4 domain specs, solve in Z3, and return model or minimal unsat_core."""
        qvc1_var, qvc2_var = self.compile_cepa_origin_and_consignment(dossier, legs)
        self.compile_customs_and_ics2_constraints(legs)
        temp_vars, batt_vars, ndf_ratio_var = self.compile_cold_chain_and_mkt_physics(
            legs, container_cfg
        )

        if self.solver.check() == z3.sat:
            model = self.solver.model()
            temps_out = {
                k: round(self._z3_real_to_float(model[v]), 4) for k, v in temp_vars.items()
            }
            batts_out = {
                k: round(self._z3_real_to_float(model[v]), 4) for k, v in batt_vars.items()
            }
            ndf_ratio = self._z3_real_to_float(model[ndf_ratio_var])

            weighted_exp_sum = 0.0
            total_h = 0.0
            for leg in legs:
                i = leg.leg_index
                for p_obj in (leg.arc_phase, leg.dwell_phase, leg.inspect_phase):
                    if p_obj.duration_hours > 0.0:
                        t_c = temps_out[f"L{i}_{p_obj.phase_name}"]
                        t_k = t_c + 273.15
                        weighted_exp_sum += p_obj.duration_hours * math.exp(
                            -HAYNES_DH_OVER_R_KELVIN / t_k
                        )
                        total_h += p_obj.duration_hours

            mean_exp = weighted_exp_sum / total_h
            exact_mkt_c = (HAYNES_DH_OVER_R_KELVIN / (-math.log(mean_exp))) - 273.15
            qvc1 = self._z3_real_to_float(model[qvc1_var]) * 100.0
            qvc2 = self._z3_real_to_float(model[qvc2_var]) * 100.0

            return VerificationResult(
                is_sat=True,
                status="SAT (COMPLIANT)",
                unsat_core=[],
                calculated_exact_mkt_c=round(exact_mkt_c, 3),
                z3_upper_bound_ndf_ratio=round(ndf_ratio, 4),
                phase_temperatures_c=temps_out,
                phase_battery_rem_hours=batts_out,
                qvc_achieved_pct=round(max(qvc1, qvc2), 2),
            )

        core_set: set[str] = {str(lit) for lit in self.solver.unsat_core()}
        while True:
            s_rem = z3.Solver()
            s_rem.set(unsat_core=True)
            for base_expr in self._base_assertions:
                s_rem.add(base_expr)
            for expr, label in self._tracked_pairs:
                if label not in core_set:
                    s_rem.assert_and_track(expr, z3.Bool(label))
            if s_rem.check() == z3.sat:
                break
            new_lits = {str(lit) for lit in s_rem.unsat_core()}
            if not new_lits or new_lits.issubset(core_set):  # pragma: no cover
                break
            core_set.update(new_lits)
        core_labels = sorted(core_set)
        return VerificationResult(
            is_sat=False,
            status="UNSAT (NON-COMPLIANT)",
            unsat_core=core_labels,
            calculated_exact_mkt_c=None,
            z3_upper_bound_ndf_ratio=None,
            phase_temperatures_c={},
            phase_battery_rem_hours={},
            qvc_achieved_pct=None,
        )
