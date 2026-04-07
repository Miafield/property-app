from __future__ import annotations

import csv
import io
import math
import os
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import altair as alt
import pandas as pd
import streamlit as st

from property_analysis import (
    BankValuation,
    PropertyAnalysis,
    PropertyInput,
    PropertyKind,
    PropertyUse,
    RentalUnit,
    analyze_property,
    bank_valuation_at_or_before_purchase,
    effective_market_value,
    interest_sensitivity_table,
    last_bank_valuation_value,
)
from property_analysis.portfolio import (
    delete_saved_property,
    get_saved_by_id,
    load_saved_properties,
    record_to_property,
    upsert_saved_property,
)


def _num0(x: Any) -> float:
    """None / NaN / 空字符串 / 非数字 → 0.0（购买时银行估价等列统一用）。"""
    if x is None:
        return 0.0
    if isinstance(x, str) and not x.strip():
        return 0.0
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(v) or math.isinf(v):
        return 0.0
    return v


def _currency(n: float, *, decimals: int = 0) -> str:
    x = _num0(n)
    if decimals:
        return f"${x:,.{decimals}f}"
    return f"${x:,.0f}"


_USE_LABEL = {"investment": "投资", "owner_occupied": "自住"}

_MONEY_COLS = {
    "购买价",
    "购买时银行估价",
    "最近银行估价",
    "有效市价",
    "套现基数",
    "年毛租",
    "年利息",
    "年非利息支出",
    "税前年现金流(套现前)",
    "税前年现金流(套现后)",
    "贷款本金",
    "可套现额",
}


_KIND_LABELS: dict[PropertyKind, str] = {
    PropertyKind.APARTMENT: "Apartment 公寓",
    PropertyKind.HOUSE: "House 独立屋",
    PropertyKind.DUAL_KEY: "Dual key 双钥匙",
    PropertyKind.TOWNHOUSE: "Townhouse 联排",
    PropertyKind.DUPLEX: "Duplex 双拼",
}


def _ensure_form_defaults() -> None:
    d0: Dict[str, Any] = {
        "fm_kind": PropertyKind.HOUSE,
        "fm_unit_count": 2,
        "fm_address_line": "",
        "fm_state": "QLD",
        "fm_postcode": "",
        "fm_property_use": "investment",
        "fm_n_bank": 0,
        "fm_market_on": True,
        "fm_market_val": 850_000.0,
        "fm_use_lease": False,
        "fm_saved_id": None,
        "fm_purchase_date": date(2020, 1, 1),
        "fm_purchase_price": 800_000.0,
        "fm_loan": 640_000.0,
        "fm_interest_pct": 6.5,
        "fm_council": 2_000.0,
        "fm_water": 800.0,
        "fm_other": 9_200.0,
        "fm_analysis_as_of": date.today(),
        "fm_l1s": date.today(),
        "fm_l1e": date.today() + timedelta(days=180),
        "fm_l2s": date.today() + timedelta(days=194),
        "fm_l2e": date.today() + timedelta(days=364),
        "fm_l2_weekly": 0.0,
        "fm_sens_max": 5.0,
        "fm_sens_step": 0.1,
    }
    for k, v in d0.items():
        if k not in st.session_state:
            st.session_state[k] = v
    for i in range(10):
        if f"fm_u_{i}_label" not in st.session_state:
            st.session_state[f"fm_u_{i}_label"] = f"Part {i + 1}"
        if f"fm_u_{i}_weekly" not in st.session_state:
            st.session_state[f"fm_u_{i}_weekly"] = 500.0 if i == 0 else 0.0
        if f"fm_u_{i}_exp" not in st.session_state:
            st.session_state[f"fm_u_{i}_exp"] = 0.0
    for i in range(10):
        if f"fm_bank_{i}_date" not in st.session_state:
            st.session_state[f"fm_bank_{i}_date"] = date.today()
        if f"fm_bank_{i}_val" not in st.session_state:
            st.session_state[f"fm_bank_{i}_val"] = 0.0


