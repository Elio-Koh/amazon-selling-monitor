from datetime import date

from src.supply_inputs import (
    build_sales_plan_progress,
    build_google_sheet_export_url,
    compute_stockout_risk,
    parse_fba_shipments_csv,
    parse_logistics_cycle_csv,
    parse_procurement_csv,
    parse_sales_plan_csv,
)


REAL_ASIN = "B0G" + "XYYZPBW"


SALES_PLAN_CSV = """更新时间：2026年6月1日,,,,,,,,,,,,,
月份,1,2,3,4,5,6,7,8,9,10,11,12,全年合计
销量,,,,,,3000,5000,8000,10000,15000,20000,20000,81000
"""


HEADERLESS_FBA_SHIPMENTS_CSV = f"""2026/6/29,0704,202606290092,供应商,美西仓（WPLA3）,,{REAL_ASIN},850083328580,4980,4980,83,60,,,"美西仓（WPLA3） 4600 E Wall St,Ontario,CA,91761",普船 卡派，0708开船-,"美国 MF04带收纳支架片配件款黑色 发美西仓（WPLA3）, 83箱共4980pc",,,,,,,,,,,,60pc箱规，入库SKU TYKMF040K00US100-60pc,
2026/4/22,0425,202604220025,供应商,SC-COOKING SCIENCE US,TYKMF040K00US100-US-CS002,{REAL_ASIN},850083328580,1008,192,4,48,FBA19BYTKYSW,8DHYHV2V,"ABE8 - 401 Independence Road 08518-2200 - Florence, NJ - United States",美森 卡车,0429-0512到港-0521送仓,,,,,,,,,,,,,
,,,,,,,,,192,4,48,FBA19BYZZNWH,1QTZB3SS,"PSP3 - 64165 19th AVE 92240 - DESERT HOT SPRINGS, CA - United States",美森,,,,,,,,,,,,,,
"""


PROCUREMENT_CSV = """产品交期,55天,,,,,
不含税采购成本(含研发费）,$5.48,￥38.38,,,,
,,,,未交数量,19168,
备货汇总,40000,,,出货汇总,20832,
备货日期,渠道AM US,交付情况,,交付日期,数量,建单发货
3月25日,9000,DONE,,4月22日,1008,DONE
4月7日,5000,DONE,,4月27日,480,DONE
4月28日,11000,partial done,,5月6日,2496,DONE
5月8日,15000,预计7月中开始交付,,5月16日,5520,DONE
,,,,5月23日,5328,DONE
,,,,6月13日,6000,DONE
"""


FBA_SHIPMENTS_CSV = f"""安排时间,出货时间,飞书审批单号,发货地,收货地,（M）SKU,ASIN,产品标,发货总数,件数,Box,装箱数,Shipment ID,Refernce ID,Ship to,运输方式,填写送达日期,实际送达,后台跟踪号
2026/4/22,0425,202604220025,供应商,SC-COOKING SCIENCE US,TYKMF040K00US100-US-CS002,{REAL_ASIN},850083328580,1008,192,4,48,FBA19BYTKYSW,8DHYHV2V,ABE8,美森 卡车,0429-0512到港-0521送仓,,
,,,,,,,,,192,4,48,FBA19BYZZNWH,1QTZB3SS,PSP3,美森,,,
2026/5/6,0509,202605070016,供应商,SC-COOKING SCIENCE US,TYKMF040K00US100-US-CS002,{REAL_ASIN},850083328580,2496,528,11,48,FBA19CSXY4Z5,4HIGGL1H,RDU2,美森,1Z765YW90320219494,June 16,
,,,,,,,,,432,9,48,FBA19CSZJY29,8PBJCO4T,SMF3,美森 卡派,,预计6/23送仓,
"""


LOGISTICS_CYCLE_CSV = """物流方式,投递时效
美森快船,25-30天
普通慢船,40-50天
UPS美仓自提,7-15天
"""


def test_parse_sales_plan_extracts_monthly_units_and_current_month_pace():
    plan = parse_sales_plan_csv(SALES_PLAN_CSV, anchor_date=date(2026, 6, 17))

    assert plan["updated_at"] == "更新时间：2026年6月1日"
    assert plan["monthly_units"][6] == 3000
    assert plan["monthly_units"][12] == 20000
    assert plan["current_month_target_units"] == 3000
    assert plan["planned_daily_units"] == 100.0
    assert plan["rows"][0] == {"month": 6, "target_units": 3000}


def test_build_sales_plan_progress_merges_sheet_targets_with_lingxing_actuals():
    plan = parse_sales_plan_csv(SALES_PLAN_CSV, anchor_date=date(2026, 7, 11))

    progress = build_sales_plan_progress(
        plan,
        actual_units_by_month={6: 1845, 7: 1787},
        anchor_date=date(2026, 7, 11),
        actuals_source="lingxing_store_sales_units",
    )

    june = progress[0]
    july = progress[1]
    assert june["month"] == 6
    assert june["target_units"] == 3000
    assert june["actual_units"] == 1845
    assert june["completion_rate"] == 0.615
    assert june["time_progress"] == 1.0
    assert june["pace_gap_units"] == -1155
    assert june["status"] == "behind"
    assert july["month"] == 7
    assert july["target_units"] == 5000
    assert july["actual_units"] == 1787
    assert july["completion_rate"] == 0.3574
    assert july["time_progress"] == 0.3548
    assert july["pace_gap_units"] == 13
    assert july["status"] == "on_track"
    assert july["actuals_source"] == "lingxing_store_sales_units"


