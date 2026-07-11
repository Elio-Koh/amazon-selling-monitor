"""Build a standalone daily CTR and TOS report for the configured ASIN."""

from __future__ import annotations

import csv
import html
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


ASIN = "B0G" + "XYYZPBW"
CAMPAIGN_METRICS_TOOL = "get_campaign_metrics_" + ASIN
PLACEMENT_PROFILE_TOOL = "list_placement_profile_" + ASIN
AUTO_CAMPAIGN = f"SC_{ASIN}_MF04_Auto_260606"
FROTHER_CAMPAIGN = f"SC_{ASIN}_MF04_Frother_P_260610"
START_DATE = "2026-06-10"
END_DATE = "2026-06-21"
CHART_START_DATE = "2026-06-10"
NO_DATA_END_DATE = "2026-06-09"
SOURCE = f"Lingxing MCP {CAMPAIGN_METRICS_TOOL} + {PLACEMENT_PROFILE_TOOL}"
ARTIFACT_DIR = Path(__file__).resolve().parents[1] / "artifacts"
HTML_FILENAME = f"{ASIN}_daily_ctr_tos_{START_DATE}_to_{END_DATE}.html"
CSV_FILENAME = f"{ASIN}_daily_ctr_tos_{START_DATE}_to_{END_DATE}.csv"

CAMPAIGNS = [
    {
        "campaign_id": "230170919088708",
        "campaign_name": AUTO_CAMPAIGN,
    },
    {
        "campaign_id": "173844737302109",
        "campaign_name": FROTHER_CAMPAIGN,
    },
]

