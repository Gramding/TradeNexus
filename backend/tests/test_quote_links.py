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


def test_isin_template_recovers_isin_from_symbol_when_column_blank():
    # ISIN-keyed instruments store the ISIN as symbol/ticker while the dedicated
    # isin column is blank; an {isin}/isin-keyed template must still resolve to the
    # broker rather than falling through to the search fallback.
    broker = {"name": "Smart Broker +",
              "quote_url_template": "https://app.smartbrokerplus.de/p/prospect/assets/{isin}",
              "quote_url_key": "isin"}
    inst = {"symbol": "DE000GW1MCC0", "ticker": "DE000GW1MCC0", "isin": "", "exchange": ""}
    out = build_quote_url({"ticker": "DE000GW1MCC0"}, inst, broker, source="onvista")
    assert out["source"] == "broker"
    assert out["url"] == "https://app.smartbrokerplus.de/p/prospect/assets/DE000GW1MCC0"


def test_isin_template_recovers_isin_from_free_text_trade_ticker():
    # A free-text trade (no instrument) logged under its ISIN still resolves an
    # {isin} broker template from the trade ticker.
    broker = {"name": "SB", "quote_url_template": "https://x.com/{isin}", "quote_url_key": "isin"}
    out = build_quote_url({"ticker": "DE000GW1MCC0"}, None, broker)
    assert out["source"] == "broker"
    assert out["url"] == "https://x.com/DE000GW1MCC0"


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


def test_no_instrument_broker_link_from_ticker():
    # A free-text trade (no instrument) still honors a {value}/ticker broker
    # template, using the trade's ticker as the identifier.
    out = build_quote_url({"ticker": "TSLA"}, None, RH)
    assert out == {
        "url": "https://robinhood.com/stocks/TSLA",
        "source": "broker",
        "label": "View on Robinhood",
    }


def test_no_instrument_isin_template_falls_through():
    # An {isin} template can't resolve without an instrument -> source fallback.
    broker = {"name": "SB", "quote_url_template": "https://x.com/{isin}", "quote_url_key": "isin"}
    out = build_quote_url({"ticker": "TSLA"}, None, broker)
    assert out["source"] == "search_fallback"  # default source is Yahoo


# ── Source-aware fallback (Onvista) ─────────────────────────────────────────

def test_onvista_source_links_by_isin():
    out = build_quote_url({"ticker": "VOD"}, INSTR, None, source="onvista")
    assert out["source"] == "onvista"
    assert out["url"] == "https://www.onvista.de/suche/?searchValue=GB00BH4HKS39"
    assert out["label"] == "View on Onvista"


def test_onvista_source_falls_back_to_ticker_without_isin():
    inst = {"symbol": "AAPL", "ticker": "AAPL", "isin": None}
    out = build_quote_url({}, inst, None, source="onvista")
    assert out["source"] == "onvista"
    assert out["url"] == "https://www.onvista.de/suche/?searchValue=AAPL"


def test_onvista_source_no_instrument_uses_trade_ticker():
    out = build_quote_url({"ticker": "TSLA"}, None, None, source="onvista")
    assert out["source"] == "onvista"
    assert out["url"] == "https://www.onvista.de/suche/?searchValue=TSLA"


def test_broker_link_wins_even_under_onvista_source():
    out = build_quote_url({"ticker": "VOD"}, INSTR, RH, source="onvista")
    assert out["source"] == "broker"
    assert out["url"] == "https://robinhood.com/stocks/VOD"


# ── Broker's own price source drives the fallback ───────────────────────────

def test_onvista_broker_without_template_links_by_isin():
    # Broker priced via Onvista, no deep link configured -> Onvista by ISIN,
    # NOT Yahoo, even though the global source defaults to Yahoo.
    broker = {"name": "Smartbroker", "price_source": "onvista",
              "quote_url_template": None, "quote_url_key": "symbol"}
    out = build_quote_url({"ticker": "VOD"}, INSTR, broker)
    assert out["source"] == "onvista"
    assert out["url"] == "https://www.onvista.de/suche/?searchValue=GB00BH4HKS39"


def test_onvista_broker_failed_template_falls_to_onvista_not_yahoo():
    # An {isin} template on an instrument with no ISIN can't resolve; because the
    # broker is priced via Onvista the link falls to Onvista (by ticker), never Yahoo.
    broker = {"name": "Smartbroker", "price_source": "onvista",
              "quote_url_template": "https://x.com/{isin}", "quote_url_key": "isin"}
    out = build_quote_url({}, {"symbol": "AAPL", "ticker": "AAPL", "isin": None}, broker)
    assert out["source"] == "onvista"
    assert out["url"] == "https://www.onvista.de/suche/?searchValue=AAPL"