def test_build_sales_plan_progress_keeps_targets_when_actuals_are_unavailable():
    plan = parse_sales_plan_csv(SALES_PLAN_CSV, anchor_date=date(2026, 7, 11))

    progress = build_sales_plan_progress(
        plan,
        actual_units_by_month={},
        anchor_date=date(2026, 7, 11),
        actuals_source="unavailable",
    )

    july = progress[1]
    assert july["target_units"] == 5000
    assert july["actual_units"] is None
    assert july["completion_rate"] is None
    assert july["pace_gap_units"] is None
    assert july["status"] == "actual_unavailable"


def test_parse_procurement_extracts_summary_and_delivery_rows():
    procurement = parse_procurement_csv(PROCUREMENT_CSV, reference_year=2026)

    assert procurement["lead_time_days"] == 55
    assert procurement["unit_cost_usd"] == 5.48
    assert procurement["purchase_total_units"] == 40000
    assert procurement["shipped_total_units"] == 20832
    assert procurement["unshipped_units"] == 19168
    assert procurement["rows"][0]["purchase_date"] == "2026-03-25"
    assert procurement["rows"][3]["planned_units"] == 15000
    assert procurement["rows"][-1]["delivery_units"] == 6000


def test_parse_fba_shipments_fills_down_group_fields_and_classifies_open_units():
    shipments = parse_fba_shipments_csv(FBA_SHIPMENTS_CSV, asin=REAL_ASIN)

    assert shipments["total_units"] == 1344
    assert shipments["delivered_units"] == 528
    assert shipments["open_units"] == 816
    assert shipments["rows"][1]["arranged_date"] == "2026-04-22"
    assert shipments["rows"][1]["asin"] == REAL_ASIN
    assert shipments["rows"][1]["shipment_id"] == "FBA19BYZZNWH"
    assert shipments["rows"][2]["status"] == "delivered"
    assert shipments["rows"][3]["status"] == "expected"


def test_parse_fba_shipments_accepts_headerless_google_sheet_export_for_display_rows():
    shipments = parse_fba_shipments_csv(HEADERLESS_FBA_SHIPMENTS_CSV, asin=REAL_ASIN)

    assert shipments["total_units"] == 5364
    assert shipments["open_units"] == 5364
    assert shipments["rows"][0]["arranged_date"] == "2026-06-29"
    assert shipments["rows"][0]["group_total_units"] == 4980
    assert shipments["rows"][0]["line_units"] == 4980
    assert shipments["display_rows"][0]["Arranged Date"] == "2026/6/29"
    assert shipments["display_rows"][0]["ASIN"] == REAL_ASIN
    assert shipments["display_rows"][1]["Shipment ID"] == "FBA19BYTKYSW"
    assert shipments["display_rows"][2]["Shipment ID"] == "FBA19BYZZNWH"


def test_parse_logistics_cycle_extracts_day_ranges():
    cycles = parse_logistics_cycle_csv(LOGISTICS_CYCLE_CSV)

    assert cycles["rows"][0] == {"method": "美森快船", "min_days": 25, "max_days": 30, "raw_lead_time": "25-30天"}
    assert cycles["rows"][2]["max_days"] == 15


def test_compute_stockout_risk_uses_plan_pace_and_thresholds():
    sales_plan = parse_sales_plan_csv(SALES_PLAN_CSV, anchor_date=date(2026, 6, 17))

    critical = compute_stockout_risk(1000, sales_plan, anchor_date=date(2026, 6, 17))
    high = compute_stockout_risk(2500, sales_plan, anchor_date=date(2026, 6, 17))
    medium = compute_stockout_risk(4000, sales_plan, anchor_date=date(2026, 6, 17))
    low = compute_stockout_risk(5000, sales_plan, anchor_date=date(2026, 6, 17))

    assert critical["level"] == "critical"
    assert critical["coverage_days"] == 10.0
    assert critical["projected_stockout_date"] == "2026-06-27"
    assert high["level"] == "high"
    assert medium["level"] == "medium"
    assert low["level"] == "low"


def test_compute_stockout_risk_records_inventory_and_sales_plan_gaps():
    missing_inventory = compute_stockout_risk(None, {"planned_daily_units": 100}, anchor_date=date(2026, 6, 17))
    missing_plan = compute_stockout_risk(100, {}, anchor_date=date(2026, 6, 17))
    zero_stock = compute_stockout_risk(0, {"planned_daily_units": 100}, anchor_date=date(2026, 6, 17))

    assert missing_inventory["level"] == "unknown"
    assert "inventory.fba_fulfillable" in missing_inventory["data_gaps"]
    assert missing_plan["level"] == "unknown"
    assert "operations.sales_plan.planned_daily_units" in missing_plan["data_gaps"]
    assert zero_stock["level"] == "critical"
    assert zero_stock["coverage_days"] == 0.0


def test_google_sheet_export_url_accepts_full_sheet_url_without_persisting_sheet_id():
    url = build_google_sheet_export_url(
        "https://docs.google.com/spreadsheets/d/example-sheet-id/edit?gid=1400239777#gid=1400239777",
        "1400239777",
    )

    assert url == "https://docs.google.com/spreadsheets/d/example-sheet-id/export?format=csv&gid=1400239777"
