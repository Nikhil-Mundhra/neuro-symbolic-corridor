"""Guided finite-state Bill of Lading parser and curated Gulf Corridor scenarios."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from app.models import (
    DisruptionState,
    MissingComplianceField,
    ParseBoLResponse,
    ScenarioPreset,
    ShipmentRequest,
    ShipmentSpec,
    ValidationHold,
)

SCENARIO_PRESETS: list[ScenarioPreset] = [
    ScenarioPreset(
        id="pharma-biologics-cepa",
        title="Biologics Cold-Chain (Pharma)",
        subtitle="JNPT Mumbai → Frankfurt | 4 TEU | 2°C–8°C GDP SLA | UAE-India CEPA",
        raw_bol_text=(
            "BILL OF LADING: BOL-INNSA-2026-8841\n"
            "SHIPPER: Cipla Biologics Exports Pvt Ltd, Navi Mumbai, IN\n"
            "CONSIGNEE: EuroMed ColdChain Distribution GmbH, Frankfurt, DE\n"
            "CARGO: Monoclonal Antibody Vaccines (Active Reefer 2.0C-8.0C GDP)\n"
            "HS CODE: 3002.15.00 | QUANTITY: 4 TEU | VALUE: USD 1,850,000\n"
            "CEPA ORIGIN VALUE-ADD: 48.5% | INITIAL TEMP: 3.5C | MAX TEMP: 8.0C\n"
            "MAX TRANSIT SLA: 144 HOURS | DEMURRAGE RATE: USD 280/TEU/DAY"
        ),
        shipment=ShipmentSpec(
            bol_number="BOL-INNSA-2026-8841",
            shipper="Cipla Biologics Exports Pvt Ltd, Navi Mumbai",
            consignee="EuroMed ColdChain Distribution GmbH, Frankfurt",
            cargo_description="Monoclonal Antibody Biologics (2°C–8°C GDP Cold-Chain)",
            hs_code="3002.15.00",
            origin_node="INNSA",
            destination_node="EUFRA",
            teu_count=4,
            cargo_value_usd=1_850_000.0,
            cepa_value_add_pct=48.5,
            is_temp_sensitive=True,
            initial_temp_c=3.5,
            max_temp_c=8.0,
            max_transit_hours=144.0,
            demurrage_usd_per_teu_day=280.0,
            spoilage_risk_pct_on_breach=100.0,
            value_of_time_usd_per_hour=420.0,
        ),
        default_disruption=DisruptionState(
            hormuz_delay_hours=72.0,
            jebel_ali_congestion_hours=24.0,
            red_sea_surcharge_usd=1850.0,
            reefer_fault=True,
            reefer_ambient_drift_c_per_hour=0.035,
            require_cepa_zero_tariff=True,
        ),
    ),
    ScenarioPreset(
        id="auto-ev-drivetrain-cepa",
        title="EV Drivetrain Gearboxes (CEPA)",
        subtitle="JNPT → KIZAD / EU | 12 TEU | 46% India Origin Value-Add | JIT Assembly",
        raw_bol_text=(
            "BILL OF LADING: BOL-INNSA-2026-4419\n"
            "SHIPPER: Bharat Forge Precision Mobility Ltd, Pune, IN\n"
            "CONSIGNEE: RheinAuto Powertrain Logistics AG, Rotterdam, NL\n"
            "CARGO: Precision EV Reduction Gearboxes (Bonded JIT Assembly)\n"
            "HS CODE: 8708.40.00 | QUANTITY: 12 TEU | VALUE: USD 920,000\n"
            "CEPA ORIGIN VALUE-ADD: 46.0% | INITIAL TEMP: 22.0C | MAX TEMP: 45.0C\n"
            "MAX TRANSIT SLA: 460 HOURS | DEMURRAGE RATE: USD 240/TEU/DAY"
        ),
        shipment=ShipmentSpec(
            bol_number="BOL-INNSA-2026-4419",
            shipper="Bharat Forge Precision Mobility Ltd, Pune",
            consignee="RheinAuto Powertrain Logistics AG, Rotterdam",
            cargo_description="Precision EV Reduction Gearboxes (CEPA 0% Duty)",
            hs_code="8708.40.00",
            origin_node="INNSA",
            destination_node="EUFRA",
            teu_count=12,
            cargo_value_usd=920_000.0,
            cepa_value_add_pct=46.0,
            is_temp_sensitive=False,
            initial_temp_c=22.0,
            max_temp_c=45.0,
            max_transit_hours=460.0,
            demurrage_usd_per_teu_day=240.0,
            spoilage_risk_pct_on_breach=8.0,
            value_of_time_usd_per_hour=165.0,
        ),
        default_disruption=DisruptionState(
            hormuz_delay_hours=84.0,
            jebel_ali_congestion_hours=36.0,
            red_sea_surcharge_usd=1200.0,
            reefer_fault=False,
            reefer_ambient_drift_c_per_hour=0.0,
            require_cepa_zero_tariff=True,
        ),
    ),
    ScenarioPreset(
        id="petchem-specialty-polymers",
        title="Specialty Polymers (Baseline Cost)",
        subtitle="JNPT → EU | 20 TEU | Non-Perishable Bulk | Hormuz Clear vs Congested",
        raw_bol_text=(
            "BILL OF LADING: BOL-INNSA-2026-1092\n"
            "SHIPPER: Reliance Advanced Materials Ltd, Jamnagar, IN\n"
            "CONSIGNEE: EuroChem Industrial Compounding BV, Rotterdam, NL\n"
            "CARGO: High-Density Polypropylene Resins (Containerized Bulk)\n"
            "HS CODE: 3902.10.00 | QUANTITY: 20 TEU | VALUE: USD 540,000\n"
            "CEPA ORIGIN VALUE-ADD: 52.0% | INITIAL TEMP: 25.0C | MAX TEMP: 55.0C\n"
            "MAX TRANSIT SLA: 600 HOURS | DEMURRAGE RATE: USD 195/TEU/DAY"
        ),
        shipment=ShipmentSpec(
            bol_number="BOL-INNSA-2026-1092",
            shipper="Reliance Advanced Materials Ltd, Jamnagar",
            consignee="EuroChem Industrial Compounding BV, Rotterdam",
            cargo_description="High-Density Polypropylene Resins (20 TEU Bulk)",
            hs_code="3902.10.00",
            origin_node="INNSA",
            destination_node="EUFRA",
            teu_count=20,
            cargo_value_usd=540_000.0,
            cepa_value_add_pct=52.0,
            is_temp_sensitive=False,
            initial_temp_c=25.0,
            max_temp_c=55.0,
            max_transit_hours=600.0,
            demurrage_usd_per_teu_day=195.0,
            spoilage_risk_pct_on_breach=0.0,
            value_of_time_usd_per_hour=55.0,
        ),
        default_disruption=DisruptionState(
            hormuz_delay_hours=0.0,
            jebel_ali_congestion_hours=0.0,
            red_sea_surcharge_usd=0.0,
            reefer_fault=False,
            reefer_ambient_drift_c_per_hour=0.0,
            require_cepa_zero_tariff=True,
        ),
    ),
]


def get_scenarios() -> list[ScenarioPreset]:
    return SCENARIO_PRESETS


def parse_bol_text(raw_text: str) -> ParseBoLResponse:
    """Guided finite-state schema extractor converting unstructured BoL text into ShipmentSpec."""
    start = time.perf_counter()
    tokens: list[str] = []

    def _find(pattern: str, default: str) -> str:
        match = re.search(pattern, raw_text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            val = match.group(1).strip()
            tokens.append(f"{pattern.split(':')[0].strip()}=>{val}")
            return val
        return default

    bol_number = _find(r"BILL OF LADING:\s*([A-Z0-9\-]+)", "BOL-INNSA-2026-CUSTOM")
    shipper = _find(r"SHIPPER:\s*([^\n]+)", "India Gulf Exporter Pvt Ltd")
    consignee = _find(r"CONSIGNEE:\s*([^\n]+)", "European Distribution Hub GmbH")
    cargo = _find(r"CARGO:\s*([^\n]+)", "High-Value Bonded Freight")
    hs_code = _find(r"HS CODE:\s*([0-9\.]+)", "3002.15.00")
    teu_str = _find(r"QUANTITY:\s*(\d+)", "4")
    val_str = _find(r"VALUE:\s*USD\s*([\d,\.]+)", "1200000")
    cepa_str = _find(r"CEPA ORIGIN VALUE-ADD:\s*([\d\.]+)", "45.0")
    init_temp_str = _find(r"INITIAL TEMP:\s*([\d\.]+)", "4.0")
    max_temp_str = _find(r"MAX TEMP:\s*([\d\.]+)", "8.0")
    sla_str = _find(r"MAX TRANSIT SLA:\s*([\d\.]+)", "168")
    demurrage_str = _find(r"DEMURRAGE RATE:\s*USD\s*([\d\.]+)", "250")

    is_pharma = any(
        kw in raw_text.lower()
        for kw in ("vaccine", "biologic", "pharma", "cold", "reefer", "insulin", "2c", "8c")
    )
    max_temp = float(max_temp_str)
    if is_pharma and max_temp > 12.0:
        max_temp = 8.0

    shipment = ShipmentSpec(
        bol_number=bol_number,
        shipper=shipper,
        consignee=consignee,
        cargo_description=cargo,
        hs_code=hs_code[:12],
        origin_node="INNSA",
        destination_node="EUFRA",
        teu_count=max(1, min(500, int(teu_str))),
        cargo_value_usd=max(10_000.0, float(val_str.replace(",", ""))),
        cepa_value_add_pct=max(0.0, min(100.0, float(cepa_str))),
        is_temp_sensitive=is_pharma or max_temp <= 15.0,
        initial_temp_c=float(init_temp_str),
        max_temp_c=max_temp,
        max_transit_hours=max(12.0, float(sla_str)),
        demurrage_usd_per_teu_day=float(demurrage_str),
        spoilage_risk_pct_on_breach=100.0 if (is_pharma or max_temp <= 15.0) else 5.0,
        value_of_time_usd_per_hour=420.0 if is_pharma else 160.0,
    )

    elapsed_ms = round((time.perf_counter() - start) * 1000.0, 3)
    confidence = min(0.99, 0.72 + 0.025 * len(tokens))
    return ParseBoLResponse(
        shipment=shipment,
        extraction_confidence=round(confidence, 3),
        extraction_ms=elapsed_ms,
        extracted_tokens=tokens,
    )


@dataclass
class ExtractionCandidate:
    """Candidate token values extracted for a single compliance field across source documents."""

    field_path: str
    values: list[str] = field(default_factory=list)


class ZeroHallucinationParser:
    """Deterministic parser state machine: never injects synthetic defaults for compliance fields."""

    _PATTERNS: dict[str, re.Pattern[str]] = {
        "hs_code": re.compile(r"(?im)\bHS(?:\s*CODE)?\s*[:#-]?\s*(\d{6,12})\b"),
        "coo_number": re.compile(
            r"(?im)\b(?:COO|CERTIFICATE\s+OF\s+ORIGIN)\s*(?:NO\.?|#)?\s*[:#-]?\s*([A-Z0-9/-]{5,32})\b"
        ),
        "cepa_pct": re.compile(
            r"(?im)\bCEPA\s*(?:VALUE[- ]ADD(?:ED)?)?\s*[:#-]?\s*(\d{1,3}(?:\.\d{1,2})?)\s*%"
        ),
        "uae_trn": re.compile(r"(?im)\bTRN\s*[:#-]?\s*(100\d{12})\b"),
        "eori": re.compile(r"(?im)\bEORI\s*[:#-]?\s*([A-Z]{2}[A-Z0-9]{8,15})\b"),
        "un_hazmat": re.compile(r"(?im)\b(UN\d{4})\s*(?:CLASS|DIV)?\s*([1-9](?:\.[1-6])?)?\b"),
        "temp_range": re.compile(
            r"(?im)\bTEMP(?:ERATURE)?\s*[:#-]?\s*(-?\d+(?:\.\d+)?)\s*(?:TO|\.\.|-)\s*(-?\d+(?:\.\d+)?)\s*C?\b"
        ),
    }

    def extract_candidates(self, document_texts: dict[str, str]) -> dict[str, ExtractionCandidate]:
        """Extract unique candidate tokens per compliance field across uploaded document texts."""
        candidates: dict[str, ExtractionCandidate] = {
            k: ExtractionCandidate(field_path=k) for k in self._PATTERNS
        }
        for text in document_texts.values():
            for key, pattern in self._PATTERNS.items():
                for match in pattern.finditer(text):
                    val = " ".join(g for g in match.groups() if g is not None).strip()
                    if val and val not in candidates[key].values:
                        candidates[key].values.append(val)
        return candidates

    @staticmethod
    def _collect_corridor_issues(shipment: ShipmentRequest) -> list[MissingComplianceField]:
        """Enforce the 6 corridor-aware compliance gates without mutating or defaulting fields."""
        issues: list[MissingComplianceField] = []
        touches_gcc_customs = any(
            leg.origin_locode.startswith(("AE", "OM"))
            or leg.destination_locode.startswith(("AE", "OM"))
            for leg in shipment.legs
        )
        touches_eu_ics2 = any(
            leg.destination_locode.startswith(("EU", "DE")) for leg in shipment.legs
        )
        touches_dubai = any(
            loc in {"AEJEA", "AEDXB", "AEDWC", "AEPRH"}
            for leg in shipment.legs
            for loc in (leg.origin_locode, leg.destination_locode)
        )

        mofaic_threshold_triggered = False
        for idx, item in enumerate(shipment.consignment_items):
            if not item.hs_code_wco6 and not item.hs_code_gcc12:
                issues.append(
                    MissingComplianceField(
                        field_path=f"consignment_items[{idx}].hs_code_wco6",
                        reason_code="MISSING_MANDATORY_FIELD",
                        message="No HS code present; synthetic default injection is prohibited.",
                        candidate_values=[],
                        regulatory_reference="WCO HS / Zero Regulatory Hallucination Invariant",
                    )
                )
            if touches_gcc_customs and not item.hs_code_gcc12:
                issues.append(
                    MissingComplianceField(
                        field_path=f"consignment_items[{idx}].hs_code_gcc12",
                        reason_code="MISSING_MANDATORY_FIELD",
                        message="12-digit GCC/UAE/Oman HS code is required in 2026; legacy 6/8-digit codes are rejected.",
                        candidate_values=[item.hs_code_wco6] if item.hs_code_wco6 else [],
                        regulatory_reference="UAE FCA / Mirsal 2 / Oman Bayan 12-Digit Tariff (2026)",
                    )
                )
            if touches_gcc_customs and not item.origin.certificate_of_origin_no:
                issues.append(
                    MissingComplianceField(
                        field_path=f"consignment_items[{idx}].origin.certificate_of_origin_no",
                        reason_code="MISSING_MANDATORY_FIELD",
                        message="Certificate of Origin number is mandatory for GCC customs declarations.",
                        candidate_values=[],
                        regulatory_reference="Mirsal 2 / Oman Bayan Required Documents",
                    )
                )
            if (
                item.is_dangerous_goods
                and item.hazmat_spec
                and not item.hazmat_spec.msds_document_ref
            ):
                issues.append(
                    MissingComplianceField(
                        field_path=f"consignment_items[{idx}].hazmat_spec.msds_document_ref",
                        reason_code="MISSING_MANDATORY_FIELD",
                        message="MSDS reference required prior to departure for dangerous goods.",
                        candidate_values=[],
                        regulatory_reference="Dubai Customs Pre-Approval Rules (Chemicals/Batteries)",
                    )
                )
            if item.customs_value_currency == "AED" and item.customs_value_amount >= Decimal(
                "10000"
            ):
                mofaic_threshold_triggered = True

        if touches_dubai and mofaic_threshold_triggered and not shipment.mofaic_attested_invoice:
            issues.append(
                MissingComplianceField(
                    field_path="mofaic_attested_invoice",
                    reason_code="MISSING_MANDATORY_FIELD",
                    message="MOFAIC invoice attestation required for UAE invoices >= AED 10,000.",
                    candidate_values=[],
                    regulatory_reference="UAE MOFAIC Commercial Invoice Attestation",
                )
            )

        for idx, party in enumerate(shipment.parties):
            if party.country_code == "AE" and not party.uae_trn:
                issues.append(
                    MissingComplianceField(
                        field_path=f"parties[{idx}].uae_trn",
                        reason_code="MISSING_MANDATORY_FIELD",
                        message="15-digit UAE TRN starting with 100 is required for UAE parties.",
                        candidate_values=[],
                        regulatory_reference="UAE FTA (Cabinet Decision No. 52/2017)",
                    )
                )
            if touches_eu_ics2 and party.role.value == "CNE" and not party.eori_number:
                issues.append(
                    MissingComplianceField(
                        field_path=f"parties[{idx}].eori_number",
                        reason_code="MISSING_MANDATORY_FIELD",
                        message="Consignee EORI number is mandatory for EU ICS2 advance cargo filing.",
                        candidate_values=[],
                        regulatory_reference="EU ICS2 Entry Summary Declaration",
                    )
                )
            if party.country_code in {"DE", "FR", "NL", "BE", "IT", "ES"} and not party.eori_number:
                issues.append(
                    MissingComplianceField(
                        field_path=f"parties[{idx}].eori_number",
                        reason_code="MISSING_MANDATORY_FIELD",
                        message="EU-established shipper/consignee EORI number is missing.",
                        candidate_values=[],
                        regulatory_reference="EU ICS2 Economic Operator Registration",
                    )
                )
        return issues

    def evaluate(
        self,
        raw_payload: dict[str, Any],
        document_texts: dict[str, str] | None = None,
    ) -> ShipmentRequest | ValidationHold:
        """Validate structured shipment payload and cross-document consistency without guessing."""
        issues: list[MissingComplianceField] = []
        req_id = str(
            raw_payload.get("internal_request_id")
            or raw_payload.get("internalRequestId")
            or "UNKNOWN"
        )

        if document_texts:
            extracted = self.extract_candidates(document_texts)
            for key, cand in extracted.items():
                if len(cand.values) > 1:
                    issues.append(
                        MissingComplianceField(
                            field_path=key,
                            reason_code="CONFLICTING_DOCUMENT_VALUES",
                            message=f"Conflicting {key} values detected across source documents.",
                            candidate_values=cand.values,
                            regulatory_reference="Mirsal 2 / Bayan Cross-Document Integrity",
                        )
                    )

        shipment: ShipmentRequest | None = None
        try:
            shipment = ShipmentRequest.model_validate(raw_payload)
        except ValidationError as exc:
            for err in exc.errors():
                loc = ".".join(str(x) for x in err["loc"])
                issues.append(
                    MissingComplianceField(
                        field_path=loc,
                        reason_code=(
                            "UNVERIFIED_FORMAT"
                            if "value_error" in err["type"]
                            else "MISSING_MANDATORY_FIELD"
                        ),
                        message=err["msg"],
                        candidate_values=[],
                        regulatory_reference="Canonical Schema / ISO 6346 / DCSA eBL 3.0",
                    )
                )

        if shipment is None:
            return ValidationHold(
                internal_request_id=req_id,
                held_at_utc=datetime.now(UTC),
                missing_compliance_fields=issues,
            )

        issues.extend(self._collect_corridor_issues(shipment))
        if issues:
            return ValidationHold(
                internal_request_id=shipment.internal_request_id,
                held_at_utc=datetime.now(UTC),
                missing_compliance_fields=issues,
            )
        return shipment