def _apply_property_to_session(p: PropertyInput, saved_id: Optional[str]) -> None:
    st.session_state.fm_saved_id = saved_id
    st.session_state.fm_address_line = p.display_street()
    st.session_state.fm_state = p.state or ""
    st.session_state.fm_postcode = p.postcode or ""
    st.session_state.fm_property_use = p.property_use.value
    st.session_state.fm_kind = p.property_kind
    st.session_state.fm_unit_count = max(2, len(p.units)) if p.property_kind == PropertyKind.DUAL_KEY else max(1, len(p.units))
    st.session_state.fm_purchase_date = p.purchase_date or date.today()
    st.session_state.fm_purchase_price = p.purchase_price
    st.session_state.fm_loan = p.loan_amount
    st.session_state.fm_interest_pct = p.interest_rate_annual * 100.0
    st.session_state.fm_council = p.council_rate_annual
    st.session_state.fm_water = p.water_rate_annual
    st.session_state.fm_other = p.other_annual_property_expenses
    if p.current_market_value is not None and p.current_market_value > 0:
        st.session_state.fm_market_on = True
        st.session_state.fm_market_val = float(p.current_market_value)
    else:
        st.session_state.fm_market_on = False
        st.session_state.fm_market_val = 0.0
    st.session_state.fm_n_bank = min(10, len(p.refinance_valuations))
    for i in range(10):
        if i < len(p.refinance_valuations):
            v = p.refinance_valuations[i]
            st.session_state[f"fm_bank_{i}_date"] = v.as_of
            st.session_state[f"fm_bank_{i}_val"] = v.value
        else:
            st.session_state[f"fm_bank_{i}_date"] = date.today()
            st.session_state[f"fm_bank_{i}_val"] = 0.0
    for i in range(10):
        if i < len(p.units):
            u = p.units[i]
            st.session_state[f"fm_u_{i}_label"] = u.label
            st.session_state[f"fm_u_{i}_weekly"] = u.weekly_rent
            st.session_state[f"fm_u_{i}_exp"] = u.annual_expense_share
    st.session_state.fm_use_lease = p.use_lease_proration
    st.session_state.fm_analysis_as_of = p.analysis_as_of or date.today()
    st.session_state.fm_l1s = p.lease_1_start or st.session_state.fm_l1s
    st.session_state.fm_l1e = p.lease_1_end or st.session_state.fm_l1e
    st.session_state.fm_l2s = p.lease_2_start or st.session_state.fm_l2s
    st.session_state.fm_l2e = p.lease_2_end or st.session_state.fm_l2e
    st.session_state.fm_l2_weekly = p.lease_2_weekly_rent


def _read_property_from_session() -> PropertyInput:
    kind: PropertyKind = st.session_state.fm_kind
    n_units = int(st.session_state.fm_unit_count) if kind == PropertyKind.DUAL_KEY else 1
    n_units = max(1, min(10, n_units))
    units: List[RentalUnit] = []
    for i in range(n_units):
        units.append(
            RentalUnit(
                label=str(st.session_state.get(f"fm_u_{i}_label", f"Part {i + 1}")),
                weekly_rent=float(st.session_state.get(f"fm_u_{i}_weekly", 0.0)),
                annual_expense_share=float(st.session_state.get(f"fm_u_{i}_exp", 0.0)),
            )
        )
    n_bank = int(st.session_state.get("fm_n_bank", 0))
    n_bank = max(0, min(10, n_bank))
    vals: List[BankValuation] = []
    for i in range(n_bank):
        d = st.session_state.get(f"fm_bank_{i}_date")
        v = float(st.session_state.get(f"fm_bank_{i}_val", 0.0))
        if isinstance(d, date) and v > 0:
            vals.append(BankValuation(as_of=d, value=v, note=""))

    market_on = bool(st.session_state.get("fm_market_on", False))
    market_val = float(st.session_state.get("fm_market_val", 0.0))
    current_market: Optional[float] = market_val if market_on and market_val > 0 else None

    use_lease = bool(st.session_state.get("fm_use_lease", False))
    l2w = float(st.session_state.get("fm_l2_weekly", 0.0))

    pu = str(st.session_state.get("fm_property_use", "investment"))
    try:
        use = PropertyUse(pu)
    except ValueError:
        use = PropertyUse.INVESTMENT

    return PropertyInput(
        address_line=str(st.session_state.get("fm_address_line", "")),
        state=str(st.session_state.get("fm_state", "")),
        postcode=str(st.session_state.get("fm_postcode", "")),
        property_use=use,
        address="",
        property_kind=kind,
        purchase_date=st.session_state.get("fm_purchase_date"),
        purchase_price=float(st.session_state.get("fm_purchase_price", 0.0)),
        loan_amount=float(st.session_state.get("fm_loan", 0.0)),
        interest_rate_annual=float(st.session_state.get("fm_interest_pct", 0.0)) / 100.0,
        council_rate_annual=float(st.session_state.get("fm_council", 0.0)),
        water_rate_annual=float(st.session_state.get("fm_water", 0.0)),
        other_annual_property_expenses=float(st.session_state.get("fm_other", 0.0)),
        current_market_value=current_market,
        refinance_valuations=vals,
        units=units,
        analysis_as_of=st.session_state.get("fm_analysis_as_of"),
        use_lease_proration=use_lease,
        lease_1_start=st.session_state.get("fm_l1s") if use_lease else None,
        lease_1_end=st.session_state.get("fm_l1e") if use_lease else None,
        lease_2_start=st.session_state.get("fm_l2s") if use_lease else None,
        lease_2_end=st.session_state.get("fm_l2e") if use_lease else None,
        lease_2_weekly_rent=l2w if use_lease else 0.0,
    )


