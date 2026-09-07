"""Paper broker: cash ledger, transaction charges, buy/sell round trip."""

import pytest

from tradefish import costs, db
from tradefish.broker import paper


@pytest.fixture(autouse=True)
def clean_db(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DB", str(tmp_path / "app.db"))
    db.init_db()


def test_buy_deducts_value_plus_charges():
    paper.buy("INFY", 1500.0, 4, "2026-08-03")
    expected = 30000 - 6000 - costs.side_cost(6000, "buy")
    assert paper.cash() == pytest.approx(expected)


def test_sell_realizes_pnl_net_of_charges():
    t = paper.buy("INFY", 100.0, 10, "2026-08-03")
    paper.sell(t["position_id"], 106.0, reason="take_profit")
    expected = (30000 - 1000 - costs.side_cost(1000, "buy")
                + 1060 - costs.side_cost(1060, "sell"))
    assert paper.cash() == pytest.approx(expected)
    snap = paper.snapshot()
    assert snap["open_count"] == 0
    assert snap["net"] > 0  # +6% beats the charges


def test_insufficient_cash_rejected():
    with pytest.raises(ValueError, match="insufficient cash"):
        paper.buy("INFY", 3500.0, 10, "2026-08-03")  # 35000 > 30000
    assert paper.cash() == 30000  # nothing recorded


def test_snapshot_and_ledger():
    paper.buy("TCS", 100.0, 5, "2026-08-03")
    snap = paper.snapshot()
    assert snap["open_count"] == 1
    assert snap["invested"] == 500
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM paper_transactions").fetchone()
    assert row["side"] == "buy" and row["cash_delta"] < -500


def test_sell_unknown_position_rejected():
    with pytest.raises(ValueError, match="no open position"):
        paper.sell(999, 100.0)
