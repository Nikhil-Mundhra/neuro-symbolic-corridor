"""Comprehensive verification tests for Part B (Agent 1, 3, and 4 Specifications)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.customs_payloads import (
    build_atlp_etihad_rail_manifest,
    build_iata_one_record_and_xfwb_bridge,
    build_mirsal2_declaration,
    build_oman_bayan_and_etir_manifest,
)
from app.main import app
from app.models import (
    ChangeOfDestinationSpec,
    ConsignmentItem,
    EdgeTelemetryOverride,
    OriginPreferenceSpec,
    ReeferSpecification,
    ShipmentRequest,
    TelemetrySnapshot,
    ValidationHold,
    validate_iso6346,
)
from app.parser import ZeroHallucinationParser
from app.z3_compiler import (
    BOMInputItem,
    CEPAOriginDossier,
    ColdChainContainerConfig,
    ContainerType,
    CorridorLegSpec,
    DossierCustomsRegime,
    DossierTransportMode,
    ETIRLegTelemetry,
    EUICS2Release3Telemetry,
    MakasaLegTelemetry,
    Mirsal2SeaAirTelemetry,
    NeuroSymbolicCorridorCompiler,
    ThermalPhaseInput,
    ValuationBasis,
)

client = TestClient(app)


def _gold_standard_dossier(
    *,
    valuation: ValuationBasis = ValuationBasis.FOB,
    retrospective: bool = False,
) -> CEPAOriginDossier:
    return CEPAOriginDossier(
        hs_code_full="3002.15.00",
        is_immunological_note2_ch30=True,
        is_measured_dose_or_retail_pack=True,
        valuation_basis=valuation,
        fob_value_usd=250_000.0,
        exw_value_usd=230_000.0,
        direct_labour_cost_usd=45_000.0,
        direct_overhead_cost_usd=35_000.0,
        transport_container_tare_value_usd=15_000.0,
        bom_inputs=[
            BOMInputItem("API_MAB", 300213, 85_000.0, is_originating_party=True),
            BOMInputItem("BUFFER_EXCIPIENT", 382290, 40_000.0, is_originating_party=False),
            BOMInputItem(
                "GLASS_VIALS",
                701090,
                30_000.0,
                is_originating_party=False,
                is_retail_packaging=True,
            ),
        ],
        final_manufacture_in_india=True,
        only_minimal_operations_art3_5=False,
        has_valid_coo=True,
        coo_has_unique_serial_and_seal=True,
        export_date_day=10.0,
        coo_issue_date_day=18.0 if retrospective else 12.0,
        coo_working_days_after_export=8.0 if retrospective else 2.0,
        coo_marked_issued_retrospectively=retrospective,
        import_declaration_date_day=24.0,
    )


def _compliant_canonical_payload() -> dict[str, Any]:
    return {
        "internal_request_id": "REQ-2026-0001",
        "transport_mode": "MULTIMODAL_SEA_AIR",
        "transport_document_ref": "MAEU-8841209",
        "document_status": "ISSU",
        "customs_regime": "SEA_AIR_TRANSSHIPMENT",
        "issue_date": "2026-11-18",
        "incoterms_code": "CIF",
        "mofaic_attested_invoice": True,
        "mofaic_attestation_ref": "MOFAIC-2026-9910",
        "parties": [
            {
                "role": "SHP",
                "legal_name": "Cipla Biologics Exports Pvt Ltd",
                "address_line": "MIDC Industrial Area, Navi Mumbai",
                "country_code": "IN",
            },
            {
                "role": "CNE",
                "legal_name": "EuroMed ColdChain GmbH",
                "address_line": "CargoCity South, Frankfurt",
                "country_code": "DE",
                "eori_number": "DE445566778899",
            },
            {
                "role": "BRK",
                "legal_name": "AlFuttaim Logistics UAE LLC",
                "address_line": "JAFZA South, Dubai, UAE",
                "country_code": "AE",
                "uae_trn": "100123456789012",
                "uae_trn_fta_verified": True,
                "dubai_customs_code": "AE-1234567",
                "oman_cr_number": "OM-CR-9911",
                "atlp_aeo_id": "AE-AEO-554",
            },
        ],
        "legs": [
            {
                "leg_sequence": 1,
                "mode": "OCEAN",
                "origin_locode": "INNSA",
                "destination_locode": "AEJEA",
                "carrier_code": "MAEU",
                "voyage_or_flight_number": "441W",
                "scheduled_departure_utc": "2026-11-18T00:00:00Z",
                "scheduled_arrival_utc": "2026-11-21T00:00:00Z",
            },
            {
                "leg_sequence": 2,
                "mode": "AIR",
                "origin_locode": "AEAUH",
                "destination_locode": "EUFRA",
                "carrier_code": "EY",
                "voyage_or_flight_number": "EY991",
                "scheduled_departure_utc": "2026-11-21T08:00:00Z",
                "scheduled_arrival_utc": "2026-11-21T15:00:00Z",
            },
        ],
        "consignment_items": [
            {
                "item_id": "ITEM-1",
                "goods_description": "Monoclonal Antibody Biologics 2C-8C Sterile Vials",
                "hs_code_gcc12": "300215000010",
                "hs_code_wco6": "300215",
                "quantity": "40",
                "package_type": "CTN",
                "gross_weight_kg": "1200.0",
                "net_weight_kg": "950.0",
                "customs_value_amount": "1850000.00",
                "customs_value_currency": "AED",
                "origin": {
                    "country_of_origin": "IN",
                    "certificate_of_origin_no": "IN-CEPA-2026-7712",
                    "preferential_cepa_claimed": True,
                    "cepa_agreement_code": "UAE-INDIA-CEPA",
                    "cepa_value_add_pct": "48.5",
                },
                "is_reefer": True,
                "reefer_spec": {
                    "min_temp_c": "2.0",
                    "max_temp_c": "8.0",
                    "setpoint_temp_c": "5.0",
                    "humidity_pct": "45.0",
                },
                "is_dangerous_goods": False,
                "regulatory_permits": ["MOHAP-2026-112"],
            }
        ],
        "utilized_equipments": [
            {
                "equipment_reference": "KEIU9000798",
                "iso_size_type_code": "45R1",
                "seal_numbers": ["ESEAL-DXB-001"],
                "tare_weight_kg": "4800",
                "verified_gross_mass_kg": "6000",
                "stowage_baplie_pos": "0340882",
            }
        ],
        "cod_amendment": {
            "vessel_imo": "IMO9321483",
            "voyage_number": "441W",
            "container_iso6346": "KEIU9000798",
            "stowage_baplie_pos": "0340882",
            "accessible_without_restow": True,
            "estimated_restow_moves": 0,
            "carrier_cod_cutoff_utc": "2026-11-20T12:00:00Z",
            "original_port_of_discharge": "AEJEA",
            "requested_port_of_discharge": "AEFJR",
            "cod_request_submitted_utc": "2026-11-19T12:00:00Z",
        },
    }


@pytest.mark.unit
def test_agent1_chapter30_scenario_a_compliant_gold_standard() -> None:
    dossier = _gold_standard_dossier()
    legs = [
        CorridorLegSpec(
            leg_index=1,
            origin_node="INNSA",
            dest_node="AEJEA",
            mode=DossierTransportMode.SEA,
            customs_regime=DossierCustomsRegime.CEPA_DIRECT_SEA,
            is_non_party_transit=False,
            arc_phase=ThermalPhaseInput(
                "ARC", 72.0, 28.0, shore_power_plugged_in=True, charge_hours_requested=8.0
            ),
            dwell_phase=ThermalPhaseInput("DWELL", 2.0, 38.0, max_hub_dwell_limit_hours=4.0),
            inspect_phase=ThermalPhaseInput("INSPECT", 0.5, 25.0),
        ),
        CorridorLegSpec(
            leg_index=2,
            origin_node="AEJEA",
            dest_node="AEDWC",
            mode=DossierTransportMode.ROAD,
            customs_regime=DossierCustomsRegime.UAE_BONDED_SEA_AIR,
            is_non_party_transit=False,
            mirsal2_telemetry=Mirsal2SeaAirTelemetry(
                mirsal2_transit_boe_lodged=True,
                dubai_customs_smart_eseal_active=True,
                transfer_duration_hours=0.75,
            ),
            arc_phase=ThermalPhaseInput("ARC", 0.75, 40.0),
            dwell_phase=ThermalPhaseInput(
                "DWELL", 1.5, 38.0, shore_power_plugged_in=True, charge_hours_requested=1.5
            ),
            inspect_phase=ThermalPhaseInput("INSPECT", 0.0, 25.0),
        ),
        CorridorLegSpec(
            leg_index=3,
            origin_node="AEDWC",
            dest_node="EUFRA",
            mode=DossierTransportMode.AIR,
            customs_regime=DossierCustomsRegime.EU_ICS2_AIR_ENTRY,
            is_non_party_transit=False,
            ics2_telemetry=EUICS2Release3Telemetry(
                placi_filing_code="F24",
                placi_lodged_ts=100.0,
                aircraft_loading_ts=103.5,
                has_active_dnl_flag=False,
                has_unresolved_rfi_flag=False,
                has_hrcm_flag=False,
                hrcm_enhanced_screening_completed=False,
                ens_complete_filing_code="F27",
                ens_complete_lodged_ts=104.0,
                aircraft_takeoff_ts=105.0,
                eu_first_port_arrival_ts=111.8,
                is_multiple_filing=False,
            ),
            arc_phase=ThermalPhaseInput("ARC", 6.8, 18.0),
            dwell_phase=ThermalPhaseInput("DWELL", 0.5, 18.0),
            inspect_phase=ThermalPhaseInput("INSPECT", 0.0, 18.0),
        ),
    ]
    cfg = ColdChainContainerConfig(
        container_type=ContainerType.ENVIROTAINER_RAP_E2,
        use_strict_sla_30h_autonomy=False,
        initial_battery_hours=60.0,
        consignee_sla_max_total_hours=120.0,
    )

    res = NeuroSymbolicCorridorCompiler().verify_corridor(dossier, legs, cfg)
    assert res.is_sat is True
    assert res.unsat_core == []
    assert res.calculated_exact_mkt_c == pytest.approx(5.0, abs=0.05)
    assert res.z3_upper_bound_ndf_ratio is not None and res.z3_upper_bound_ndf_ratio <= 1.0
    assert res.qvc_achieved_pct is not None and res.qvc_achieved_pct >= 40.0


@pytest.mark.unit
def test_agent1_chapter30_scenario_b_and_c_unsat_cores_and_variants() -> None:
    # Scenario B: Minimal ops + <40% QVC + Oman non-manipulation cert missing + e-TIR Error 310 + >40C charge + unpowered dwell
    bad_dossier = CEPAOriginDossier(
        hs_code_full="3002.15.00",
        is_immunological_note2_ch30=True,
        is_measured_dose_or_retail_pack=True,
        valuation_basis=ValuationBasis.FOB,
        fob_value_usd=250_000.0,
        exw_value_usd=230_000.0,
        direct_labour_cost_usd=10_000.0,
        direct_overhead_cost_usd=5_000.0,
        transport_container_tare_value_usd=10_000.0,
        bom_inputs=[
            BOMInputItem("PREFILLED_BULK", 300215, 180_000.0, is_originating_party=False),
        ],
        final_manufacture_in_india=True,
        only_minimal_operations_art3_5=True,
        has_valid_coo=True,
        coo_has_unique_serial_and_seal=True,
        export_date_day=1.0,
        coo_issue_date_day=2.0,
        coo_working_days_after_export=1.0,
        coo_marked_issued_retrospectively=False,
        import_declaration_date_day=10.0,
    )
    legs_b = [
        CorridorLegSpec(
            leg_index=1,
            origin_node="INNSA",
            dest_node="OMSOH",
            mode=DossierTransportMode.SEA,
            customs_regime=DossierCustomsRegime.OMAN_TRANSIT_PORT,
            is_non_party_transit=True,
            remains_under_customs_control=True,
            entered_local_trade_or_consumption=False,
            undergoes_ops_beyond_preservation=False,
            has_non_manipulation_certificate=False,
            has_single_through_transport_doc=False,
            arc_phase=ThermalPhaseInput("ARC", 60.0, 22.0),
        ),
        CorridorLegSpec(
            leg_index=2,
            origin_node="OMSOH",
            dest_node="AEDWC",
            mode=DossierTransportMode.ROAD,
            customs_regime=DossierCustomsRegime.ETIR_CROSS_BORDER,
            is_non_party_transit=False,
            etir_telemetry=ETIRLegTelemetry(
                holder_authorized_in_itdb=True,
                e9_advance_data_ts=1.0,
                i1_accept_guarantee_ts=2.0,
                i7_record_declaration_ts=3.0,
                i7_contains_seal_id=True,
                i9_start_tir_ts=4.0,
                i9_seal_id="SEAL-1",
                i15_notify_customs_ts=8.0,
                border_arrival_ts=6.0,
                i11_terminate_tir_ts=9.0,
                i11_seal_id="SEAL-1",
                i13_discharge_tir_ts=10.0,
            ),
            arc_phase=ThermalPhaseInput("ARC", 6.0, 35.0),
            dwell_phase=ThermalPhaseInput(
                "DWELL", 4.0, 44.0, shore_power_plugged_in=True, charge_hours_requested=2.0
            ),
            inspect_phase=ThermalPhaseInput("INSPECT", 3.5, 44.0, unpowered_exposure_hours=3.5),
        ),
        CorridorLegSpec(
            leg_index=3,
            origin_node="AEDWC",
            dest_node="EUFRA",
            mode=DossierTransportMode.AIR,
            customs_regime=DossierCustomsRegime.EU_ICS2_AIR_ENTRY,
            is_non_party_transit=False,
            ics2_telemetry=EUICS2Release3Telemetry(
                placi_filing_code="F24",
                placi_lodged_ts=10.0,
                aircraft_loading_ts=12.0,
                has_active_dnl_flag=False,
                has_unresolved_rfi_flag=False,
                has_hrcm_flag=False,
                hrcm_enhanced_screening_completed=False,
                ens_complete_filing_code="F27",
                ens_complete_lodged_ts=13.0,
                aircraft_takeoff_ts=14.0,
                eu_first_port_arrival_ts=20.8,
                is_multiple_filing=False,
            ),
            arc_phase=ThermalPhaseInput("ARC", 6.8, 18.0),
        ),
    ]
    res_b = NeuroSymbolicCorridorCompiler().verify_corridor(
        bad_dossier,
        legs_b,
        ColdChainContainerConfig(
            container_type=ContainerType.ENVIROTAINER_RKN_E1,
            use_strict_sla_30h_autonomy=False,
            initial_battery_hours=58.0,
        ),
    )
    assert res_b.is_sat is False
    for expected in (
        "CEPA_ORIGIN::ANNEX_3B_CTSH_OR_ART_3_4_DEMINIMIS",
        "CEPA_ORIGIN::ANNEX_3B_QVC_THRESHOLD_40FOB_35EXW",
        "CEPA_ORIGIN::ART_3_5_NO_MINIMAL_OPERATIONS",
        "CEPA_TRANSIT::ART_3_12_NON_MANIPULATION_CERT_LEG_1",
        "GCC_CUSTOMS::ETIR_ANNEX11_MSG_SEQ_LEG_2",
        "GCC_CUSTOMS::ETIR_ERROR_309_310_SEAL_LINEAGE_LEG_2",
        "GDP_THERMAL::ENVIROTAINER_CHARGING_TEMP_LIMIT_LEG_2_DWELL",
        "GDP_THERMAL::USP_1079_2_SPIKE_CEILING_15C_LEG_2_INSPECT",
        "GDP_THERMAL::SLA_CUMULATIVE_EXCURSION_MAX_2H_ABOVE_8C",
        "GDP_THERMAL::USP_1079_2_HAYNES_MKT_24H_WINDOW_LEG_2_INSPECT",
    ):
        assert expected in res_b.unsat_core

    # Scenario C: EU ICS2 Release 3 PLACI + HRCM + 4h ENS failure
    legs_c = [
        CorridorLegSpec(
            leg_index=3,
            origin_node="AEAUH",
            dest_node="EUFRA",
            mode=DossierTransportMode.AIR,
            customs_regime=DossierCustomsRegime.EU_ICS2_AIR_ENTRY,
            is_non_party_transit=False,
            ics2_telemetry=EUICS2Release3Telemetry(
                placi_filing_code="F26",
                placi_lodged_ts=105.0,
                aircraft_loading_ts=103.5,
                has_active_dnl_flag=False,
                has_unresolved_rfi_flag=False,
                has_hrcm_flag=True,
                hrcm_enhanced_screening_completed=False,
                ens_complete_filing_code="F21+F26",
                ens_complete_lodged_ts=109.7,
                aircraft_takeoff_ts=105.0,
                eu_first_port_arrival_ts=111.8,
                is_multiple_filing=True,
                carrier_eori_matches=True,
                mawb_number_matches=True,
                house_declarant_eori_matches=True,
            ),
            arc_phase=ThermalPhaseInput("ARC", 6.8, 18.0),
        )
    ]
    res_c = NeuroSymbolicCorridorCompiler().verify_corridor(
        _gold_standard_dossier(valuation=ValuationBasis.EXW, retrospective=True),
        legs_c,
        ColdChainContainerConfig(container_type=ContainerType.ENVIROTAINER_RKN_E1),
    )
    assert res_c.is_sat is False
    assert "EU_ICS2::ART_106_PLACI_PRE_LOADING_FILING_LEG_3" in res_c.unsat_core
    assert "EU_ICS2::ART_106_NO_DNL_HRCM_RFI_BLOCK_LEG_3" in res_c.unsat_core
    assert "EU_ICS2::ART_106_ENS_PRE_ARRIVAL_LEAD_TIME_LEG_3" in res_c.unsat_core

    # Additional regimes & RKN t2 coverage: Makasa, Missing telemetry, short-haul <4h ENS, RKN t2 dry-ice
    legs_extra = [
        CorridorLegSpec(
            leg_index=1,
            origin_node="OMSOH",
            dest_node="AEWAJ",
            mode=DossierTransportMode.ROAD,
            customs_regime=DossierCustomsRegime.MAKASA_CROSS_BORDER,
            is_non_party_transit=False,
            makasa_telemetry=MakasaLegTelemetry(True, True, True, True, True),
            arc_phase=ThermalPhaseInput("ARC", 4.0, 32.0),
        ),
        CorridorLegSpec(
            leg_index=2,
            origin_node="AEWAJ",
            dest_node="AEAUH",
            mode=DossierTransportMode.ROAD,
            customs_regime=DossierCustomsRegime.ETIR_CROSS_BORDER,
            is_non_party_transit=False,
            etir_telemetry=ETIRLegTelemetry(
                holder_authorized_in_itdb=True,
                e9_advance_data_ts=1.0,
                i1_accept_guarantee_ts=2.0,
                i7_record_declaration_ts=3.0,
                i7_contains_seal_id=False,
                i9_start_tir_ts=4.0,
                i9_seal_id="SEAL-OLD",
                i15_notify_customs_ts=5.0,
                border_arrival_ts=6.0,
                i11_terminate_tir_ts=7.0,
                i11_seal_id="SEAL-NEW",
                i13_discharge_tir_ts=8.0,
                customs_inspection_broke_seal=True,
                new_seal_recorded_in_etir=True,
            ),
            arc_phase=ThermalPhaseInput("ARC", 2.0, 34.0),
        ),
        CorridorLegSpec(
            leg_index=3,
            origin_node="AEAUH",
            dest_node="EUFRA",
            mode=DossierTransportMode.AIR,
            customs_regime=DossierCustomsRegime.EU_ICS2_AIR_ENTRY,
            is_non_party_transit=False,
            ics2_telemetry=EUICS2Release3Telemetry(
                placi_filing_code="F20",
                placi_lodged_ts=1.0,
                aircraft_loading_ts=2.0,
                has_active_dnl_flag=False,
                has_unresolved_rfi_flag=False,
                has_hrcm_flag=False,
                hrcm_enhanced_screening_completed=False,
                ens_complete_filing_code="F20",
                ens_complete_lodged_ts=2.5,
                aircraft_takeoff_ts=3.0,
                eu_first_port_arrival_ts=6.0,  # 3.0h short-haul
                is_multiple_filing=False,
            ),
            arc_phase=ThermalPhaseInput("ARC", 3.0, 20.0, dry_ice_re_iced_kg=2.0),
        ),
    ]
    res_t2 = NeuroSymbolicCorridorCompiler().verify_corridor(
        _gold_standard_dossier(),
        legs_extra,
        ColdChainContainerConfig(
            container_type=ContainerType.ENVIROTAINER_RKN_T2,
            initial_battery_hours=72.0,
            initial_dry_ice_kg=50.0,
        ),
    )
    assert res_t2.is_sat is True

    res_rap_strict = NeuroSymbolicCorridorCompiler().verify_corridor(
        _gold_standard_dossier(),
        [legs_extra[2]],
        ColdChainContainerConfig(
            container_type=ContainerType.ENVIROTAINER_RAP_E2,
            use_strict_sla_30h_autonomy=True,
            initial_battery_hours=30.0,
        ),
    )
    assert res_rap_strict.is_sat is True

    # Missing telemetry payloads on each regime produce UNSAT
    missing_legs = [
        CorridorLegSpec(
            1,
            "OMSOH",
            "AEWAJ",
            DossierTransportMode.ROAD,
            DossierCustomsRegime.ETIR_CROSS_BORDER,
            False,
            arc_phase=ThermalPhaseInput("ARC", 1.0, 20.0),
        ),
        CorridorLegSpec(
            2,
            "OMSOH",
            "AEWAJ",
            DossierTransportMode.ROAD,
            DossierCustomsRegime.MAKASA_CROSS_BORDER,
            False,
        ),
        CorridorLegSpec(
            3,
            "AEJEA",
            "AEDWC",
            DossierTransportMode.ROAD,
            DossierCustomsRegime.UAE_BONDED_SEA_AIR,
            False,
        ),
        CorridorLegSpec(
            4,
            "AEDWC",
            "EUFRA",
            DossierTransportMode.AIR,
            DossierCustomsRegime.EU_ICS2_AIR_ENTRY,
            False,
        ),
    ]
    res_missing = NeuroSymbolicCorridorCompiler().verify_corridor(
        _gold_standard_dossier(),
        missing_legs,
        ColdChainContainerConfig(container_type=ContainerType.ENVIROTAINER_RKN_E1),
    )
    assert res_missing.is_sat is False


@pytest.mark.unit
def test_agent3_iso6346_validators_parser_and_endpoint() -> None:
    assert validate_iso6346("keiu9000798") == "KEIU9000798"
    assert validate_iso6346("ABCU4000000") == "ABCU4000000"  # remainder 10 -> 0
    with pytest.raises(ValueError, match="ISO 6346"):
        validate_iso6346("BAD123")
    with pytest.raises(ValueError, match="check digit mismatch"):
        validate_iso6346("KEIU9000799")

    # Happy path canonical payload & /validate-shipment 200
    payload = _compliant_canonical_payload()
    parser = ZeroHallucinationParser()
    validated = parser.evaluate(payload)
    assert isinstance(validated, ShipmentRequest)

    resp_ok = client.post("/validate-shipment", json={"shipment": payload})
    assert resp_ok.status_code == 200
    assert resp_ok.json()["internal_request_id"] == "REQ-2026-0001"

    # Cross-document conflicts + missing compliance gates -> ValidationHold (422)
    incomplete = _compliant_canonical_payload()
    incomplete["mofaic_attested_invoice"] = False
    incomplete["parties"][1]["eori_number"] = None
    incomplete["parties"][2]["uae_trn"] = None
    incomplete["consignment_items"][0]["hs_code_gcc12"] = None
    incomplete["consignment_items"][0]["hs_code_wco6"] = None
    incomplete["consignment_items"][0]["origin"]["preferential_cepa_claimed"] = False
    incomplete["consignment_items"][0]["origin"]["certificate_of_origin_no"] = None
    incomplete["consignment_items"][0]["is_dangerous_goods"] = True
    incomplete["consignment_items"][0]["hazmat_spec"] = {
        "un_number": "UN3481",
        "un_hazmat_class": "9",
        "proper_shipping_name": "Lithium Ion Batteries",
    }
    hold = parser.evaluate(
        incomplete,
        document_texts={
            "invoice": "HS CODE: 300215000010",
            "packing_list": "HS CODE: 300490000000",
        },
    )
    assert isinstance(hold, ValidationHold)
    assert hold.autonomous_dispatch_blocked is True
    reasons = {f.reason_code for f in hold.missing_compliance_fields}
    assert "CONFLICTING_DOCUMENT_VALUES" in reasons
    assert "MISSING_MANDATORY_FIELD" in reasons

    resp_hold = client.post("/validate-shipment", json=incomplete)
    assert resp_hold.status_code == 422
    assert resp_hold.json()["status"] == "VALIDATION_HOLD"

    # Structural validation errors map into ValidationHold cleanly
    bad_struct = _compliant_canonical_payload()
    bad_struct["parties"][2]["uae_trn"] = "999"
    bad_struct["parties"][2]["dubai_customs_code"] = "BAD"
    bad_struct["utilized_equipments"][0]["stowage_baplie_pos"] = "BAD"
    bad_struct["cod_amendment"]["vessel_imo"] = "BADIMO"
    hold_struct = parser.evaluate(bad_struct)
    assert isinstance(hold_struct, ValidationHold)
    assert any(f.reason_code == "UNVERIFIED_FORMAT" for f in hold_struct.missing_compliance_fields)

    # Check direct Pydantic validators for edge errors
    with pytest.raises(ValidationError):
        ReeferSpecification(min_temp_c=Decimal("10"), max_temp_c=Decimal("5"))
    with pytest.raises(ValidationError):
        ReeferSpecification(
            min_temp_c=Decimal("2"), max_temp_c=Decimal("8"), setpoint_temp_c=Decimal("12")
        )
    with pytest.raises(ValidationError):
        OriginPreferenceSpec(country_of_origin="IN", preferential_cepa_claimed=True)
    with pytest.raises(ValidationError):
        OriginPreferenceSpec(
            country_of_origin="IN",
            preferential_cepa_claimed=True,
            certificate_of_origin_no="COO-1",
            cepa_value_add_pct=None,
        )
    base_item = _compliant_canonical_payload()["consignment_items"][0]
    for bad_update in (
        {"hs_code_gcc12": "123456"},
        {"hs_code_wco6": "123"},
        {"net_weight_kg": "5000.0"},
        {"is_reefer": True, "reefer_spec": None},
        {"is_dangerous_goods": True, "hazmat_spec": None},
    ):
        with pytest.raises(ValidationError):
            ConsignmentItem.model_validate({**base_item, **bad_update})

    with pytest.raises(ValidationError):
        ChangeOfDestinationSpec(
            vessel_imo="IMO9321483",
            voyage_number="441W",
            container_iso6346="KEIU9000798",
            stowage_baplie_pos="0340882",
            accessible_without_restow=True,
            estimated_restow_moves=2,
            carrier_cod_cutoff_utc=datetime(2026, 11, 20, tzinfo=UTC),
            original_port_of_discharge="AEJEA",
            requested_port_of_discharge="AEFJR",
            cod_request_submitted_utc=datetime(2026, 11, 19, tzinfo=UTC),
        )
    with pytest.raises(ValidationError):
        ChangeOfDestinationSpec(
            vessel_imo="IMO9321483",
            voyage_number="441W",
            container_iso6346="KEIU9000798",
            stowage_baplie_pos="0340882",
            accessible_without_restow=False,
            estimated_restow_moves=1,
            carrier_cod_cutoff_utc=datetime(2026, 11, 19, tzinfo=UTC),
            original_port_of_discharge="AEJEA",
            requested_port_of_discharge="AEFJR",
            cod_request_submitted_utc=datetime(2026, 11, 20, tzinfo=UTC),
        )
    with pytest.raises(ValidationError):
        ChangeOfDestinationSpec(
            vessel_imo="IMO9321483",
            voyage_number="441W",
            container_iso6346="BAD",
            stowage_baplie_pos="BAD",
            accessible_without_restow=False,
            estimated_restow_moves=1,
            carrier_cod_cutoff_utc=datetime(2026, 11, 20, tzinfo=UTC),
            original_port_of_discharge="X",
            requested_port_of_discharge="AEFJR",
            cod_request_submitted_utc=datetime(2026, 11, 19, tzinfo=UTC),
        )
    bad_parties = _compliant_canonical_payload()
    bad_parties["parties"] = [bad_parties["parties"][0], bad_parties["parties"][2]]
    with pytest.raises(ValidationError, match="SHIPPER"):
        ShipmentRequest.model_validate(bad_parties)

    # Direct instantiation check for TelemetrySnapshot & EdgeTelemetryOverride
    snap = TelemetrySnapshot(
        disruption={"hormuz_delay_hours": 72.0},
        edge_overrides={
            "E_INNSA_AEFJR_SEA": EdgeTelemetryOverride(
                edge_id="E_INNSA_AEFJR_SEA",
                base_hours=92.0,
                source_provider="marinetraffic_vi06",
                updated_at_utc="2026-11-18T12:00:00Z",
            )
        },
        last_updated_utc="2026-11-18T12:00:00Z",
        active_sources=["marinetraffic_vi06"],
        event_count=1,
    )
    assert snap.edge_overrides["E_INNSA_AEFJR_SEA"].base_hours == 92.0


@pytest.mark.unit
def test_agent3_schema_accurate_customs_payload_builders() -> None:
    req = ShipmentRequest.model_validate(_compliant_canonical_payload())

    mirsal2 = build_mirsal2_declaration(
        req,
        declarant_business_code="AE-1234567",
        mpci_reference="MPCI-2026-001",
        uae_pass_session_id="UAEPASS-SESS-77",
        is_intra_gcc_makasa=False,
    )
    assert mirsal2["authContext"]["authProvider"] == "UAE_PASS"
    assert mirsal2["items"][0]["hsCode12Digit"] == "300215000010"

    atlp = build_atlp_etihad_rail_manifest(
        req,
        atlp_trader_id="ATLP-TRD-09",
        inland_rail_customs_terminal="KIZAD-RAIL-ICD",
        wagon_consignment_map={"KEIU9000798": "ER-WAGON-441"},
    )
    assert atlp["platform"] == "MAQTA_ATLP"
    assert atlp["railConsignmentUnits"][0]["assignedRailWagonId"] == "ER-WAGON-441"

    bayan_etir = build_oman_bayan_and_etir_manifest(
        req,
        border_post_code="AEWAJ",
        bayan_company_cr="OM-CR-9911",
        truck_plate_and_driver="OM-4412-DX / Driver A",
        etir_guarantee_id="ETIR-G-2026-88",
        etir_guarantee_chain_code="IRU",
        etir_holder_id="OM-HOLDER-01",
        transit_security_bank="Bank Muscat",
        exit_port_code="AEWAJ",
    )
    assert bayan_etir["bayanDeclaration"]["header"]["applicationFeeOmr"] == "15.000"
    te = bayan_etir["etirI7RecordDeclaration"]["Declaration"]["Consignment"][0][
        "TransportEquipment"
    ][0]
    assert "SealIDs" not in te  # UNECE eTIR Error 310 prevention

    # Uniform commodity -> Shipment#goodsDescription
    one_rec_uniform = build_iata_one_record_and_xfwb_bridge(
        req, base_uri="https://api.example.ae", chargeable_weight_kg="1200.0"
    )
    graph_u = one_rec_uniform["oneRecordJsonLd"]["@graph"]
    shipment_node_u = next(n for n in graph_u if n["@type"] == "cargo:Shipment")
    assert "cargo:goodsDescription" in shipment_node_u

    # Multi-commodity -> Piece#goodsDescription
    multi_payload = _compliant_canonical_payload()
    second_item = dict(multi_payload["consignment_items"][0])
    second_item["item_id"] = "ITEM-2"
    second_item["goods_description"] = "Adjuvant Buffer Vials"
    second_item["is_dangerous_goods"] = True
    second_item["hazmat_spec"] = {
        "un_number": "UN3481",
        "un_hazmat_class": "9",
        "proper_shipping_name": "Lithium Batteries",
        "msds_document_ref": "MSDS-2026-01",
        "un383_certified": True,
    }
    multi_payload["consignment_items"].append(second_item)
    req_multi = ShipmentRequest.model_validate(multi_payload)
    one_rec_multi = build_iata_one_record_and_xfwb_bridge(
        req_multi, base_uri="https://api.example.ae", chargeable_weight_kg="2400.0"
    )
    graph_m = one_rec_multi["oneRecordJsonLd"]["@graph"]
    shipment_node_m = next(n for n in graph_m if n["@type"] == "cargo:Shipment")
    assert "cargo:goodsDescription" not in shipment_node_m
    pieces_m = [n for n in graph_m if n["@type"] == "cargo:Piece"]
    assert len(pieces_m) == 2
    assert all("cargo:goodsDescription" in p for p in pieces_m)

    # Extra branch checks for 95%+ branch coverage on models.py & parser.py
    req_no_regime = req.model_copy(update={"customs_regime": None})
    with pytest.raises(ValueError, match="customs_regime"):
        build_mirsal2_declaration(
            req_no_regime,
            declarant_business_code="AE-1234567",
            mpci_reference="MPCI-1",
            uae_pass_session_id="SESS-1",
        )

    assert date.fromisoformat("2026-11-18") == req.issue_date
    assert Decimal("1850000.00") == req.consignment_items[0].customs_value_amount
