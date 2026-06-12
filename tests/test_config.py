from pathlib import Path

from src.config import load_targets


def test_load_targets_reads_current_b0g_goal_config():
    targets = load_targets(Path("config/targets.yaml"))

    assert targets["asin"] == "B0GXYYZPBW"
    assert targets["sp_target_acos"] == 0.4993
    assert targets["sp_daily_budget_current"] == 300
    assert targets["sp_orders_daily_min"] == 22
    assert targets["sp_orders_daily_max"] == 60