NONZERO_DAILY_METRICS: Dict[str, List[Dict[str, Any]]] = {
    "2026-06-10": [
        {
            "campaign_id": "230170919088708",
            "campaign_name": AUTO_CAMPAIGN,
            "impressions": 30327,
            "clicks": 58,
            "spend": 75.59,
            "sales": 279.93,
            "orders": 7,
        },
        {
            "campaign_id": "173844737302109",
            "campaign_name": FROTHER_CAMPAIGN,
            "impressions": 15903,
            "clicks": 13,
            "spend": 18.61,
            "sales": 39.99,
            "orders": 1,
        },
    ],
    "2026-06-11": [
        {
            "campaign_id": "230170919088708",
            "campaign_name": AUTO_CAMPAIGN,
            "impressions": 3813,
            "clicks": 8,
            "spend": 15.15,
            "sales": 0.0,
            "orders": 0,
        },
        {
            "campaign_id": "173844737302109",
            "campaign_name": FROTHER_CAMPAIGN,
            "impressions": 1282,
            "clicks": 6,
            "spend": 12.46,
            "sales": 39.99,
            "orders": 1,
        },
    ],
    "2026-06-12": [
        {
            "campaign_id": "230170919088708",
            "campaign_name": AUTO_CAMPAIGN,
            "impressions": 4720,
            "clicks": 5,
            "spend": 8.69,
            "sales": 0.0,
            "orders": 0,
        },
        {
            "campaign_id": "173844737302109",
            "campaign_name": FROTHER_CAMPAIGN,
            "impressions": 373,
            "clicks": 1,
            "spend": 2.31,
            "sales": 0.0,
            "orders": 0,
        },
    ],
    "2026-06-13": [
        {
            "campaign_id": "230170919088708",
            "campaign_name": AUTO_CAMPAIGN,
            "impressions": 12691,
            "clicks": 20,
            "spend": 44.8,
            "sales": 0.0,
            "orders": 0,
        },
        {
            "campaign_id": "173844737302109",
            "campaign_name": FROTHER_CAMPAIGN,
            "impressions": 3188,
            "clicks": 9,
            "spend": 23.39,
            "sales": 27.99,
            "orders": 1,
        },
    ],
    "2026-06-14": [
        {
            "campaign_id": "230170919088708",
            "campaign_name": AUTO_CAMPAIGN,
            "impressions": 22771,
            "clicks": 82,
            "spend": 199.63,
            "sales": 135.96,
            "orders": 4,
        },
        {
            "campaign_id": "173844737302109",
            "campaign_name": FROTHER_CAMPAIGN,
            "impressions": 7826,
            "clicks": 60,
            "spend": 181.61,
            "sales": 147.96,
            "orders": 4,
        },
    ],
    "2026-06-15": [
        {
            "campaign_id": "230170919088708",
            "campaign_name": AUTO_CAMPAIGN,
            "impressions": 18582,
            "clicks": 136,
            "spend": 341.47,
            "sales": 244.91,
            "orders": 9,
        },
        {
            "campaign_id": "173844737302109",
            "campaign_name": FROTHER_CAMPAIGN,
            "impressions": 4755,
            "clicks": 81,
            "spend": 263.28,
            "sales": 189.93,
            "orders": 7,
        },
    ],
    "2026-06-16": [
        {
            "campaign_id": "173844737302109",
            "campaign_name": FROTHER_CAMPAIGN,
            "impressions": 10316,
            "clicks": 125,
            "spend": 395.41,
            "sales": 378.86,
            "orders": 14,
        },
        {
            "campaign_id": "230170919088708",
            "campaign_name": AUTO_CAMPAIGN,
            "impressions": 11099,
            "clicks": 71,
            "spend": 176.06,
            "sales": 26.99,
            "orders": 1,
        },
    ],
    "2026-06-17": [
        {
            "campaign_id": "230170919088708",
            "campaign_name": AUTO_CAMPAIGN,
            "impressions": 5068,
            "clicks": 57,
            "spend": 152.6,
            "sales": 161.94,
            "orders": 6,
        },
        {
            "campaign_id": "173844737302109",
            "campaign_name": FROTHER_CAMPAIGN,
            "impressions": 7093,
            "clicks": 53,
            "spend": 137.53,
            "sales": 189.93,
            "orders": 7,
        },
    ],
    "2026-06-18": [
        {
            "campaign_id": "173844737302109",
            "campaign_name": FROTHER_CAMPAIGN,
            "impressions": 7287,
            "clicks": 71,
            "spend": 182.06,
            "sales": 271.9,
            "orders": 10,
        },
        {
            "campaign_id": "230170919088708",
            "campaign_name": AUTO_CAMPAIGN,
            "impressions": 6273,
            "clicks": 55,
            "spend": 161.61,
            "sales": 161.94,
            "orders": 6,
        },
    ],
    "2026-06-19": [
        {
            "campaign_id": "173844737302109",
            "campaign_name": FROTHER_CAMPAIGN,
            "impressions": 12764,
            "clicks": 123,
            "spend": 301.2,
            "sales": 379.86,
            "orders": 14,
        },
        {
            "campaign_id": "230170919088708",
            "campaign_name": AUTO_CAMPAIGN,
            "impressions": 13230,
            "clicks": 100,
            "spend": 278.19,
            "sales": 271.9,
            "orders": 10,
        },
    ],
    "2026-06-20": [
        {
            "campaign_id": "173844737302109",
            "campaign_name": FROTHER_CAMPAIGN,
            "impressions": 25988,
            "clicks": 197,
            "spend": 512.58,
            "sales": 541.8,
            "orders": 20,
        },
        {
            "campaign_id": "230170919088708",
            "campaign_name": AUTO_CAMPAIGN,
            "impressions": 15539,
            "clicks": 148,
            "spend": 446.4,
            "sales": 559.79,
            "orders": 21,
        },
    ],
    "2026-06-21": [
        {
            "campaign_id": "173844737302109",
            "campaign_name": FROTHER_CAMPAIGN,
            "impressions": 45703,
            "clicks": 227,
            "spend": 596.94,
            "sales": 920.66,
            "orders": 33,
        },
        {
            "campaign_id": "230170919088708",
            "campaign_name": AUTO_CAMPAIGN,
            "impressions": 37301,
            "clicks": 179,
            "spend": 500.62,
            "sales": 460.83,
            "orders": 17,
        },
    ],
}