def _portfolio_summary_rows() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for rec in load_saved_properties():
        rid = rec.get("id", "")
        try:
            p = record_to_property({k: v for k, v in rec.items() if k != "id"})
            a = analyze_property(p)
            mkt = effective_market_value(p)
            lb = last_bank_valuation_value(p)
            pb = bank_valuation_at_or_before_purchase(p)
            full = p.full_address_label() or p.display_street() or "(未命名)"
            rows.append(
                {
                    "id": rid,
                    "用途": _USE_LABEL.get(p.property_use.value, p.property_use.value),
                    "完整地址": full,
                    "街道": p.display_street(),
                    "州": p.state,
                    "邮编": p.postcode,
                    "种类": _KIND_LABELS.get(p.property_kind, p.property_kind.value),
                    "购买日": p.purchase_date.isoformat() if p.purchase_date else "",
                    "持有天数": a.hold_days,
                    "满6月可套现": "是" if a.cash_out_eligible else "否",
                    "购买价": _num0(p.purchase_price),
                    "购买时银行估价": _num0(pb),
                    "最近银行估价": _num0(lb),
                    "有效市价": _num0(mkt),
                    "套现基数": _num0(a.cash_out_cost_basis),
                    "套现前毛%": round(a.gross_rental_yield_pct, 2),
                    "套现前净%": round(a.net_rental_yield_pct, 2),
                    "套现后毛%": round(a.gross_yield_after_cash_out_pct, 2),
                    "套现后净%": round(a.net_yield_after_cash_out_pct, 2),
                    "年毛租": round(a.annual_gross_rent, 2),
                    "年利息": round(a.annual_interest, 2),
                    "年非利息支出": round(a.annual_non_interest_expenses, 2),
                    "税前年现金流(套现前)": round(a.net_cash_before_tax, 2),
                    "税前年现金流(套现后)": round(a.net_cash_after_cash_out, 2),
                    "贷款本金": p.loan_amount,
                    "可套现额": round(a.cash_out_equity_release, 2),
                }
            )
        except Exception:
            rows.append(
                {
                    "id": rid,
                    "用途": "?",
                    "完整地址": rec.get("address", "?"),
                    "街道": "",
                    "州": "",
                    "邮编": "",
                    "种类": "-",
                    "购买日": "",
                    "持有天数": 0,
                    "满6月可套现": "",
                    "购买价": 0.0,
                    "购买时银行估价": 0.0,
                    "最近银行估价": 0.0,
                    "有效市价": 0.0,
                    "套现基数": 0.0,
                    "套现前毛%": 0.0,
                    "套现前净%": 0.0,
                    "套现后毛%": 0.0,
                    "套现后净%": 0.0,
                    "年毛租": 0.0,
                    "年利息": 0.0,
                    "年非利息支出": 0.0,
                    "税前年现金流(套现前)": 0.0,
                    "税前年现金流(套现后)": 0.0,
                    "贷款本金": 0.0,
                    "可套现额": 0.0,
                }
            )
    return rows