def test_broker_onvista_overrides_global_yahoo():
    # The broker is priced via Onvista while the global setting is Yahoo -> Onvista.
    broker = {"name": "Smartbroker", "price_source": "onvista",
              "quote_url_template": None, "quote_url_key": "symbol"}
    out = build_quote_url({"ticker": "VOD"}, INSTR, broker, source="yahoo_finance")
    assert out["source"] == "onvista"


def test_global_onvista_wins_when_broker_at_default_yahoo():
    # The global source is Onvista; the broker is still at its Yahoo default and has
    # no deep link. Onvista is sticky, so the link must NOT fall back to Yahoo.
    broker = {"name": "Generic", "price_source": "yahoo_finance",
              "quote_url_template": None, "quote_url_key": "symbol"}
    out = build_quote_url({"ticker": "VOD"}, INSTR, broker, source="onvista")
    assert out["source"] == "onvista"
    assert out["url"] == "https://www.onvista.de/suche/?searchValue=GB00BH4HKS39"


def test_both_yahoo_stays_yahoo():
    # Neither source is Onvista and no deep link -> Yahoo, as before.
    broker = {"name": "Generic", "price_source": "yahoo_finance",
              "quote_url_template": None, "quote_url_key": "symbol"}
    out = build_quote_url({"ticker": "VOD"}, INSTR, broker, source="yahoo_finance")
    assert out["source"] == "yahoo"


def test_instrument_quote_url_follows_onvista_setting(client):
    client.put("/settings", json={"price_source": "onvista"})
    instr = _make_instrument(client)  # has ISIN GB00BH4HKS39
    out = client.get(f"/instruments/{instr['id']}/quote-url").json()
    assert out["source"] == "onvista"
    assert out["url"] == "https://www.onvista.de/suche/?searchValue=GB00BH4HKS39"


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


def test_trade_quote_url_onvista_broker_empty_template(client, user_id):
    # User's report: a broker priced via Onvista with an empty Quote URL template
    # must link to Onvista by ISIN, NOT Yahoo (global setting still defaults to Yahoo).
    bid = client.post("/brokers", json={"name": "Smartbroker", "price_source": "onvista"}).json()["id"]
    instr = _make_instrument(client)  # ISIN GB00BH4HKS39
    trade = make_trade(client, user_id, ticker="VOD", broker_id=bid, instrument_id=instr["id"])
    out = client.get(f"/trades/{trade['id']}/quote-url").json()
    assert out["source"] == "onvista"
    assert out["url"] == "https://www.onvista.de/suche/?searchValue=GB00BH4HKS39"


def test_trade_quote_url_configured_template_not_ignored(client, user_id):
    # User's report: a configured Quote URL template must be honored, even for an
    # Onvista-priced broker (the deep link wins over the source fallback).
    bid = client.post("/brokers", json={
        "name": "Smartbroker", "price_source": "onvista",
        "quote_url_template": "https://app.smartbrokerplus.de/p/{isin}",
        "quote_url_key": "isin",
    }).json()["id"]
    instr = _make_instrument(client)  # ISIN GB00BH4HKS39
    trade = make_trade(client, user_id, ticker="VOD", broker_id=bid, instrument_id=instr["id"])
    out = client.get(f"/trades/{trade['id']}/quote-url").json()
    assert out["source"] == "broker"
    assert out["url"] == "https://app.smartbrokerplus.de/p/GB00BH4HKS39"


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


def test_instrument_quote_url_onvista_broker_without_template(client):
    # Broker priced via Onvista with no deep link -> the position link goes to
    # Onvista by ISIN, never Yahoo (global price source still defaults to Yahoo).
    bid = client.post("/brokers", json={"name": "Smartbroker", "price_source": "onvista"}).json()["id"]
    instr = _make_instrument(client)  # has ISIN GB00BH4HKS39
    out = client.get(f"/instruments/{instr['id']}/quote-url", params={"broker_id": bid}).json()
    assert out["source"] == "onvista"
    assert out["url"] == "https://www.onvista.de/suche/?searchValue=GB00BH4HKS39"


def test_instrument_quote_url_404(client):
    assert client.get("/instruments/999999/quote-url").status_code == 404