TOS_DAILY_IMPRESSIONS: Dict[str, Dict[str, int]] = {
    "2026-06-10": {"tos_impressions": 39, "placement_impressions": 42188},
    "2026-06-11": {"tos_impressions": 50, "placement_impressions": 4930},
    "2026-06-12": {"tos_impressions": 58, "placement_impressions": 5071},
    "2026-06-13": {"tos_impressions": 644, "placement_impressions": 15828},
    "2026-06-14": {"tos_impressions": 6037, "placement_impressions": 30514},
    "2026-06-15": {"tos_impressions": 6914, "placement_impressions": 23275},
    "2026-06-16": {"tos_impressions": 6346, "placement_impressions": 21324},
    "2026-06-17": {"tos_impressions": 1477, "placement_impressions": 12114},
    "2026-06-18": {"tos_impressions": 1984, "placement_impressions": 13307},
    "2026-06-19": {"tos_impressions": 2819, "placement_impressions": 25917},
    "2026-06-20": {"tos_impressions": 4691, "placement_impressions": 41460},
    "2026-06-21": {"tos_impressions": 7299, "placement_impressions": 81382},
}


def date_range(start_date: str = START_DATE, end_date: str = END_DATE) -> List[str]:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    days = (end - start).days + 1
    return [(start + timedelta(days=offset)).isoformat() for offset in range(days)]


def ctr_pct(clicks: int, impressions: int) -> Optional[float]:
    if impressions <= 0:
        return None
    return clicks / impressions * 100


def ratio_pct(numerator: int, denominator: int) -> Optional[float]:
    if denominator <= 0:
        return None
    return numerator / denominator * 100


def campaign_rows() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for day in date_range():
        metrics = NONZERO_DAILY_METRICS.get(day)
        if metrics is None:
            metrics = [
                {
                    **campaign,
                    "impressions": 0,
                    "clicks": 0,
                    "spend": 0.0,
                    "sales": 0.0,
                    "orders": 0,
                }
                for campaign in CAMPAIGNS
            ]
        for row in metrics:
            impressions = int(row["impressions"])
            clicks = int(row["clicks"])
            tos = tos_for_day(day)
            rows.append(
                {
                    "date": day,
                    "asin": ASIN,
                    "campaign_id": row["campaign_id"],
                    "campaign_name": row["campaign_name"],
                    "impressions": impressions,
                    "clicks": clicks,
                    "ctr_pct": ctr_pct(clicks, impressions),
                    "spend": float(row["spend"]),
                    "sales": float(row["sales"]),
                    "orders": int(row["orders"]),
                    "tos_impressions": tos["tos_impressions"],
                    "placement_impressions": tos["placement_impressions"],
                    "tos_impression_share_pct": tos["tos_impression_share_pct"],
                }
            )
    return rows


def tos_for_day(day: str) -> Dict[str, Any]:
    values = TOS_DAILY_IMPRESSIONS.get(day, {"tos_impressions": 0, "placement_impressions": 0})
    tos_impressions = int(values["tos_impressions"])
    placement_impressions = int(values["placement_impressions"])
    return {
        "tos_impressions": tos_impressions,
        "placement_impressions": placement_impressions,
        "tos_impression_share_pct": ratio_pct(tos_impressions, placement_impressions),
    }


def tos_summary_rows() -> List[Dict[str, Any]]:
    rows = []
    for day in date_range():
        rows.append({"date": day, **tos_for_day(day)})
    return rows


def daily_summary_rows() -> List[Dict[str, Any]]:
    by_day: Dict[str, List[Mapping[str, Any]]] = {}
    for row in campaign_rows():
        by_day.setdefault(str(row["date"]), []).append(row)

    rows = []
    for day in date_range():
        day_rows = by_day[day]
        impressions = sum(int(row["impressions"]) for row in day_rows)
        clicks = sum(int(row["clicks"]) for row in day_rows)
        spend = round(sum(float(row["spend"]) for row in day_rows), 2)
        sales = round(sum(float(row["sales"]) for row in day_rows), 2)
        orders = sum(int(row["orders"]) for row in day_rows)
        tos = tos_for_day(day)
        rows.append(
            {
                "date": day,
                "impressions": impressions,
                "clicks": clicks,
                "ctr_pct": ctr_pct(clicks, impressions),
                "spend": spend,
                "sales": sales,
                "orders": orders,
                **tos,
            }
        )
    return rows


