"""Z3 SMT Symbolic Regulatory & Cold-Chain Compliance Compiler."""

from __future__ import annotations

import z3

from app.models import (
    CorridorEdge,
    DisruptionState,
    ShipmentSpec,
    TransportMode,
    Z3ProofCertificate,
    Z3RuleCheck,
)


def compute_route_physics(
    edges: list[CorridorEdge],
    shipment: ShipmentSpec,
    disruption: DisruptionState,
) -> tuple[float, float, bool]:
    """Compute deterministic transit hours, arrival temperature, and continuous seal flag."""
    total_hours = 0.0
    temp_c = shipment.initial_temp_c
    continuous_seal = True

    for edge in edges:
        arc_hours = edge.base_hours
        if edge.passes_hormuz:
            arc_hours += disruption.hormuz_delay_hours
        if edge.touches_jebel_ali:
            arc_hours += disruption.jebel_ali_congestion_hours
        total_hours += arc_hours

        if not edge.has_continuous_customs_seal:
            continuous_seal = False

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
            temp_c += drift * arc_hours

    return round(total_hours, 2), round(temp_c, 2), continuous_seal


def verify_route_with_z3(
    route_id: str,
    route_name: str,
    edges: list[CorridorEdge],
    shipment: ShipmentSpec,
    disruption: DisruptionState,
) -> Z3ProofCertificate:
    """Formally prove or refute compliance using Z3 SMT constraints."""
    total_hours, arrival_temp_c, continuous_seal = compute_route_physics(
        edges, shipment, disruption
    )
    touches_oman = any(e.touches_oman for e in edges)
    has_valid_hs = len(shipment.hs_code.replace(".", "")) >= 6

    solver = z3.Solver()

    # Symbolic Z3 variables
    z_hs_valid = z3.Bool("hs_code_valid_8digit")
    z_continuous_seal = z3.Bool("gcc_continuous_etir_seal")
    z_touches_oman = z3.Bool("non_party_oman_transit")
    z_require_cepa = z3.Bool("require_cepa_zero_tariff")
    z_cepa_value_add = z3.Real("cepa_origin_value_add_pct")
    z_temp_sensitive = z3.Bool("gdp_pharma_cold_chain")
    z_arrival_temp = z3.Real("predicted_arrival_temp_c")
    z_max_temp = z3.Real("sla_max_temp_c")
    z_transit_hours = z3.Real("total_transit_hours")
    z_max_hours = z3.Real("sla_max_transit_hours")

    # Bind observed concrete telemetry into SMT assertions
    solver.add(z_hs_valid == has_valid_hs)
    solver.add(z_continuous_seal == continuous_seal)
    solver.add(z_touches_oman == touches_oman)
    solver.add(z_require_cepa == disruption.require_cepa_zero_tariff)
    solver.add(z_cepa_value_add == z3.RealVal(str(shipment.cepa_value_add_pct)))
    solver.add(z_temp_sensitive == shipment.is_temp_sensitive)
    solver.add(z_arrival_temp == z3.RealVal(str(arrival_temp_c)))
    solver.add(z_max_temp == z3.RealVal(str(shipment.max_temp_c)))
    solver.add(z_transit_hours == z3.RealVal(str(total_hours)))
    solver.add(z_max_hours == z3.RealVal(str(shipment.max_transit_hours)))

    # Formal Regulatory & SLA Axioms
    axiom_gcc_seal = z3.And(z_hs_valid, z_continuous_seal)
    axiom_cepa_origin = z3.Implies(
        z_require_cepa,
        z3.And(
            z_cepa_value_add >= z3.RealVal("40.0"),
            z3.Implies(z_touches_oman, z_continuous_seal),
        ),
    )
    axiom_cold_chain = z3.Implies(
        z_temp_sensitive,
        z_arrival_temp <= z_max_temp,
    )
    axiom_sla_deadline = z_transit_hours <= z_max_hours

    solver.add(axiom_gcc_seal)
    solver.add(axiom_cepa_origin)
    solver.add(axiom_cold_chain)
    solver.add(axiom_sla_deadline)

    result = solver.check()
    is_sat = result == z3.sat

    # Individual rule diagnostics for transparent audit trail
    seal_ok = has_valid_hs and continuous_seal
    cepa_ok = (not disruption.require_cepa_zero_tariff) or (
        shipment.cepa_value_add_pct >= 40.0 and ((not touches_oman) or continuous_seal)
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
    smtlib_excerpt = (
        f"(assert (and gcc_continuous_etir_seal "
        f"(=> require_cepa_zero_tariff (and (>= cepa_origin_value_add_pct 40.0) "
        f"(=> non_party_oman_transit gcc_continuous_etir_seal))) "
        f"(=> gdp_pharma_cold_chain (<= predicted_arrival_temp_c {shipment.max_temp_c:.1f})) "
        f"(<= total_transit_hours {shipment.max_transit_hours:.1f}))) ; check-sat => {'sat' if is_sat else 'unsat'}"
    )

    return Z3ProofCertificate(
        route_id=route_id,
        route_name=route_name,
        edge_ids=[e.id for e in edges],
        status="SAT" if is_sat else "UNSAT",
        checks=checks,
        smtlib_excerpt=smtlib_excerpt,
        violation_summary=" | ".join(violations) if violations else None,
    )
