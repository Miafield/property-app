from __future__ import annotations

import html
import urllib.parse
from typing import Callable, List, Optional, Tuple

from property_analysis.engine import PropertyAnalysis
from property_analysis.models import PropertyInput, PropertyUse


def _maps_search_url(full_address: str) -> str:
    q = urllib.parse.quote_plus(full_address or "Australia")
    return f"https://www.google.com/maps/search/?api=1&query={q}"


def build_investment_kml(
    items: List[Tuple[PropertyInput, PropertyAnalysis]],
    *,
    geocode: Optional[Callable[[str], Optional[Tuple[float, float]]]] = None,
) -> str:
    """
    KML for investment properties only. Google My Maps: 创建地图 → 导入 → 上传此文件。
    """
    parts: List[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        "<Document>",
        "<name>Property Master — 投资物业</name>",
    ]
    for p, a in items:
        if p.property_use != PropertyUse.INVESTMENT:
            continue
        label = p.full_address_label() or p.display_street() or "Property"
        extra_loc = ""
        coords = None
        if geocode is not None:
            coords = geocode(label + ", Australia")
        if coords is None:
            lon, lat = 151.2093, -33.8688
            extra_loc = "<br/><i>（坐标由 OpenStreetMap 未解析时使用占位点，请在 My Maps 中拖到正确位置。）</i>"
        else:
            lon, lat = coords
        desc = "<br/>".join(
            [
                f"<b>用途</b>: 投资",
                f"<b>地址</b>: {html.escape(label)}",
                f"<b>税前年现金流(套现前)</b>: ${a.net_cash_before_tax:,.0f}",
                f"<b>税前年现金流(套现后)</b>: ${a.net_cash_after_cash_out:,.0f}",
                f"<b>可套现额</b>: ${a.cash_out_equity_release:,.0f}",
                f"<b>套现前净收益率</b>: {a.net_rental_yield_pct:.2f}%",
                f'<a href="{_maps_search_url(label)}">在 Google Maps 中打开</a>',
                extra_loc,
            ]
        )
        parts.append("<Placemark>")
        parts.append(f"<name>{html.escape(label)}</name>")
        parts.append(f"<description><![CDATA[{desc}]]></description>")
        parts.append("<Point>")
        parts.append(f"<coordinates>{lon},{lat},0</coordinates>")
        parts.append("</Point>")
        parts.append("</Placemark>")
    parts.extend(["</Document>", "</kml>"])
    return "\n".join(parts)