def build_report(output_dir: Path = ARTIFACT_DIR) -> Dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / CSV_FILENAME
    html_path = output_dir / HTML_FILENAME

    detail_rows = campaign_rows()
    summary_rows = daily_summary_rows()
    write_csv(csv_path, detail_rows)
    html_path.write_text(render_html(summary_rows, detail_rows), encoding="utf-8")
    return {"html_path": str(html_path), "csv_path": str(csv_path)}


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fieldnames = [
        "date",
        "asin",
        "campaign_id",
        "campaign_name",
        "impressions",
        "clicks",
        "ctr_pct",
        "spend",
        "sales",
        "orders",
        "tos_impressions",
        "placement_impressions",
        "tos_impression_share_pct",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            out = dict(row)
            out["ctr_pct"] = "" if row["ctr_pct"] is None else f"{float(row['ctr_pct']):.6f}"
            out["tos_impression_share_pct"] = (
                "" if row["tos_impression_share_pct"] is None else f"{float(row['tos_impression_share_pct']):.6f}"
            )
            writer.writerow(out)


def render_html(summary_rows: Sequence[Mapping[str, Any]], detail_rows: Sequence[Mapping[str, Any]]) -> str:
    generated_at = datetime.now(timezone(timedelta(hours=8))).replace(microsecond=0).isoformat()
    no_impression_dates = [row["date"] for row in summary_rows if int(row["impressions"]) == 0]
    active_days = [row for row in summary_rows if int(row["impressions"]) > 0]
    chart_summary_rows = [row for row in summary_rows if str(row["date"]) >= CHART_START_DATE]
    chart_active_days = [row for row in chart_summary_rows if int(row["impressions"]) > 0]
    chart_tos_days = [row for row in chart_summary_rows if row.get("tos_impression_share_pct") is not None]
    latest = active_days[-1] if active_days else None
    latest_tos = chart_tos_days[-1] if chart_tos_days else None
    max_ctr = max((float(row["ctr_pct"]) for row in chart_active_days if row["ctr_pct"] is not None), default=0.0)
    max_tos = max(
        (float(row["tos_impression_share_pct"]) for row in chart_tos_days if row["tos_impression_share_pct"] is not None),
        default=0.0,
    )
    total_impressions = sum(int(row["impressions"]) for row in summary_rows)
    total_clicks = sum(int(row["clicks"]) for row in summary_rows)
    window_ctr = ctr_pct(total_clicks, total_impressions)

    campaign_series = []
    for campaign in CAMPAIGNS:
        rows = [
            row
            for row in detail_rows
            if row["campaign_id"] == campaign["campaign_id"]
            and str(row["date"]) >= CHART_START_DATE
            and int(row["impressions"]) > 0
        ]
        campaign_series.append(
            {
                "name": campaign["campaign_name"],
                "campaign_id": campaign["campaign_id"],
                "rows": rows,
            }
        )

    table_rows = "\n".join(render_table_row(row) for row in detail_rows)
    no_impression_preview = ", ".join(no_impression_dates[:12])
    if len(no_impression_dates) > 12:
        no_impression_preview += f", ... 共 {len(no_impression_dates)} 天"
    if not no_impression_preview:
        no_impression_preview = "本报告窗口内无零曝光日期"

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{ASIN} 每日 CTR 报告</title>
  <style>
    :root {{
      --ink: #111827;
      --muted: #6b7280;
      --line: #d1d5db;
      --panel: #ffffff;
      --bg: #f8fafc;
      --blue: #2563eb;
      --gold: #b7791f;
      --pink: #be185d;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
      line-height: 1.45;
    }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 32px 20px 56px; }}
    h1 {{ margin: 0 0 8px; font-size: 30px; letter-spacing: 0; }}
    h2 {{ margin: 0 0 12px; font-size: 20px; letter-spacing: 0; }}
    p {{ margin: 0; }}
    .subtitle {{ color: var(--muted); margin-bottom: 22px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 20px 0; }}
    .metric, section {{
      background: var(--panel);
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
    }}
    .metric {{ padding: 14px 16px; }}
    .label {{ color: var(--muted); font-size: 13px; }}
    .value {{ font-size: 24px; font-weight: 700; margin-top: 4px; }}
    section {{ padding: 18px; margin-top: 16px; }}
    .note {{ color: var(--muted); font-size: 13px; margin-top: 8px; }}
    svg {{ display: block; width: 100%; height: auto; }}
    .axis text {{ fill: var(--muted); font-size: 12px; }}
    .axis line, .axis path, .gridline {{ stroke: var(--line); stroke-width: 1; }}
    .legend {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 10px; font-size: 13px; color: var(--muted); }}
    .swatch {{ display: inline-block; width: 10px; height: 10px; margin-right: 6px; border-radius: 999px; }}
    .table-wrap {{ max-height: 520px; overflow: auto; border: 1px solid #e5e7eb; border-radius: 8px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; background: #fff; }}
    th, td {{ padding: 8px 10px; border-bottom: 1px solid #eef2f7; text-align: right; white-space: nowrap; }}
    th {{ position: sticky; top: 0; background: #f9fafb; color: #374151; z-index: 1; }}
    th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) {{ text-align: left; }}
    @media (max-width: 820px) {{
      main {{ padding: 22px 12px 40px; }}
      .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      h1 {{ font-size: 24px; }}
    }}
  </style>
</head>
<body>
<main>
  <h1>{ASIN} 每日 CTR 报告</h1>
  <p class="subtitle">数据覆盖范围：{START_DATE} 至 {END_DATE} · 图表日期范围：{CHART_START_DATE} 至 {END_DATE} · 数据源：{SOURCE} · 生成时间：{generated_at} Asia/Shanghai</p>

  <div class="grid">
    <div class="metric"><div class="label">覆盖天数</div><div class="value">{len(summary_rows)}</div></div>
    <div class="metric"><div class="label">有效曝光天数</div><div class="value">{len(active_days)}</div></div>
    <div class="metric"><div class="label">区间总 CTR</div><div class="value">{format_pct(window_ctr)}</div></div>
    <div class="metric"><div class="label">最新日 TOS 曝光占比</div><div class="value">{format_pct(latest_tos["tos_impression_share_pct"] if latest_tos else None)}</div></div>
  </div>

  <section>
    <h2>ASIN 汇总每日 CTR + TOS 曝光占比</h2>
    <p class="note">2026-06-09 及以前无曝光数据，因此本次图表从 2026-06-10 开始。左轴：ASIN 汇总 CTR；右轴：TOS 曝光占比。</p>
    {dual_axis_line_chart(
        chart_summary_rows,
        left_series={"name": "ASIN 汇总 CTR", "rows": chart_active_days, "value_key": "ctr_pct", "color": "#2563eb"},
        right_series={"name": "TOS 曝光占比", "rows": chart_tos_days, "value_key": "tos_impression_share_pct", "color": "#047857"},
        max_left=max_ctr,
        max_right=max_tos,
    )}
  </section>

  <section>
    <h2>Campaign 级每日 CTR</h2>
    <p class="note">每条线为一个 campaign，CTR 均由原始 clicks / impressions 重新计算。</p>
    {line_chart(chart_summary_rows, [
        {"name": campaign_series[0]["name"], "rows": campaign_series[0]["rows"], "color": "#b7791f"},
        {"name": campaign_series[1]["name"], "rows": campaign_series[1]["rows"], "color": "#be185d"},
    ], max_ctr=max_ctr)}
  </section>

  <section>
    <h2>数据缺口与异常</h2>
    <p>2026-06-09 及以前无曝光数据；本报告窗口固定为 2026-06-10 至 2026-06-21，未将此前日期画成 0。</p>
    <p class="note">零曝光或无可计算 CTR 的日期：{html.escape(no_impression_preview)}</p>
    <p class="note">TOS 分子/分母均按当日 {ASIN} campaign IDs 过滤后的 placement rows 计算，避免混入其他 ASIN campaign。</p>
  </section>

  <section>
    <h2>每日 Campaign 明细</h2>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Date</th><th>Campaign</th><th>Impressions</th><th>Clicks</th><th>CTR</th><th>TOS Impr.</th><th>Placement Impr.</th><th>TOS Share</th><th>Spend</th><th>Sales</th><th>Orders</th>
          </tr>
        </thead>
        <tbody>
          {table_rows}
        </tbody>
      </table>
    </div>
  </section>
</main>
<script type="application/json" id="daily-summary-data">{html.escape(json.dumps(list(summary_rows), ensure_ascii=False))}</script>
</body>
</html>
"""


def line_chart(
    all_days: Sequence[Mapping[str, Any]],
    series: Sequence[Mapping[str, Any]],
    *,
    max_ctr: float,
) -> str:
    width = 1100
    height = 360
    left = 64
    right = 22
    top = 24
    bottom = 46
    chart_width = width - left - right
    chart_height = height - top - bottom
    days = [str(row["date"]) for row in all_days]
    day_index = {day: index for index, day in enumerate(days)}
    y_max = max(1.0, round(max_ctr + 0.25, 2))

    def x_for(day: str) -> float:
        if len(days) == 1:
            return left
        return left + day_index[day] / (len(days) - 1) * chart_width

    def y_for(value: float) -> float:
        return top + (1 - value / y_max) * chart_height

    y_ticks = [0, y_max / 2, y_max]
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="CTR line chart">',
        '<g class="axis">',
    ]
    for tick in y_ticks:
        y = y_for(tick)
        parts.append(f'<line class="gridline" x1="{left}" y1="{y:.2f}" x2="{width - right}" y2="{y:.2f}"></line>')
        parts.append(f'<text x="{left - 10}" y="{y + 4:.2f}" text-anchor="end">{tick:.2f}%</text>')
    parts.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}"></line>')
    parts.append(f'<line x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}"></line>')

    for label in axis_labels(days):
        x = x_for(label)
        parts.append(f'<line x1="{x:.2f}" y1="{height - bottom}" x2="{x:.2f}" y2="{height - bottom + 5}"></line>')
        parts.append(f'<text x="{x:.2f}" y="{height - 18}" text-anchor="middle">{label[5:]}</text>')
    parts.append("</g>")

    legend = []
    for item in series:
        rows = [row for row in item["rows"] if row.get("ctr_pct") is not None]
        if not rows:
            continue
        points = [(x_for(str(row["date"])), y_for(float(row["ctr_pct"]))) for row in rows]
        path = " ".join(("M" if index == 0 else "L") + f" {x:.2f} {y:.2f}" for index, (x, y) in enumerate(points))
        color = str(item["color"])
        name = html.escape(str(item["name"]))
        parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"></path>')
        for x, y in points:
            parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3.5" fill="#fff" stroke="{color}" stroke-width="2"></circle>')
        last_x, last_y = points[-1]
        parts.append(f'<text x="{last_x + 7:.2f}" y="{last_y + 4:.2f}" fill="{color}" font-size="12">{format_pct(rows[-1]["ctr_pct"])}</text>')
        legend.append(f'<span><span class="swatch" style="background:{color}"></span>{name}</span>')

    parts.append("</svg>")
    parts.append(f'<div class="legend">{"".join(legend)}</div>')
    return "\n".join(parts)


def dual_axis_line_chart(
    all_days: Sequence[Mapping[str, Any]],
    *,
    left_series: Mapping[str, Any],
    right_series: Mapping[str, Any],
    max_left: float,
    max_right: float,
) -> str:
    width = 1100
    height = 380
    left = 64
    right = 76
    top = 24
    bottom = 52
    chart_width = width - left - right
    chart_height = height - top - bottom
    days = [str(row["date"]) for row in all_days]
    day_index = {day: index for index, day in enumerate(days)}
    left_max = max(1.0, round(max_left + 0.25, 2))
    right_max = max(5.0, round(max_right + 3, 2))

    def x_for(day: str) -> float:
        if len(days) == 1:
            return left
        return left + day_index[day] / (len(days) - 1) * chart_width

    def y_left(value: float) -> float:
        return top + (1 - value / left_max) * chart_height

    def y_right(value: float) -> float:
        return top + (1 - value / right_max) * chart_height

    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="ASIN CTR and TOS impression share line chart">',
        '<g class="axis">',
    ]
    for tick in (0, left_max / 2, left_max):
        y = y_left(tick)
        parts.append(f'<line class="gridline" x1="{left}" y1="{y:.2f}" x2="{width - right}" y2="{y:.2f}"></line>')
        parts.append(f'<text x="{left - 10}" y="{y + 4:.2f}" text-anchor="end">{tick:.2f}%</text>')
    for tick in (0, right_max / 2, right_max):
        y = y_right(tick)
        parts.append(f'<text x="{width - right + 10}" y="{y + 4:.2f}" text-anchor="start">{tick:.1f}%</text>')
    parts.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}"></line>')
    parts.append(f'<line x1="{width - right}" y1="{top}" x2="{width - right}" y2="{height - bottom}"></line>')
    parts.append(f'<line x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}"></line>')

    for label in axis_labels(days):
        x = x_for(label)
        parts.append(f'<line x1="{x:.2f}" y1="{height - bottom}" x2="{x:.2f}" y2="{height - bottom + 5}"></line>')
        parts.append(f'<text x="{x:.2f}" y="{height - 20}" text-anchor="middle">{label[5:]}</text>')

    parts.append(f'<text x="{left}" y="16" fill="{left_series["color"]}" font-size="12">左轴：{html.escape(str(left_series["name"]))}</text>')
    parts.append(f'<text x="{width - right}" y="16" fill="{right_series["color"]}" font-size="12" text-anchor="end">右轴：{html.escape(str(right_series["name"]))}</text>')
    parts.append("</g>")

    legend = []
    for item, mapper in ((left_series, y_left), (right_series, y_right)):
        rows = [row for row in item["rows"] if row.get(str(item["value_key"])) is not None]
        if not rows:
            continue
        points = [(x_for(str(row["date"])), mapper(float(row[str(item["value_key"])]))) for row in rows]
        path = " ".join(("M" if index == 0 else "L") + f" {x:.2f} {y:.2f}" for index, (x, y) in enumerate(points))
        color = str(item["color"])
        name = html.escape(str(item["name"]))
        parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"></path>')
        for x, y in points:
            parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3.5" fill="#fff" stroke="{color}" stroke-width="2"></circle>')
        last_x, last_y = points[-1]
        parts.append(f'<text x="{last_x + 7:.2f}" y="{last_y + 4:.2f}" fill="{color}" font-size="12">{format_pct(rows[-1][str(item["value_key"])])}</text>')
        legend.append(f'<span><span class="swatch" style="background:{color}"></span>{name}</span>')

    parts.append("</svg>")
    parts.append(f'<div class="legend">{"".join(legend)}</div>')
    return "\n".join(parts)


def axis_labels(days: Sequence[str]) -> List[str]:
    if len(days) <= 8:
        return list(days)
    return [days[0], days[len(days) // 2], days[-1]]


def render_table_row(row: Mapping[str, Any]) -> str:
    return (
        "<tr>"
        f"<td>{html.escape(str(row['date']))}</td>"
        f"<td>{html.escape(str(row['campaign_name']))}</td>"
        f"<td>{int(row['impressions']):,}</td>"
        f"<td>{int(row['clicks']):,}</td>"
        f"<td>{format_pct(row['ctr_pct'])}</td>"
        f"<td>{int(row['tos_impressions']):,}</td>"
        f"<td>{int(row['placement_impressions']):,}</td>"
        f"<td>{format_pct(row['tos_impression_share_pct'])}</td>"
        f"<td>${float(row['spend']):,.2f}</td>"
        f"<td>${float(row['sales']):,.2f}</td>"
        f"<td>{int(row['orders']):,}</td>"
        "</tr>"
    )


def format_pct(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}%"


def main() -> None:
    outputs = build_report()
    print(f"HTML: {outputs['html_path']}")
    print(f"CSV: {outputs['csv_path']}")


if __name__ == "__main__":
    main()
