"""
Example: dual-key property + sensitivity table (prints to stdout).
Run from repo root: python examples/run_property_demo.py
"""

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from property_analysis import (
    BankValuation,
    PropertyInput,
    RentalUnit,
    analyze_property,
    interest_sensitivity_table,
)


def main() -> None:
    p = PropertyInput(
        address="Example St, NSW",
        purchase_date=date(2020, 6, 1),
        purchase_price=800_000.0,
        loan_amount=640_000.0,
        interest_rate_annual=0.065,
        council_rate_annual=2_000.0,
        water_rate_annual=800.0,
        other_annual_property_expenses=9_200.0,
        current_market_value=950_000.0,
        refinance_valuations=[BankValuation(as_of=date(2024, 3, 1), value=880_000.0, note="refi")],
        units=[
            RentalUnit("Unit A", weekly_rent=450.0, annual_expense_share=500.0),
            RentalUnit("Unit B", weekly_rent=420.0, annual_expense_share=500.0),
        ],
    )

    a = analyze_property(p)
    print("=== Base scenario (interest-only) ===")
    print(f"Before denominator (bank→purchase): ${a.price_basis_before:,.0f}")
    print(f"After denominator (market→bank→purchase): ${a.price_basis_after:,.0f}")
    print(f"Annual gross rent:   ${a.annual_gross_rent:,.0f}")
    print(f"Annual interest:     ${a.annual_interest:,.0f}")
    print(f"Other expenses:      ${a.annual_non_interest_expenses:,.0f}")
    print(f"Net cash (pre-tax):  ${a.net_cash_before_tax:,.0f}")
    print(f"Gross yield before:  {a.gross_rental_yield_pct:.2f}%")
    print(f"Net yield before:    {a.net_rental_yield_pct:.2f}%")
    print()
    print("=== Cash-out ===")
    print(f"Cash-out amount:     ${a.cash_out_equity_release:,.0f}")
    print(f"Gross yield after:   {a.gross_yield_after_cash_out_pct:.2f}%")
    print(f"Net yield after:     {a.net_yield_after_cash_out_pct:.2f}%")
    print()
    print("=== Rate sensitivity (post cash-out loan, after denominator for net %) ===")
    for row in interest_sensitivity_table(
        p,
        principal=a.loan_after_cash_out,
        net_yield_denominator=a.price_basis_after,
    ):
        if row.rate_increase_pp <= 0.5 or row.rate_increase_pp % 1 == 0:
            print(
                f"+{row.rate_increase_pp:.1f} pp | rate {row.new_rate_annual * 100:.2f}% | "
                f"interest ${row.annual_interest:,.0f} | net ${row.net_cash_before_tax:,.0f} | "
                f"net yield {row.net_rental_yield_pct:.2f}%"
            )


if __name__ == "__main__":
    main()
