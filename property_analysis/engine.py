from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional, Tuple

from property_analysis.models import PropertyInput


WEEKS_PER_YEAR = 52
PROJECTION_DAYS = 365
# 银行套现/增值提取常见持有期门槛（约 6 个月）
MIN_HOLD_DAYS_FOR_CASHOUT = 183


def _analysis_anchor_date(p: PropertyInput) -> date:
    return p.analysis_as_of or date.today()


def hold_days(p: PropertyInput) -> int:
    if not p.purchase_date:
        return 0
    return max(0, (_analysis_anchor_date(p) - p.purchase_date).days)


def cash_out_eligible_by_hold(p: PropertyInput) -> bool:
    if not p.purchase_date:
        return True
    return hold_days(p) >= MIN_HOLD_DAYS_FOR_CASHOUT


def bank_valuation_at_or_before_purchase(p: PropertyInput) -> Optional[float]:
    """
    购买日或之前最近一笔银行估价（用于：买价 vs 银行价、套现基数 B）。
    若无 on/before purchase 的记录，则退回最早一笔正估价（常见于只在成交日录了一笔）。
    """
    if not p.refinance_valuations:
        return None
    positive = [v for v in p.refinance_valuations if v.value and v.value > 0]
    if not positive:
        return None
    if p.purchase_date:
        pd = p.purchase_date
        on_or_before = [v for v in positive if v.as_of <= pd]
        if on_or_before:
            best = max(on_or_before, key=lambda v: v.as_of)
            return best.value
    return min(positive, key=lambda v: v.as_of).value


def last_bank_valuation_value(p: PropertyInput) -> Optional[float]:
    if not p.refinance_valuations:
        return None
    latest = max(p.refinance_valuations, key=lambda v: v.as_of)
    return latest.value if latest.value > 0 else None


def effective_market_value(p: PropertyInput) -> float:
    """Explicit current market, else last bank valuation, else purchase price."""
    if p.current_market_value is not None and p.current_market_value > 0:
        return float(p.current_market_value)
    lb = last_bank_valuation_value(p)
    if lb is not None:
        return lb
    return p.purchase_price


def denominator_before_cashout(p: PropertyInput) -> float:
    """
    套现前毛/净回报率分母：
    - 若购买时（或之前最近）银行估价 < 购买价 → 分母用购买价（保守口径）。
    - 否则：最近一次银行 refi 估价，无则购买价。
    """
    B0 = bank_valuation_at_or_before_purchase(p)
    P = p.purchase_price
    if B0 is not None and B0 < P:
        return P
    lb = last_bank_valuation_value(p)
    if lb is not None:
        return lb
    return P


def denominator_after_cashout(p: PropertyInput) -> float:
    """套现后回报率分母：当前市价；未填则等同最后一次银行估价（再退回购买价）。"""
    return effective_market_value(p)


def _weekly_rent_base(p: PropertyInput) -> float:
    return sum(u.weekly_rent for u in p.units)


def _lease2_active(p: PropertyInput) -> bool:
    return p.use_lease_proration


def annual_gross_rent(p: PropertyInput) -> float:
    """
    If use_lease_proration: daily rent over 365 days from analysis_as_of; vacancy between L1 end and L2 start.
    Else: sum(units weekly) × 52.
    """
    r1 = _weekly_rent_base(p)
    if not _lease2_active(p):
        return r1 * WEEKS_PER_YEAR

    as_of = p.analysis_as_of or date.today()
    window_end = as_of + timedelta(days=PROJECTION_DAYS - 1)

    l1s = p.lease_1_start
    l1e = p.lease_1_end
    l2s = p.lease_2_start
    assert l1s is not None and l1e is not None and l2s is not None

    r2 = p.lease_2_weekly_rent
    l2e = p.lease_2_end if p.lease_2_end is not None else window_end
    if l2e < l2s:
        raise ValueError("新租约结束日不能早于开始日。")

    total = 0.0
    for off in range(PROJECTION_DAYS):
        d = as_of + timedelta(days=off)
        total += _daily_rent_on_date(d, r1, r2, l1s, l1e, l2s, l2e)
    return total


def _daily_rent_on_date(
    d: date,
    r1: float,
    r2: float,
    l1s: date,
    l1e: date,
    l2s: date,
    l2e: date,
) -> float:
    in_2 = l2s <= d <= l2e
    in_1 = l1s <= d <= l1e
    if in_2:
        return r2 / 7.0
    if in_1:
        return r1 / 7.0
    return 0.0


def _non_interest_expenses(p: PropertyInput) -> float:
    unit_exp = sum(u.annual_expense_share for u in p.units)
    return (
        p.council_rate_annual
        + p.water_rate_annual
        + p.other_annual_property_expenses
        + unit_exp
    )


