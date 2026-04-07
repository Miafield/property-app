from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from property_analysis.models import BankValuation, PropertyInput, PropertyKind, PropertyUse, RentalUnit


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def portfolio_path() -> Path:
    d = _repo_root() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d / "saved_properties.json"


def _date_iso(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    return date.fromisoformat(s)


def _safe_float(x: Any, default: float = 0.0) -> float:
    if x is None or x == "":
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def property_to_record(p: PropertyInput) -> Dict[str, Any]:
    return {
        "address_line": p.address_line,
        "state": p.state,
        "postcode": p.postcode,
        "property_use": p.property_use.value,
        "address": p.full_address_label() or p.display_street(),
        "property_kind": p.property_kind.value,
        "purchase_date": _date_iso(p.purchase_date),
        "purchase_price": p.purchase_price,
        "loan_amount": p.loan_amount,
        "interest_rate_annual": p.interest_rate_annual,
        "council_rate_annual": p.council_rate_annual,
        "water_rate_annual": p.water_rate_annual,
        "other_annual_property_expenses": p.other_annual_property_expenses,
        "current_market_value": p.current_market_value,
        "refinance_valuations": [
            {"as_of": _date_iso(v.as_of), "value": v.value, "note": v.note}
            for v in p.refinance_valuations
        ],
        "units": [
            {"label": u.label, "weekly_rent": u.weekly_rent, "annual_expense_share": u.annual_expense_share}
            for u in p.units
        ],
        "analysis_as_of": _date_iso(p.analysis_as_of),
        "use_lease_proration": p.use_lease_proration,
        "lease_1_start": _date_iso(p.lease_1_start),
        "lease_1_end": _date_iso(p.lease_1_end),
        "lease_2_start": _date_iso(p.lease_2_start),
        "lease_2_end": _date_iso(p.lease_2_end),
        "lease_2_weekly_rent": p.lease_2_weekly_rent,
    }


def record_to_property(data: Dict[str, Any]) -> PropertyInput:
    vals: List[BankValuation] = []
    for row in data.get("refinance_valuations") or []:
        if not isinstance(row, dict):
            continue
        vals.append(
            BankValuation(
                as_of=_parse_date(row.get("as_of")) or date.today(),
                value=_safe_float(row.get("value"), 0.0),
                note=str(row.get("note") or ""),
            )
        )
    units: List[RentalUnit] = []
    for row in data.get("units") or []:
        units.append(
            RentalUnit(
                label=str(row.get("label") or ""),
                weekly_rent=float(row.get("weekly_rent") or 0),
                annual_expense_share=float(row.get("annual_expense_share") or 0),
            )
        )
    cm = data.get("current_market_value")
    current_market: Optional[float]
    if cm is None:
        current_market = None
    else:
        current_market = float(cm) if float(cm) > 0 else None

    legacy_other = float(data.get("other_annual_property_expenses") or 0)
    if legacy_other == 0 and data.get("annual_property_expenses"):
        legacy_other = float(data["annual_property_expenses"])

    addr_line = str(data.get("address_line") or "").strip()
    legacy_addr = str(data.get("address") or "").strip()
    if not addr_line and legacy_addr:
        addr_line = legacy_addr

    use_raw = data.get("property_use") or "investment"
    try:
        prop_use = PropertyUse(str(use_raw))
    except ValueError:
        prop_use = PropertyUse.INVESTMENT

    return PropertyInput(
        address_line=addr_line,
        state=str(data.get("state") or ""),
        postcode=str(data.get("postcode") or ""),
        property_use=prop_use,
        address=legacy_addr,
        property_kind=PropertyKind(data.get("property_kind") or "house"),
        purchase_date=_parse_date(data.get("purchase_date")),
        purchase_price=float(data.get("purchase_price") or 0),
        loan_amount=float(data.get("loan_amount") or 0),
        interest_rate_annual=float(data.get("interest_rate_annual") or 0),
        council_rate_annual=float(data.get("council_rate_annual") or 0),
        water_rate_annual=float(data.get("water_rate_annual") or 0),
        other_annual_property_expenses=legacy_other,
        current_market_value=current_market,
        refinance_valuations=vals,
        units=units or [RentalUnit(label="Unit 1", weekly_rent=0.0, annual_expense_share=0.0)],
        analysis_as_of=_parse_date(data.get("analysis_as_of")),
        use_lease_proration=bool(data.get("use_lease_proration")),
        lease_1_start=_parse_date(data.get("lease_1_start")),
        lease_1_end=_parse_date(data.get("lease_1_end")),
        lease_2_start=_parse_date(data.get("lease_2_start")),
        lease_2_end=_parse_date(data.get("lease_2_end")),
        lease_2_weekly_rent=float(data.get("lease_2_weekly_rent") or 0),
    )


def load_saved_properties() -> List[Dict[str, Any]]:
    path = portfolio_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return raw
    except (json.JSONDecodeError, OSError):
        pass
    return []


def write_saved_properties(items: List[Dict[str, Any]]) -> None:
    path = portfolio_path()
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def upsert_saved_property(prop: PropertyInput, record_id: Optional[str] = None) -> str:
    items = load_saved_properties()
    payload = property_to_record(prop)
    if record_id:
        for i, it in enumerate(items):
            if it.get("id") == record_id:
                items[i] = {"id": record_id, **payload}
                write_saved_properties(items)
                return record_id
    new_id = str(uuid.uuid4())
    items.append({"id": new_id, **payload})
    write_saved_properties(items)
    return new_id


def delete_saved_property(record_id: str) -> None:
    items = [x for x in load_saved_properties() if x.get("id") != record_id]
    write_saved_properties(items)


def get_saved_by_id(record_id: str) -> Optional[Dict[str, Any]]:
    for it in load_saved_properties():
        if it.get("id") == record_id:
            return it
    return None
