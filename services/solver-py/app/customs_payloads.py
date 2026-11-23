"""Auto-generator for Dubai Trade, Maqta Gateway, Oman Green Corridor, and Etihad Cargo JSONs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.models import (
    CandidatePathEvaluation,
    CustomsPayloads,
    ShipmentRequest,
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
        "terminal_code": (
            "AEKHL"
            if "AEKHL" in optimal.node_sequence
            else (
                optimal.node_sequence[1]
                if len(optimal.node_sequence) > 1
                else optimal.node_sequence[0]
            )
        ),
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


def build_mirsal2_declaration(
    shipment: ShipmentRequest,
    *,
    declarant_business_code: str,
    mpci_reference: str,
    uae_pass_session_id: str,
    is_intra_gcc_makasa: bool = False,
) -> dict[str, Any]:
    """Build Dubai Trade / Mirsal 2 declaration payload (pending partner B2G XSDs)."""
    if not shipment.customs_regime:
        raise ValueError("customs_regime is mandatory for Mirsal 2 declaration")

    primary_leg = shipment.legs[0]
    shipper = next(p for p in shipment.parties if p.role.value == "SHP")
    consignee = next(p for p in shipment.parties if p.role.value == "CNE")

    return {
        "schemaBoundaryNotice": "CANONICAL_MIRSAL2_TEMPLATE_PENDING_B2G_XSD",
        "authContext": {
            "authProvider": "UAE_PASS",
            "uaePassSessionId": uae_pass_session_id,
            "customsBusinessCode": declarant_business_code,
        },
        "generalDetails": {
            "regimeType": shipment.customs_regime.value,
            "declarationType": (
                "SEA_AIR_TRANSSHIPMENT"
                if shipment.transport_mode.value == "MULTIMODAL_SEA_AIR"
                else shipment.customs_regime.value
            ),
            "preArrivalFiling": True,
            "mpciPreloadReference": mpci_reference,
            "digitalMakasaIntraGcc": is_intra_gcc_makasa,
            "incoterms": shipment.incoterms_code,
        },
        "parties": {
            "consignorExporterName": shipper.legal_name,
            "consignorExporterAddress": shipper.address_line[:255],
            "consigneeImporterName": consignee.legal_name,
            "consigneeUaeTrn": consignee.uae_trn,
            "consigneeDubaiCustomsCode": consignee.dubai_customs_code,
        },
        "transportDocument": {
            "masterBillOfLadingOrAwb": shipment.transport_document_ref,
            "modeOfTransport": primary_leg.mode.value,
            "carrierCode": primary_leg.carrier_code,
            "voyageOrFlightNo": primary_leg.voyage_or_flight_number,
            "portOfLoading": primary_leg.origin_locode,
            "portOfDischarge": shipment.legs[-1].destination_locode,
            "containers": [
                {
                    "containerNo": eq.equipment_reference,
                    "isoSizeType": eq.iso_size_type_code,
                    "seals": eq.seal_numbers,
                }
                for eq in shipment.utilized_equipments
            ],
        },
        "invoiceAndAttestation": {
            "mofaicAttested": bool(shipment.mofaic_attested_invoice),
            "mofaicAttestationRef": shipment.mofaic_attestation_ref,
        },
        "items": [
            {
                "itemNo": idx + 1,
                "hsCode12Digit": item.hs_code_gcc12,
                "goodsDescription": item.goods_description,
                "countryOfOrigin": item.origin.country_of_origin,
                "certificateOfOriginNo": item.origin.certificate_of_origin_no,
                "cepaPreferentialClaim": item.origin.preferential_cepa_claimed,
                "cepaValueAddPct": (
                    str(item.origin.cepa_value_add_pct)
                    if item.origin.cepa_value_add_pct is not None
                    else None
                ),
                "grossWeightKg": str(item.gross_weight_kg),
                "netWeightKg": str(item.net_weight_kg),
                "cifValue": str(item.customs_value_amount),
                "currency": item.customs_value_currency,
                "regulatoryPermits": item.regulatory_permits,
            }
            for idx, item in enumerate(shipment.consignment_items)
        ],
    }


def build_atlp_etihad_rail_manifest(
    shipment: ShipmentRequest,
    *,
    atlp_trader_id: str,
    inland_rail_customs_terminal: str,
    wagon_consignment_map: dict[str, str],
) -> dict[str, Any]:
    """Build AD Ports / Maqta Gateway ATLP & Etihad Rail multimodal manifest payload."""
    shipper = next(p for p in shipment.parties if p.role.value == "SHP")
    consignee = next(p for p in shipment.parties if p.role.value == "CNE")

    return {
        "schemaBoundaryNotice": "CANONICAL_ATLP_ETIHAD_RAIL_TEMPLATE_PENDING_MAQTA_API_SPEC",
        "platform": "MAQTA_ATLP",
        "atlpTraderAccountId": atlp_trader_id,
        "abuDhabiCustomsAeoId": consignee.atlp_aeo_id or shipper.atlp_aeo_id,
        "inlandCustomsClearancePoint": inland_rail_customs_terminal,
        "masterTransportDocumentRef": shipment.transport_document_ref,
        "legs": [
            {
                "sequence": leg.leg_sequence,
                "mode": leg.mode.value,
                "origin": leg.origin_locode,
                "destination": leg.destination_locode,
                "operatorCode": leg.carrier_code,
                "tripOrTrainId": leg.voyage_or_flight_number,
                "etaUtc": leg.scheduled_arrival_utc.isoformat(),
            }
            for leg in shipment.legs
        ],
        "railConsignmentUnits": [
            {
                "containerIso6346": eq.equipment_reference,
                "isoSizeType": eq.iso_size_type_code,
                "assignedRailWagonId": wagon_consignment_map.get(eq.equipment_reference),
                "verifiedGrossMassKg": (
                    str(eq.verified_gross_mass_kg) if eq.verified_gross_mass_kg else None
                ),
                "seals": eq.seal_numbers,
            }
            for eq in shipment.utilized_equipments
        ],
        "cargoLines": [
            {
                "lineId": item.item_id,
                "hsCode12Digit": item.hs_code_gcc12,
                "description": item.goods_description,
                "grossWeightKg": str(item.gross_weight_kg),
                "originCountry": item.origin.country_of_origin,
            }
            for item in shipment.consignment_items
        ],
    }


def build_oman_bayan_and_etir_manifest(
    shipment: ShipmentRequest,
    *,
    border_post_code: str,
    bayan_company_cr: str,
    truck_plate_and_driver: str,
    etir_guarantee_id: str,
    etir_guarantee_chain_code: str,
    etir_holder_id: str,
    transit_security_bank: str,
    exit_port_code: str,
) -> dict[str, Any]:
    """Build Oman Bayan Transit Declaration + UNECE eTIR v4.3 I7 payload (seal deferred to I9)."""
    consignee = next(p for p in shipment.parties if p.role.value == "CNE")
    road_leg = shipment.legs[-1]
    cr_number = consignee.oman_cr_number or bayan_company_cr

    return {
        "bayanDeclaration": {
            "header": {
                "port": border_post_code,
                "decType": "TRANSIT",
                "decDate": shipment.issue_date.isoformat(),
                "mandatoryExportManifestRef": shipment.transport_document_ref,
                "applicationFeeOmr": "15.000",
            },
            "party": {
                "consigneeExporter": consignee.legal_name,
                "commercialRegNo": cr_number,
                "carrierName": road_leg.carrier_code,
                "carCaptDriver": truck_plate_and_driver,
            },
            "transportDocument": {
                "blAwbManifestNo": shipment.transport_document_ref,
                "voyageOrTripNo": road_leg.voyage_or_flight_number,
                "portOfLoading": road_leg.origin_locode,
                "portOfDischarge": road_leg.destination_locode,
                "exitPort": exit_port_code,
                "transitSecurityType": "INSURED",
                "guaranteeBank": transit_security_bank,
            },
            "items": [
                {
                    "htCode12Digit": item.hs_code_gcc12,
                    "goodsDescription": item.goods_description,
                    "origin": item.origin.country_of_origin,
                    "cifForeignValue": str(item.customs_value_amount),
                    "currency": item.customs_value_currency,
                    "grossWeightKg": str(item.gross_weight_kg),
                    "netWeightKg": str(item.net_weight_kg),
                    "packageType": item.package_type,
                    "packageQty": str(item.quantity),
                }
                for item in shipment.consignment_items
            ],
        },
        "etirI7RecordDeclaration": {
            "schemaVersion": "UNECE_eTIR_v4.3",
            "messageType": "I7_RecordDeclarationData",
            "Guarantee": {
                "GuaranteeReference": etir_guarantee_id,
                "GuaranteeChainCode": etir_guarantee_chain_code,
                "HolderId": etir_holder_id,
            },
            "Declaration": {
                "IssueDateTime": datetime.now(UTC).isoformat(),
                "Consignment": [
                    {
                        "SequenceNumeric": 1,
                        "TransportEquipment": [
                            {
                                "ID": eq.equipment_reference,
                                "sealIdsDeferredToI9StartTir": eq.seal_numbers,
                            }
                            for eq in shipment.utilized_equipments
                        ],
                        "ConsignmentItem": [
                            {
                                "CommodityCode": item.hs_code_gcc12,
                                "GoodsDescription": item.goods_description,
                                "GrossWeightMeasureKg": str(item.gross_weight_kg),
                                "OriginCountryCode": item.origin.country_of_origin,
                            }
                            for item in shipment.consignment_items
                        ],
                    }
                ],
            },
        },
    }


def build_iata_one_record_and_xfwb_bridge(
    shipment: ShipmentRequest,
    *,
    base_uri: str,
    chargeable_weight_kg: str,
) -> dict[str, Any]:
    """Build IATA ONE Record JSON-LD @graph + XFWB/EU ICS2 regulatory customs bridge."""
    shipper = next(p for p in shipment.parties if p.role.value == "SHP")
    consignee = next(p for p in shipment.parties if p.role.value == "CNE")
    air_leg = shipment.legs[-1]

    waybill_uri = f"{base_uri}/logistics-objects/waybills/{shipment.transport_document_ref}"
    booking_uri = f"{base_uri}/logistics-objects/bookings/{shipment.internal_request_id}"
    shipment_uri = f"{base_uri}/logistics-objects/shipments/{shipment.internal_request_id}"
    movement_uri = f"{base_uri}/logistics-objects/movements/{air_leg.voyage_or_flight_number}"

    unique_descriptions = {item.goods_description for item in shipment.consignment_items}
    is_uniform_commodity = len(unique_descriptions) == 1

    piece_nodes = []
    piece_refs = []
    for item in shipment.consignment_items:
        p_uri = f"{base_uri}/logistics-objects/pieces/{shipment.internal_request_id}-{item.item_id}"
        piece_refs.append({"@id": p_uri})
        piece_node: dict[str, Any] = {
            "@id": p_uri,
            "@type": "cargo:Piece",
            "cargo:grossWeight": {
                "@type": "cargo:Value",
                "cargo:numericalValue": float(item.gross_weight_kg),
                "cargo:unit": {"@id": "https://onerecord.iata.org/ns/coreCodeLists#KGM"},
            },
            "cargo:hsCode": item.hs_code_wco6 or item.hs_code_gcc12,
        }
        if not is_uniform_commodity:
            piece_node["cargo:goodsDescription"] = item.goods_description
        if item.is_dangerous_goods and item.hazmat_spec:
            piece_node["cargo:handlingInstructions"] = [
                f"DG {item.hazmat_spec.un_number} CLASS {item.hazmat_spec.un_hazmat_class}"
            ]
        piece_nodes.append(piece_node)

    shipment_node: dict[str, Any] = {
        "@id": shipment_uri,
        "@type": "cargo:Shipment",
        "cargo:containedPieces": piece_refs,
        "cargo:involvedParties": [
            {"partyRole": "SHP", "legalName": shipper.legal_name},
            {"partyRole": "CNE", "legalName": consignee.legal_name},
        ],
    }
    if is_uniform_commodity:
        shipment_node["cargo:goodsDescription"] = next(iter(unique_descriptions))

    return {
        "oneRecordJsonLd": {
            "@context": {"cargo": "https://onerecord.iata.org/ns/cargo#"},
            "@graph": [
                {
                    "@id": waybill_uri,
                    "@type": "cargo:Waybill",
                    "cargo:waybillNumber": shipment.transport_document_ref,
                    "cargo:referredBookingOption": {"@id": booking_uri},
                    "cargo:waybillLineItems": [
                        {
                            "@type": "cargo:WaybillLineItem",
                            "cargo:chargeableWeight": {
                                "@type": "cargo:Value",
                                "cargo:numericalValue": float(chargeable_weight_kg),
                                "cargo:unit": {
                                    "@id": "https://onerecord.iata.org/ns/coreCodeLists#KGM"
                                },
                            },
                        }
                    ],
                },
                {
                    "@id": booking_uri,
                    "@type": "cargo:Booking",
                    "cargo:waybillNumber": shipment.transport_document_ref,
                    "cargo:activitySequences": [{"@id": movement_uri}],
                },
                {
                    "@id": movement_uri,
                    "@type": "cargo:TransportMovement",
                    "cargo:transportIdentifier": air_leg.voyage_or_flight_number,
                    "cargo:departureLocation": air_leg.origin_locode,
                    "cargo:arrivalLocation": air_leg.destination_locode,
                    "cargo:scheduledDepartureTime": air_leg.scheduled_departure_utc.isoformat(),
                    "cargo:scheduledArrivalTime": air_leg.scheduled_arrival_utc.isoformat(),
                },
                shipment_node,
                *piece_nodes,
            ],
        },
        "regulatoryCustomsBridge": {
            "bridgeFormat": "Cargo-XML_XFWB3_and_EU_ICS2",
            "reason": "Customs authorities in 2026 do not broadly accept native ONE Record filings",
            "ics2FilingRequired": air_leg.destination_locode.startswith(("EU", "DE")),
            "consigneeEori": consignee.eori_number,
            "masterAwbNo": shipment.transport_document_ref,
        },
    }
