import streamlit as st

def calculate_annual_net_cash_flow(rental_income: float, total_expenses: float) -> float:
    """
    Calculates the Annual Net Cash Flow.
    :param rental_income: Total annual rental income.
    :param total_expenses: Total annual expenses.
    :return: Annual Net Cash Flow.
    """
    return rental_income - total_expenses

def calculate_lvr(loan_balance: float, market_value: float) -> float:
    """
    Calculates the Loan to Value Ratio (LVR).
    :param loan_balance: Current loan balance.
    :param market_value: Current property market value.
    :return: LVR as a percentage (0-100).
    """
    if market_value == 0:
        return 0
    return (loan_balance / market_value) * 100

def calculate_refinance_equity(market_value: float, loan_balance: float) -> float:
    """
    Calculates available Refinance Equity.
    :param market_value: Current property market value.
    :param loan_balance: Current loan balance.
    :return: Usable refinance equity.
    """
    target_lvr_value = market_value * 0.80
    refinance_equity = target_lvr_value - loan_balance
    return max(refinance_equity, 0)

def main():
    st.title("Property Investment Analysis Dashboard")
    st.markdown("Enter your property and financial details to analyze key investment metrics.")

    st.header("Input Your Details")
    market_value = st.number_input("Property Market Value ($)", min_value=0.0, value=500000.0, step=10000.0)
    loan_balance = st.number_input("Current Loan Balance ($)", min_value=0.0, value=400000.0, step=5000.0)
    rental_income = st.number_input("Annual Rental Income ($)", min_value=0.0, value=30000.0, step=1000.0)
    total_expenses = st.number_input("Annual Total Expenses ($)", min_value=0.0, value=15000.0, step=500.0)

    st.header("Results")
    annual_net_cash_flow = calculate_annual_net_cash_flow(rental_income, total_expenses)
    lvr = calculate_lvr(loan_balance, market_value)
    refinance_equity = calculate_refinance_equity(market_value, loan_balance)

    st.subheader("Annual Net Cash Flow")
    st.write(f"${annual_net_cash_flow:,.2f}")

    st.subheader("Loan to Value Ratio (LVR)")
    if lvr > 80:
        st.markdown(f"<span style='color:red; font-weight:bold;'>RED ALERT: LVR is {lvr:.2f}% (Above 80%)</span>", unsafe_allow_html=True)
    else:
        st.write(f"LVR: {lvr:.2f}%")

    st.subheader("Available Refinance Equity (at 80% LVR)")
    st.write(f"${refinance_equity:,.2f}")

    st.markdown("---")
    st.caption("All calculations are for estimation purposes only. Please consult a qualified financial advisor for professional advice.")

if __name__ == "__main__":
    main()