def _records_fillna_zero(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """组合/表格加载：NaN/None → 0，避免 Streamlit/Altair 数值转换报错。"""
    if not records:
        return records
    df = pd.DataFrame(records)
    for _col in ("购买时银行估价", "最近银行估价", "有效市价", "套现基数", "购买价"):
        if _col in df.columns:
            df[_col] = pd.to_numeric(df[_col], errors="coerce").fillna(0)
    df = df.fillna(0)
    out: List[Dict[str, Any]] = df.to_dict(orient="records")
    _text_cols = (
        "用途",
        "完整地址",
        "街道",
        "州",
        "邮编",
        "种类",
        "购买日",
        "满6月可套现",
    )
    for r in out:
        for k in _text_cols:
            if k not in r:
                continue
            v = r[k]
            if v == 0 or v == 0.0:
                r[k] = ""
    return out


def _display_portfolio_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows:
        d = {k: v for k, v in r.items() if k != "id"}
        for k in _MONEY_COLS:
            if k in d:
                dec = 2 if k == "年毛租" else 0
                d[k] = _currency(_num0(d[k]), decimals=dec)
        out.append(d)
    return out


def _try_finish_google_oauth() -> None:
    try:
        code = st.query_params.get("code")
        state = st.query_params.get("state")
        if not code or not state:
            return
        if isinstance(code, (list, tuple)):
            code = code[0]
        if isinstance(state, (list, tuple)):
            state = state[0]
        if str(state) != str(st.session_state.get("_oauth_state", "")):
            return
        from property_analysis.google_connect import (
            exchange_code,
            load_client_config,
            redirect_uri_default,
            save_token,
        )

        cfg = load_client_config()
        if not cfg:
            return
        creds = exchange_code(cfg, redirect_uri_default(), str(code))
        save_token(creds)
        for k in ("_oauth_state", "_oauth_url"):
            st.session_state.pop(k, None)
        st.session_state["_google_just_connected"] = True
        try:
            st.query_params.clear()
        except Exception:
            try:
                for k in list(dict(st.query_params).keys()):
                    del st.query_params[k]
            except Exception:
                pass
        st.rerun()
    except Exception as ex:
        st.session_state["_oauth_error"] = str(ex)


def _portfolio_cash_metrics(title: str, sub: List[Dict[str, Any]]) -> None:
    if not sub:
        st.caption(f"{title}：暂无记录")
        return
    c1, c2 = st.columns(2)
    with c1:
        st.metric(
            f"{title} · 税前年现金流（套现前）",
            _currency(_sum_col(sub, "税前年现金流(套现前)")),
        )
    with c2:
        st.metric(
            f"{title} · 税前年现金流（套现后）",
            _currency(_sum_col(sub, "税前年现金流(套现后)")),
        )


def main() -> None:
    st.set_page_config(
        page_title="Property yield & portfolio",
        page_icon="🏠",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _ensure_form_defaults()
    _try_finish_google_oauth()
    if st.session_state.pop("_google_just_connected", False):
        st.toast("Google 已连接，可同步表格或导出 KML。")
    if "_oauth_error" in st.session_state:
        st.error(f"Google 授权失败：{st.session_state.pop('_oauth_error')}")

    if st.session_state.get("_load_id"):
        lid = st.session_state.pop("_load_id")
        rec = get_saved_by_id(lid)
        if rec:
            p = record_to_property({k: v for k, v in rec.items() if k != "id"})
            _apply_property_to_session(p, lid)
            st.toast("已加载物业 / Property loaded")

    st.title("房产租金回报与物业库")
    st.caption(
        "套现前分母：若购买时银行估价 < 买价则用买价；否则用最近银行估价（无则买价）。"
        "可套现 = max(0, 市价 − 基数)×0.8；基数：若购买时银行估价 < 买价则为该银行价，否则为买价；"
        "且须持有满约 6 个月（183 天）才计套现额。套现后回报率分母 = 当前市价（未填则最近银行估价→买价）。"
        "Council / Water 为整栋费用。非投资建议。"
    )

    tab_analysis, tab_portfolio = st.tabs(["当前物业分析", "我的物业 Portfolio"])

    with tab_analysis:
        _render_analysis_tab()

    with tab_portfolio:
        _render_portfolio_tab()


def _render_analysis_tab() -> None:
    with st.sidebar:
        st.header("输入 / Inputs")
        st.text_input("街道地址 Street address", key="fm_address_line", placeholder="不含州/邮编")
        c_ad1, c_ad2 = st.columns(2)
        with c_ad1:
            st.text_input("州 State", key="fm_state", placeholder="如 QLD、NSW")
        with c_ad2:
            st.text_input("邮编 Postcode", key="fm_postcode", placeholder="如 4506")
        st.radio(
            "用途 Property use",
            options=["investment", "owner_occupied"],
            format_func=lambda x: "投资出租" if x == "investment" else "自住",
            key="fm_property_use",
            horizontal=True,
        )
        st.selectbox(
            "房产种类 Property type",
            options=list(PropertyKind),
            format_func=lambda k: _KIND_LABELS[k],
            key="fm_kind",
        )

        st.date_input("购买日 Purchase date", key="fm_purchase_date")
        st.number_input("购买价 Purchase price ($)", min_value=0.0, step=5_000.0, key="fm_purchase_price")
        st.checkbox(
            "填写当前市价（用于套现后与现金套现计算；不填则沿用最近银行估价）",
            key="fm_market_on",
        )
        st.number_input(
            "当前市价 Current market value ($)",
            min_value=0.0,
            step=5_000.0,
            key="fm_market_val",
            disabled=not st.session_state.fm_market_on,
        )

        st.subheader("银行 refi 估价 Bank valuations")
        st.caption("可添加多笔；「最近一次」按日期最新的一笔用于套现前分母与市价回退。")
        st.number_input("估价条数（0–10）", min_value=0, max_value=10, step=1, key="fm_n_bank")
        n_bank = int(st.session_state.fm_n_bank)
        for i in range(n_bank):
            c1, c2 = st.columns(2)
            with c1:
                st.date_input(f"估价 {i + 1} 日期", key=f"fm_bank_{i}_date")
            with c2:
                st.number_input(f"估价 {i + 1} 金额 ($)", min_value=0.0, step=10_000.0, key=f"fm_bank_{i}_val")

        st.number_input("贷款本金 Loan ($)", min_value=0.0, step=5_000.0, key="fm_loan")
        st.number_input(
            "年利率 Annual rate (%) interest-only",
            min_value=0.0,
            max_value=25.0,
            step=0.05,
            format="%.2f",
            key="fm_interest_pct",
        )

        st.subheader("整栋费用（不分摊）Property-wide costs")
        st.number_input("Council rate /年 ($)", min_value=0.0, step=100.0, key="fm_council")
        st.number_input("Water rate /年 ($)", min_value=0.0, step=50.0, key="fm_water")
        st.number_input("其他年支出 Other annual ($) insurance/strata/repairs…", min_value=0.0, step=500.0, key="fm_other")

        st.subheader("利率敏感度参数")
        st.number_input("最大加息 (pp)", min_value=0.1, value=5.0, step=0.1, key="fm_sens_max")
        st.number_input("步长 (pp)", min_value=0.05, value=0.1, step=0.05, key="fm_sens_step")

        st.subheader("租约与断档 Vacancy between leases")
        st.checkbox(
            "启用租约折算（旧约结束与新约开始之间无租金）",
            key="fm_use_lease",
        )
        st.date_input("租金分析起点 365 日窗口", key="fm_analysis_as_of")
        if st.session_state.fm_use_lease:
            st.date_input("当前租约开始 L1 start", key="fm_l1s")
            st.date_input("当前租约结束 L1 end", key="fm_l1e")
            st.date_input("新租约开始 L2 start（可与 L1 结束之间留空档）", key="fm_l2s")
            st.date_input("新租约结束 L2 end", key="fm_l2e")
            st.number_input("新租约周租（整套房合计）($)", min_value=0.0, step=10.0, key="fm_l2_weekly")
            st.info(
                "断档期说明：日历日在「旧租约结束日之后」且「新租约开始日之前」的日期不计租金。"
            )

    kind: PropertyKind = st.session_state.fm_kind
    st.subheader("出租单元 Rental units")
    if kind == PropertyKind.DUAL_KEY:
        st.caption("双钥匙：用 − / + 调整单元数量；各单元自有周租与年支出。Council / Water 已在侧栏按整栋计入。")
        a, b, c = st.columns([1, 3, 1])
        with a:
            if st.button("− 减少单元", key="fm_dual_minus"):
                st.session_state.fm_unit_count = max(2, int(st.session_state.fm_unit_count) - 1)
                st.rerun()
        with b:
            st.write(f"**{int(st.session_state.fm_unit_count)}** 个单元")
        with c:
            if st.button("+ 增加单元", key="fm_dual_plus"):
                st.session_state.fm_unit_count = min(10, int(st.session_state.fm_unit_count) + 1)
                st.rerun()
        n_units = int(st.session_state.fm_unit_count)
    else:
        st.caption("非双钥匙：单套出租单元。")
        n_units = 1

    n_units = max(1, min(10, n_units))
    for i in range(n_units):
        with st.expander(f"单元 {i + 1} / Unit {i + 1}", expanded=(n_units <= 2)):
            c1, c2, c3 = st.columns([2, 2, 2])
            with c1:
                st.text_input("标签 Label", key=f"fm_u_{i}_label")
            with c2:
                st.number_input("周租 Weekly rent ($)", min_value=0.0, step=10.0, key=f"fm_u_{i}_weekly")
            with c3:
                st.number_input("该单元年支出 Annual unit expenses ($)", min_value=0.0, step=100.0, key=f"fm_u_{i}_exp")

    prop = _read_property_from_session()

    st.divider()
    if st.button("新建物业（清空关联）New property", key="fm_btn_clear_link"):
        st.session_state.fm_saved_id = None
        st.toast("已解除与已保存记录的关联；写入文件须用下方 Accept。")

    st.caption("**不会自动写入** `saved_properties.json`。只有点击 **Accept** 才会保存。")
    with st.form("accept_save_form", clear_on_submit=False):
        c1, c2 = st.columns(2)
        with c1:
            accept_new = st.form_submit_button(
                "Accept · 保存为新物业",
                type="primary",
                use_container_width=True,
            )
        with c2:
            accept_update = st.form_submit_button(
                "Accept · 更新当前已加载物业",
                use_container_width=True,
                disabled=st.session_state.fm_saved_id is None,
            )
    if accept_new:
        try:
            prop.validate()
        except ValueError as e:
            st.error(str(e))
        else:
            sid = upsert_saved_property(prop, None)
            st.session_state.fm_saved_id = sid
            st.success("已新增保存 / Saved new row")
    elif accept_update and st.session_state.fm_saved_id:
        try:
            prop.validate()
        except ValueError as e:
            st.error(str(e))
        else:
            upsert_saved_property(prop, st.session_state.fm_saved_id)
            st.success("已更新 / Updated")
    elif st.session_state.fm_saved_id is None:
        st.caption("从「我的物业」加载一条后，可用 **Accept · 更新当前已加载物业**。")

    try:
        result = analyze_property(prop)
        sens_rows = interest_sensitivity_table(
            prop,
            principal=result.loan_after_cash_out,
            max_increase_pp=float(st.session_state.fm_sens_max),
            step_pp=float(st.session_state.fm_sens_step),
            net_yield_denominator=result.price_basis_after,
        )
    except ValueError as e:
        st.error(str(e))
        return

    mkt_eff = effective_market_value(prop)
    last_bank = last_bank_valuation_value(prop)

    st.subheader("估值口径 Valuation basis")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("套现前分母（银行估价→买价）Before denominator", _currency(result.price_basis_before))
    c2.metric("套现后分母（市价→银行→买价）After denominator", _currency(result.price_basis_after))
    c3.metric("有效市价（用于套现）Effective market", _currency(mkt_eff))
    c4.metric(
        "最近银行估价 Last bank val",
        _currency(last_bank) if last_bank else "—",
    )

    if mkt_eff > 0:
        lvr = prop.loan_amount / mkt_eff * 100
        st.metric("LVR (loan / 有效市价)", f"{lvr:.2f}%")

    st.subheader("年毛租金（按租约规则）")
    st.metric("Annual gross rent", _currency(result.annual_gross_rent))

    st.subheader("回报率 Yield — 套现前 vs 套现后")
    st.caption(
        "套现前：若购买时银行估价 < 买价则用买价作分母；否则最近 refi 银行估价，无则买价。"
        "套现后：分母 = 当前市价；未填市价则用最近银行估价。"
    )
    y1, y2, y3, y4 = st.columns(4)
    y1.metric("套现前 毛 Gross (before)", f"{result.gross_rental_yield_pct:.2f}%")
    y2.metric("套现前 净 Net (before)", f"{result.net_rental_yield_pct:.2f}%")
    y3.metric("套现后 毛 Gross (after)", f"{result.gross_yield_after_cash_out_pct:.2f}%")
    y4.metric("套现后 净 Net (after)", f"{result.net_yield_after_cash_out_pct:.2f}%")

    st.subheader("现金流 Cash flow")
    c1, c2, c3 = st.columns(3)
    c1.metric("套现前 年利息", _currency(result.annual_interest))
    c2.metric("套现前 税前净现金流", _currency(result.net_cash_before_tax))
    c3.metric("年非利息总支出（含 council/water/单元）", _currency(result.annual_non_interest_expenses))

    st.subheader("增值套现 Cash-out（市价 − 基数，×80%；须持有约 6 个月）")
    st.caption(
        f"分析日持有 {result.hold_days} 天；"
        f"{'已满 6 个月门槛' if result.cash_out_eligible else '未满 6 个月：套现额按 0'}。"
        f" 购买时银行估价：{_currency(_num0(result.purchase_bank_valuation))}；"
        f"套现用基数 {_currency(_num0(result.cash_out_cost_basis))}。"
    )
    if not result.cash_out_eligible:
        st.warning("持有未满约 6 个月（183 天）时，可套现金额按 0 计算（与银行政策一致便于保守估算）。")
    if result.cash_out_equity_release <= 0 and result.cash_out_eligible:
        st.info("有效市价相对套现基数无增值：套现额为 0。")
    elif result.cash_out_equity_release > 0:
        d1, d2, d3 = st.columns(3)
        d1.metric("可套现", _currency(result.cash_out_equity_release))
        d2.metric("套现后贷款", _currency(result.loan_after_cash_out))
        d3.metric("套现后年利息", _currency(result.annual_interest_after_cash_out))
    st.metric("套现后税前净现金流", _currency(result.net_cash_after_cash_out))

    st.subheader(f"利率敏感度（套现后贷款 {_currency(result.loan_after_cash_out)}）")
    table_rows = [
        {
            "加息 +pp": r.rate_increase_pp,
            "新利率 %": round(r.new_rate_annual * 100, 4),
            "年利息": _currency(r.annual_interest),
            "税前净现金流": _currency(r.net_cash_before_tax),
            "净回报率 %（套现后分母）": round(r.net_rental_yield_pct, 4),
        }
        for r in sens_rows
    ]
    st.dataframe(pd.DataFrame(table_rows).fillna(0), use_container_width=True, height=360)
    sens_chart = (
        alt.Chart(
            alt.Data(
                values=pd.DataFrame([{"pp": r.rate_increase_pp, "net": r.net_cash_before_tax} for r in sens_rows])
                .fillna(0)
                .to_dict(orient="records")
            )
        )
        .mark_line(point=True)
        .encode(
            x=alt.X("pp:Q", title="加息 (百分点)"),
            y=alt.Y("net:Q", title="税前净现金流 ($)"),
        )
        .properties(height=320)
    )
    st.altair_chart(sens_chart, use_container_width=True)

    st.markdown("---")
    st.caption("数据保存在项目 data/saved_properties.json。非投资建议。")


def _sum_col(rows: List[Dict[str, Any]], key: str) -> float:
    t = 0.0
    for r in rows:
        v = r.get(key)
        if isinstance(v, (int, float)):
            t += float(v)
    return t


def _render_portfolio_tab() -> None:
    st.subheader("已保存的物业")
    items = load_saved_properties()
    if not items:
        st.info("暂无保存。在「当前物业分析」填完后点「保存为新物业」；每次新增一条。")
        return

    rows = _records_fillna_zero(_portfolio_summary_rows())
    inv_rows = [r for r in rows if r.get("用途") == "投资"]
    own_rows = [r for r in rows if r.get("用途") == "自住"]

    st.markdown("### 投资物业")
    if inv_rows:
        st.dataframe(_display_portfolio_rows(inv_rows), use_container_width=True, height=min(400, 60 + len(inv_rows) * 36))
    _portfolio_cash_metrics("投资物业小计", inv_rows)

    st.markdown("### 自住物业")
    if own_rows:
        st.dataframe(_display_portfolio_rows(own_rows), use_container_width=True, height=min(400, 60 + len(own_rows) * 36))
    _portfolio_cash_metrics("自住物业小计", own_rows)

    st.markdown("### 全部物业（含金额格式：$ 与千分位）")
    st.dataframe(_display_portfolio_rows(rows), use_container_width=True, height=min(520, 60 + len(rows) * 36))
    _portfolio_cash_metrics("全部合计", rows)

    csv_buf = io.StringIO()
    if rows:
        fieldnames = [k for k in rows[0].keys() if k != "id"]
        w = csv.DictWriter(csv_buf, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})
    st.download_button(
        "下载组合 CSV（数字未加 $，便于表格公式）",
        data=csv_buf.getvalue(),
        file_name="property_portfolio.csv",
        mime="text/csv",
    )

    with st.expander("Google：一键依赖 + 账号授权 + 同步表格 + My Maps", expanded=False):
        st.caption(
            "说明：Google **不提供**官方「My Maps」写入 API。此处用您的 Google 账号写 **Google 表格**，"
            "并下载 **KML** 文件，在 [Google My Maps](https://www.google.com/maps/d/) 中「导入」即可在地图上看投资物业与分析摘要。"
        )
        if st.button("一键安装 Google 相关 Python 包", type="secondary"):
            try:
                from property_analysis.google_connect import install_google_packages

                install_google_packages()
                st.success("已安装 gspread / google-auth 等。若失败请在终端手动：pip install gspread google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client")
                st.rerun()
            except Exception as ex:
                st.error(str(ex))

        from property_analysis.google_connect import (
            load_client_config,
            load_saved_credentials,
            redirect_uri_default,
            spreadsheet_id_config,
        )

        cfg = load_client_config()
        creds = None
        try:
            creds = load_saved_credentials()
        except Exception:
            creds = None

        if not cfg:
            st.warning(
                "请先在 Google Cloud 创建 **OAuth 客户端 ID（Web 应用）**，"
                "并把下载的 `client_secret....json` 路径写入环境变量 `GOOGLE_OAUTH_CLIENT_SECRETS_JSON`，"
                "或 `.streamlit/secrets.toml` 的 `GOOGLE_OAUTH_CLIENT_SECRETS_JSON`。"
                f" **已授权重定向 URI** 须包含：`{redirect_uri_default()}`"
            )
        else:
            st.success("已检测到 OAuth 客户端配置。")
            if st.button("生成 Google 登录链接"):
                from property_analysis.google_connect import authorization_url_and_state

                auth_url, state = authorization_url_and_state(cfg, redirect_uri_default())
                st.session_state["_oauth_state"] = state
                st.session_state["_oauth_url"] = auth_url
            url = st.session_state.get("_oauth_url")
            if url:
                st.link_button("→ 在浏览器中打开并完成 Google 授权", url)
            if creds:
                if getattr(creds, "valid", False):
                    st.info("已保存 Google 登录令牌（本地 data/google_oauth_token.json）。")
                elif getattr(creds, "refresh_token", None):
                    st.caption("Access token 已过期；点「同步」时会用 refresh token 自动续期。")
                else:
                    st.warning("令牌无效或已撤销，请重新完成授权。")

        if "google_sheet_id_input" not in st.session_state:
            st.session_state.google_sheet_id_input = spreadsheet_id_config()
        new_sid = st.text_input(
            "表格 ID（可选，留空则首次同步时自动新建表格）",
            key="google_sheet_id_input",
            placeholder="从 docs.google.com/spreadsheets/d/【这里】/edit 复制",
        )

        if st.button("将组合数据同步到我的 Google 表格", type="primary"):
            try:
                from google.auth.transport.requests import Request
                from property_analysis.google_connect import (
                    load_saved_credentials,
                    push_rows_with_user_creds,
                    save_token,
                )
            except ImportError:
                st.error("请先点击「一键安装 Google 相关 Python 包」。")
            else:
                c = load_saved_credentials()
                if not c:
                    st.error("请先完成 Google 授权。")
                else:
                    if c.expired and c.refresh_token:
                        c.refresh(Request())
                        save_token(c)
                    hdr = [k for k in rows[0].keys() if k != "id"] if rows else []
                    data_rows = [[r.get(h, "") for h in hdr] for r in rows]
                    try:
                        sid_out = push_rows_with_user_creds(
                            c,
                            new_sid.strip() or None,
                            "Property_Portfolio",
                            hdr,
                            data_rows,
                        )
                        st.success(
                            f"已写入。[打开表格](https://docs.google.com/spreadsheets/d/{sid_out}/edit) — 可将此 ID 记入 secrets 的 `GOOGLE_SHEET_ID` 以便下次覆盖同一表。"
                        )
                    except Exception as ex:
                        st.error(str(ex))

        st.markdown("**投资物业 → Google My Maps**（下载 KML 后：My Maps → 创建地图 → 导入）")
        if st.button("生成投资物业 KML（含现金流/收益率摘要）"):
            pairs: List[Tuple[PropertyInput, PropertyAnalysis]] = []
            for rec in load_saved_properties():
                try:
                    p = record_to_property({k: v for k, v in rec.items() if k != "id"})
                    if p.property_use != PropertyUse.INVESTMENT:
                        continue
                    pairs.append((p, analyze_property(p)))
                except Exception:
                    continue
            if not pairs:
                st.warning("没有标记为「投资」的物业。")
            else:
                from property_analysis.geocode import geocode_nominatim
                from property_analysis.kml_export import build_investment_kml

                with st.spinner("正在解析地址坐标（OpenStreetMap，约每秒一套）…"):
                    kml = build_investment_kml(pairs, geocode=geocode_nominatim)
                st.download_button(
                    "下载 investment_properties.kml",
                    data=kml,
                    file_name="investment_properties.kml",
                    mime="application/vnd.google-earth.kml+xml",
                )

    st.divider()
    labels: List[str] = []
    id_for_label: Dict[str, str] = {}
    for r in rows:
        base = f"{r['完整地址']} [{str(r['id'])[:8]}…]"
        label = base
        n = 1
        while label in id_for_label:
            n += 1
            label = f"{base} ({n})"
        id_for_label[label] = str(r["id"])
        labels.append(label)
    choice = st.selectbox("选择要加载的物业", options=labels)
    chosen_id = id_for_label[choice]
    c1, c2 = st.columns(2)
    with c1:
        if st.button("加载到分析表单 Load into editor", type="primary"):
            st.session_state._load_id = chosen_id
            st.rerun()
    with c2:
        if st.button("删除选中 Delete", type="secondary"):
            delete_saved_property(chosen_id)
            if st.session_state.get("fm_saved_id") == chosen_id:
                st.session_state.fm_saved_id = None
            st.rerun()


if __name__ == "__main__":
    main()
