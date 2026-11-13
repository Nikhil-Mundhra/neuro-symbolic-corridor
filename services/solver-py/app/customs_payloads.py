"""Auto-generator for Dubai Trade, Maqta Gateway, Oman Green Corridor, and Etihad Cargo JSONs."""

from __future__ import annotations

from datetime import UTC, datetime

from app.models import (
    CandidatePathEvaluation,
    CustomsPayloads,
    ShipmentSpec,
    TransportMode,
    Z3ProofCertificate,
)


def build_customs_payloads(
    solve_id: str,
    shipment: ShipmentSpec,
    optimal: CandidatePathEvaluation,
    z3_cert: Z3ProofCertificate,
) -> CustomsPayloads:
    """Generate compliant JSON payloads for UAE/Oman customs and spot freight booking."""
    now_iso = datetime.now(UTC).isoformat()
    uses_air = TransportMode.AIR_CARGO in optimal.modes
    uses_green_corridor = "AEWAJ" in optimal.node_sequence or "AEFJR" in optimal.node_sequence

    dubai_trade = {
        "system": "DP World / Dubai Trade - Mirsal 2 Declaration",
        "declaration_type": "SEA_TO_LAND_AIR_TRANSIT_BOND",
        "correlation_id": solve_id,
        "timestamp_utc": now_iso,
        "bol_reference": shipment.bol_number,
        "hs_code": shipment.hs_code,
        "teu_quantity": shipment.teu_count,
        "declared_cif_usd": shipment.cargo_value_usd,
        "cepa_claim": {
            "agreement": "UAE-INDIA-CEPA-2022",
            "origin_value_add_pct": shipment.cepa_value_add_pct,
            "preferential_duty_rate_pct": 0.0,
            "z3_proof_status": z3_cert.status,
        },
        "routed_corridor": optimal.node_sequence,
    }

    maqta_gateway = {
        "system": "AD Ports Group - Maqta Gateway ATLP",
        "message_type": "MULTIMODAL_REROUTE_MANIFEST",
        "terminal_code": "AEKHL" if "AEKHL" in optimal.node_sequence else optimal.node_sequence[1],
        "bol_reference": shipment.bol_number,
        "shipper": shipment.shipper,
        "consignee": shipment.consignee,
        "cold_chain_sla": {
            "required": shipment.is_temp_sensitive,
            "ceiling_celsius": shipment.max_temp_c,
            "predicted_arrival_celsius": optimal.predicted_arrival_temp_c,
        },
        "transit_edges": optimal.edge_ids,
        "estimated_total_hours": optimal.total_hours,
    }

    oman_green = {
        "system": "Oman Royal Customs (Bayan) ↔ Dubai Customs Green Corridor",
        "corridor_program": "GCC_SEALED_TRUCK_ETIR",
        "activated": uses_green_corridor,
        "border_gate": "AEWAJ_AL_WAJAJAH"
        if "AEWAJ" in optimal.node_sequence
        else "AEFJR_BONDED_RAIL",
        "electronic_seal_id": f"ETIR-GCC-{solve_id[:8].upper()}",
        "continuous_customs_custody": True,
        "z3_verified_rules": [c.rule_id for c in z3_cert.checks if c.passed],
    }

    etihad_cargo = None
    if uses_air:
        etihad_cargo = {
            "system": "Etihad Cargo Spot-Booking API (Zayed Int'l Airport - AUH)",
            "product_tier": "PharmaLife Active 2-8C"
            if shipment.is_temp_sensitive
            else "SecureTech Priority",
            "origin_airport": "AUH",
            "destination_airport": "FRA",
            "uld_allocation": f"{shipment.teu_count}x RKN Active Envirotainer"
            if shipment.is_temp_sensitive
            else f"{shipment.teu_count}x PMC Main-Deck Pallet",
            "bol_reference": shipment.bol_number,
            "booking_status": "READY_FOR_1CLICK_EXECUTION",
        }

    return CustomsPayloads(
        dubai_trade_mirsal2=dubai_trade,
        maqta_gateway_atlp=maqta_gateway,
        oman_green_corridor_etir=oman_green,
        etihad_cargo_eawb=etihad_cargo,
    )
