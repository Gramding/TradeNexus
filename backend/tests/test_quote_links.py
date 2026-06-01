from conftest import make_trade
from quote_links import build_quote_url


# ---------------------------------------------------------------------------
# Pure resolver
# ---------------------------------------------------------------------------

RH = {"name": "Robinhood", "quote_url_template": "https://robinhood.com/stocks/{value}", "quote_url_key": "ticker"}
INSTR = {"symbol": "VOD.L", "ticker": "VOD", "isin": "GB00BH4HKS39"}


def test_broker_deep_link_uses_chosen_key():
    out = build_quote_url({"ticker": "VOD"}, INSTR, RH)
    assert out == {
        "url": "https://robinhood.com/stocks/VOD",
        "source": "broker",
        "label": "View on Robinhood",
    }


def test_broker_isin_key():
    broker = {"name": "Trading 212", "quote_url_template": "https://www.trading212.com/x/{value}", "quote_url_key": "isin"}
    out = build_quote_url({}, INSTR, broker)
    assert out["url"] == "https://www.trading212.com/x/GB00BH4HKS39"
    assert out["source"] == "broker"


def test_identifier_url_encoded():
    # A symbol-keyed template must URL-encode reserved characters like '='.
    broker = {"name": "X", "quote_url_template": "https://x.com/q/{value}", "quote_url_key": "symbol"}
    out = build_quote_url({}, {"symbol": "EURUSD=X", "ticker": "EUR/USD", "isin": None}, broker)
    assert out["url"] == "https://x.com/q/EURUSD%3DX"


def test_empty_identifier_falls_through_to_yahoo():
    # ISIN key chosen but the instrument has no ISIN -> Yahoo by symbol.
    broker = {"name": "EU", "quote_url_template": "https://eu.com/{value}", "quote_url_key": "isin"}
    out = build_quote_url({}, {"symbol": "AAPL", "ticker": "AAPL", "isin": None}, broker)
    assert out["source"] == "yahoo"
    assert out["url"] == "https://finance.yahoo.com/quote/AAPL"


def test_named_placeholder_isin():
    broker = {"name": "TR", "quote_url_template": "https://traderepublic.com/{isin}", "quote_url_key": "symbol"}
    out = build_quote_url({}, INSTR, broker)
    assert out["source"] == "broker"
    assert out["url"] == "https://traderepublic.com/GB00BH4HKS39"


def test_named_placeholder_composite():
    broker = {"name": "X", "quote_url_template": "https://x.com/{ticker}.{exchange}", "quote_url_key": "symbol"}
    inst = {"symbol": "SAP.DE", "ticker": "SAP", "isin": "DE0007164600", "exchange": "GER"}
    out = build_quote_url({}, inst, broker)
    assert out["url"] == "https://x.com/SAP.GER"


def test_named_placeholder_missing_field_falls_through():
    # {isin} template on an instrument with no ISIN -> Yahoo fallback.
    broker = {"name": "TR", "quote_url_template": "https://x.com/{isin}", "quote_url_key": "symbol"}
    out = build_quote_url({}, {"symbol": "AAPL", "ticker": "AAPL", "isin": None}, broker)
    assert out["source"] == "yahoo"


def test_unknown_placeholder_falls_through():
    broker = {"name": "X", "quote_url_template": "https://x.com/{wkn}", "quote_url_key": "symbol"}
    out = build_quote_url({}, INSTR, broker)
    assert out["source"] == "yahoo"


def test_non_https_template_falls_through():
    broker = {"name": "Bad", "quote_url_template": "http://insecure.com/{value}", "quote_url_key": "ticker"}
    out = build_quote_url({}, INSTR, broker)
    assert out["source"] == "yahoo"
    assert out["url"].startswith("https://")


def test_no_broker_yahoo_fallback():
    out = build_quote_url({"ticker": "VOD"}, INSTR, None)
    assert out == {
        "url": "https://finance.yahoo.com/quote/VOD.L",
        "source": "yahoo",
        "label": "View on Yahoo Finance",
    }


def test_no_instrument_search_fallback():
    out = build_quote_url({"ticker": "TSLA"}, None, RH)
    assert out == {
        "url": "https://finance.yahoo.com/search?q=TSLA",
        "source": "search_fallback",
        "label": "Search TSLA",
    }


def test_every_branch_is_https():
    cases = [
        build_quote_url({"ticker": "VOD"}, INSTR, RH),
        build_quote_url({"ticker": "VOD"}, INSTR, None),
        build_quote_url({"ticker": "VOD"}, None, None),
    ]
    assert all(c["url"].startswith("https://") for c in cases)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _make_instrument(client, **over):
    body = {"symbol": "VOD.L", "ticker": "VOD", "name": "Vodafone", "isin": "GB00BH4HKS39"}
    body.update(over)
    return client.post("/instruments", json=body).json()


def test_trade_quote_url_broker_link(client, user_id):
    bid = client.post("/brokers", json={
        "name": "Robinhood",
        "quote_url_template": "https://robinhood.com/stocks/{value}",
        "quote_url_key": "ticker",
    }).json()["id"]
    instr = _make_instrument(client)
    trade = make_trade(client, user_id, ticker="VOD", broker_id=bid, instrument_id=instr["id"])

    out = client.get(f"/trades/{trade['id']}/quote-url").json()
    assert out["source"] == "broker"
    assert out["url"] == "https://robinhood.com/stocks/VOD"
    assert out["label"] == "View on Robinhood"


def test_trade_quote_url_search_fallback_without_instrument(client, user_id):
    trade = make_trade(client, user_id, ticker="TSLA")  # no broker, no instrument
    out = client.get(f"/trades/{trade['id']}/quote-url").json()
    assert out["source"] == "search_fallback"
    assert out["url"] == "https://finance.yahoo.com/search?q=TSLA"


def test_trade_quote_url_404(client):
    assert client.get("/trades/999999/quote-url").status_code == 404


def test_instrument_quote_url_without_broker(client):
    instr = _make_instrument(client)
    out = client.get(f"/instruments/{instr['id']}/quote-url").json()
    assert out["source"] == "yahoo"
    assert out["url"] == "https://finance.yahoo.com/quote/VOD.L"


def test_instrument_quote_url_with_broker(client):
    bid = client.post("/brokers", json={
        "name": "Robinhood",
        "quote_url_template": "https://robinhood.com/stocks/{value}",
        "quote_url_key": "ticker",
    }).json()["id"]
    instr = _make_instrument(client)
    out = client.get(f"/instruments/{instr['id']}/quote-url", params={"broker_id": bid}).json()
    assert out["source"] == "broker"
    assert out["url"] == "https://robinhood.com/stocks/VOD"


def test_instrument_quote_url_404(client):
    assert client.get("/instruments/999999/quote-url").status_code == 404
