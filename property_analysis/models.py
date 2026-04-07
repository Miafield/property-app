from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import List, Optional


class PropertyKind(str, Enum):
    APARTMENT = "apartment"
    HOUSE = "house"
    DUAL_KEY = "dual_key"
    TOWNHOUSE = "townhouse"
    DUPLEX = "duplex"


class PropertyUse(str, Enum):
    """投资出租 vs 自住（自住仍可做贷款/估值记录，组合页单独汇总）。"""

    INVESTMENT = "investment"
    OWNER_OCCUPIED = "owner_occupied"


@dataclass
class RentalUnit:
    """One rentable part (e.g. dual-key half). Weekly rent; unit-level annual expenses."""

    label: str = ""
    weekly_rent: float = 0.0
    annual_expense_share: float = 0.0


@dataclass
class BankValuation:
    """Lender / refinance valuation (most recent by date used as 'last bank valuation')."""

    as_of: date
    value: float
    note: str = ""


@dataclass
class PropertyInput:
    """街道地址 + 州 + 邮编；兼容旧数据单字段 address。"""

    address_line: str = ""
    state: str = ""
    postcode: str = ""
    property_use: PropertyUse = PropertyUse.INVESTMENT
    """Legacy single field; if set and address_line empty, treated as street line."""
    address: str = ""
    property_kind: PropertyKind = PropertyKind.HOUSE
    purchase_date: Optional[date] = None
    purchase_price: float = 0.0
    loan_amount: float = 0.0
    """Annual interest rate as decimal, e.g. 0.065 for 6.5% p.a. (interest-only)."""
    interest_rate_annual: float = 0.0

    """Whole-property rates (not split across units)."""
    council_rate_annual: float = 0.0
    water_rate_annual: float = 0.0
    """Insurance, strata, repairs, etc. (excludes council, water, interest)."""
    other_annual_property_expenses: float = 0.0

    """None = not provided → for cash-out / 'after' yield, fall back to last bank valuation then purchase."""
    current_market_value: Optional[float] = None

    refinance_valuations: List[BankValuation] = field(default_factory=list)
    units: List[RentalUnit] = field(default_factory=list)

    analysis_as_of: Optional[date] = None

    """When True: use L1/L2 dates with vacancy between L1 end and L2 start; need L2 start + positive L2 weekly."""
    use_lease_proration: bool = False
    lease_1_start: Optional[date] = None
    lease_1_end: Optional[date] = None
    lease_2_start: Optional[date] = None
    lease_2_end: Optional[date] = None
    lease_2_weekly_rent: float = 0.0

    def display_street(self) -> str:
        line = (self.address_line or "").strip()
        if line:
            return line
        return (self.address or "").strip()

    def full_address_label(self) -> str:
        parts = [self.display_street(), (self.state or "").strip(), (self.postcode or "").strip()]
        return ", ".join(p for p in parts if p)

    def validate(self) -> None:
        if self.purchase_price < 0 or self.loan_amount < 0:
            raise ValueError("purchase_price and loan_amount must be non-negative")
        if self.interest_rate_annual < 0:
            raise ValueError("interest_rate_annual cannot be negative")
        if not self.units:
            raise ValueError("至少需要一个出租单元 / At least one RentalUnit is required")
        if self.use_lease_proration:
            if self.lease_1_start is None or self.lease_1_end is None:
                raise ValueError("启用租约折算时，请填写当前租约开始日与结束日。")
            if self.lease_2_start is None:
                raise ValueError("请填写新租约开始日（旧租约结束与新租约开始之间的日期为断档、无租金）。")
            if (self.lease_2_weekly_rent or 0) <= 0:
                raise ValueError("启用租约折算时，请填写新租约周租（> 0）。")

    def _lease2_active(self) -> bool:
        return self.use_lease_proration