@dataclass(frozen=True)
class PropertyAnalysis:
    price_basis_before: float
    price_basis_after: float
    annual_gross_rent: float
    annual_interest: float
    annual_non_interest_expenses: float
    net_cash_before_tax: float
    gross_rental_yield_pct: float
    net_rental_yield_pct: float
    cash_out_equity_release: float
    loan_after_cash_out: float
    annual_interest_after_cash_out: float
    net_cash_after_cash_out: float
    gross_yield_after_cash_out_pct: float
    net_yield_after_cash_out_pct: float
    cash_out_eligible: bool
    hold_days: int
    # 无「购买时银行估价」记录时为 0.0（仅展示）；套现/分母仍用内部 None 语义，不把 0 当真估价。
    purchase_bank_valuation: float
    cash_out_cost_basis: float


def compute_cash_out_equity(
    p: PropertyInput, market_value: float
) -> Tuple[float, float, bool]:
    """
    可套现 ≈ max(0, 市价 - 基数) × 0.8；持有未满约 6 个月则 0。
    - 若购买时银行估价 B < 买价 P：基数 = B（套现 = (市价 - B)×0.8）。
    - 否则：基数 = P（套现 = (市价 - P)×0.8）。
    返回 (amount, cost_basis, eligible)。
    """
    if not cash_out_eligible_by_hold(p):
        B = bank_valuation_at_or_before_purchase(p)
        P = p.purchase_price
        basis = B if (B is not None and B < P) else P
        return 0.0, basis, False
    B = bank_valuation_at_or_before_purchase(p)
    P = p.purchase_price
    if B is not None and B < P:
        basis = B
        gain = market_value - B
    else:
        basis = P
        gain = market_value - P
    return max(0.0, gain) * 0.8, basis, True


def analyze_property(p: PropertyInput) -> PropertyAnalysis:
    p.validate()
    annual_rent = annual_gross_rent(p)
    non_interest_exp = _non_interest_expenses(p)
    d_before = denominator_before_cashout(p)
    d_after = denominator_after_cashout(p)
    mkt = effective_market_value(p)
    B0 = bank_valuation_at_or_before_purchase(p)
    eligible = cash_out_eligible_by_hold(p)
    hdays = hold_days(p)

    interest = p.loan_amount * p.interest_rate_annual
    net = annual_rent - interest - non_interest_exp

    gross_before = (annual_rent / d_before * 100) if d_before else 0.0
    net_before = (net / d_before * 100) if d_before else 0.0

    cash_out, cost_basis, _ = compute_cash_out_equity(p, mkt)
    loan_after = p.loan_amount + cash_out
    int_after = loan_after * p.interest_rate_annual
    net_after = annual_rent - int_after - non_interest_exp

    gross_after = (annual_rent / d_after * 100) if d_after else 0.0
    net_after_yield = (net_after / d_after * 100) if d_after else 0.0

    return PropertyAnalysis(
        price_basis_before=d_before,
        price_basis_after=d_after,
        annual_gross_rent=annual_rent,
        annual_interest=interest,
        annual_non_interest_expenses=non_interest_exp,
        net_cash_before_tax=net,
        gross_rental_yield_pct=gross_before,
        net_rental_yield_pct=net_before,
        cash_out_equity_release=cash_out,
        loan_after_cash_out=loan_after,
        annual_interest_after_cash_out=int_after,
        net_cash_after_cash_out=net_after,
        gross_yield_after_cash_out_pct=gross_after,
        net_yield_after_cash_out_pct=net_after_yield,
        cash_out_eligible=eligible,
        hold_days=hdays,
        purchase_bank_valuation=float(B0) if B0 is not None else 0.0,
        cash_out_cost_basis=cost_basis,
    )


@dataclass(frozen=True)
class InterestSensitivityRow:
    rate_increase_pp: float
    new_rate_annual: float
    annual_interest: float
    net_cash_before_tax: float
    net_rental_yield_pct: float


def interest_sensitivity_table(
    p: PropertyInput,
    *,
    principal: Optional[float] = None,
    max_increase_pp: float = 5.0,
    step_pp: float = 0.1,
    net_yield_denominator: Optional[float] = None,
) -> List[InterestSensitivityRow]:
    p.validate()
    loan = p.loan_amount if principal is None else principal
    if loan < 0:
        raise ValueError("principal cannot be negative")
    if max_increase_pp <= 0 or step_pp <= 0:
        raise ValueError("max_increase_pp and step_pp must be positive")

    annual_rent = annual_gross_rent(p)
    non_interest_exp = _non_interest_expenses(p)
    v = net_yield_denominator if net_yield_denominator is not None else denominator_after_cashout(p)
    base = p.interest_rate_annual
    rows: List[InterestSensitivityRow] = []
    n = int(round(max_increase_pp / step_pp))
    for i in range(1, n + 1):
        inc = round(i * step_pp / 100.0, 6)
        new_r = base + inc
        int_annual = loan * new_r
        net = annual_rent - int_annual - non_interest_exp
        ny = (net / v * 100) if v else 0.0
        rows.append(
            InterestSensitivityRow(
                rate_increase_pp=round(i * step_pp, 6),
                new_rate_annual=new_r,
                annual_interest=int_annual,
                net_cash_before_tax=net,
                net_rental_yield_pct=ny,
            )
        )
    return rows
