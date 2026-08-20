"""Run-loop integration tests for the VL market maker."""

from __future__ import annotations

import time
from decimal import Decimal

from rotor.mm import vl_runner as vr
from rotor.mm.exchange.client import MarketInfo, OrderRecord, VLBatchResult
from rotor.mm.vl_config import BudgetConfig, PairConfig, VLConfig
from rotor.price_reference.models import PriceObservation
from rotor.updater import GitUpdateResult


def _pair(market: str, *, qty: str = "10", fixed_bps: str = "50") -> PairConfig:
    return PairConfig(
        market=market,
        price_source="wise",
        qty_base=Decimal(qty),
        fixed_bps=Decimal(fixed_bps),
    )


def _config(*, pairs: list[PairConfig] | None = None) -> VLConfig:
    return VLConfig(
        budgets=[BudgetConfig("USDC", Decimal("100000"))],
        pairs=pairs or [_pair("XSGD/USDC"), _pair("EURC/USDC")],
        fixed_bps=Decimal("50"),
        return_bps=Decimal("1"),
    )


def _market(symbol: str, base: str, quote: str) -> MarketInfo:
    return MarketInfo(
        symbol=symbol,
        base_symbol=base,
        quote_symbol=quote,
        base_address=f"0x{base.lower()}",
        quote_address=f"0x{quote.lower()}",
        base_decimals=6,
        quote_decimals=6,
        tick_precision=4,
        quantity_precision=2,
        price_step=Decimal("0.0001"),
        amount_step=Decimal("0.01"),
        min_bid_quote_amount=Decimal("0"),
        min_ask_amount=Decimal("0"),
    )


class _SequencedSource:
    name = "test-source"

    def __init__(
        self,
        rates: dict[tuple[str, str], list[str]],
        *,
        fail_first_quotes: int = 0,
        always_fail: set[tuple[str, str]] | None = None,
    ) -> None:
        self.rates = {
            pair: [Decimal(value) for value in values]
            for pair, values in rates.items()
        }
        self.calls: dict[tuple[str, str], int] = {}
        self.fail_first_quotes = fail_first_quotes
        self.always_fail = {
            (b.upper(), q.upper()) for b, q in (always_fail or set())
        }

    def quote(self, base: str, quote: str, *, amount=None) -> PriceObservation:
        if (base.upper(), quote.upper()) in self.always_fail:
            raise RuntimeError("source unavailable for pair")
        if self.fail_first_quotes > 0:
            self.fail_first_quotes -= 1
            raise RuntimeError("source unavailable")
        pair = (base.upper(), quote.upper())
        idx = self.calls.get(pair, 0)
        self.calls[pair] = idx + 1
        values = self.rates[pair]
        rate = values[min(idx, len(values) - 1)]
        return PriceObservation(
            source=self.name,
            pair=f"{pair[0]}/{pair[1]}",
            rate=rate,
            ts=time.time(),
        )


class _StopFlag:
    def __init__(self) -> None:
        self.requested = False

    def install(self) -> None:
        return None

    def request(self) -> None:
        self.requested = True

    def wait(self, _timeout: float) -> bool:
        return self.requested


class _FakeClient:
    vl_batch_min = 2
    vl_batch_max = 50

    def __init__(
        self,
        *,
        open_orders: list[dict] | None = None,
        fill_first_xsgd_bid: bool = False,
        cancel_ok: bool = True,
    ) -> None:
        self.markets_by_symbol = {
            "XSGD/USDC": _market("XSGD/USDC", "XSGD", "USDC"),
            "EURC/USDC": _market("EURC/USDC", "EURC", "USDC"),
        }
        self.open_orders = list(open_orders or [])
        self.fill_first_xsgd_bid = fill_first_xsgd_bid
        # When False, cancels report Sera's cooldown (return False, order stays).
        self.cancel_ok = cancel_ok
        self.events: list[tuple] = []
        self.active_orders: set[str] = set()
        self.batch_orders: dict[str, list[str]] = {}
        self.batch_places: list[dict] = []
        self.standalone_places: list[dict] = []
        self.fill_order_ids: set[str] = set()
        self.polled_fill_ids: set[str] = set()
        self._batch_count = 0
        self._order_count = 0
        self._uuid_int = 100

    def bootstrap(self) -> None:
        self.events.append(("bootstrap",))

    def get_config_limits(self) -> None:
        self.events.append(("limits",))

    def get_open_orders(self) -> list[dict]:
        self.events.append(("open_orders",))
        return list(self.open_orders)

    def expiration_from_server_time(self, order_ttl_seconds: int) -> int:
        self.events.append(("expiration", order_ttl_seconds))
        return 1_000_000 + len([
            event for event in self.events if event[0] == "expiration"
        ])

    def place_vl_batch(self, legs) -> VLBatchResult:
        self._batch_count += 1
        batch_id = f"batch-{self._batch_count}"
        records: list[OrderRecord] = []
        rows = []
        for idx, leg in enumerate(legs):
            order_id = f"{batch_id}-leg-{idx}"
            self._uuid_int += 1
            records.append(OrderRecord(order_id, self._uuid_int))
            self.active_orders.add(order_id)
            rows.append({
                "market": leg.market,
                "side": leg.side,
                "price": leg.price,
                "qty": leg.qty_base,
                "order_id": order_id,
            })
            if (
                self.fill_first_xsgd_bid
                and self._batch_count == 1
                and leg.market == "XSGD/USDC"
                and leg.side == "bid"
            ):
                self.fill_order_ids.add(order_id)
        self.batch_orders[batch_id] = [record.order_id for record in records]
        self.batch_places.append({"batch_id": batch_id, "legs": rows})
        self.events.append(("place_vl", batch_id))
        return VLBatchResult(
            vl_batch_id=batch_id,
            order_ids=[record.order_id for record in records],
            records=records,
            amendments=[],
            cancelled=[],
            fills=[],
            vl_group=None,
        )

    def place_order_previewed(
        self,
        market: str,
        side: str,
        qty_base: Decimal,
        price: Decimal,
        expiration: int,
    ) -> OrderRecord:
        self._order_count += 1
        self._uuid_int += 1
        order_id = f"solo-{self._order_count}"
        self.active_orders.add(order_id)
        self.standalone_places.append({
            "market": market,
            "side": side,
            "qty": qty_base,
            "price": price,
            "expiration": expiration,
            "order_id": order_id,
        })
        self.events.append(("place_order", order_id, market, side))
        return OrderRecord(order_id, self._uuid_int)

    def get_order_fills(self, order_id: str) -> list[dict]:
        self.events.append(("fills", order_id))
        if order_id in self.fill_order_ids and order_id not in self.polled_fill_ids:
            self.polled_fill_ids.add(order_id)
            return [{"quantity": "5", "price": "1.0"}]
        return []

    def cancel_vl_batch(self, vl_batch_id: str) -> bool:
        self.events.append(("cancel_vl", vl_batch_id))
        if not self.cancel_ok:
            return False
        for order_id in self.batch_orders.get(vl_batch_id, []):
            self.active_orders.discard(order_id)
        return True

    def cancel_order(self, order_id: str, uuid_int: int) -> bool:
        self.events.append(("cancel_order", order_id, uuid_int))
        if not self.cancel_ok:
            return False
        self.active_orders.discard(order_id)
        return True


def _wire_runner(monkeypatch, *, config: VLConfig, client: _FakeClient, source) -> None:
    monkeypatch.setattr(vr, "load_vl_config", lambda _path: config)
    monkeypatch.setattr(vr, "build_client", lambda **_kwargs: client)
    monkeypatch.setattr(vr, "load_price_reference_source", lambda _name: source)
    monkeypatch.setattr(vr, "load_token_to_iso", lambda: {
        "XSGD": "SGD",
        "EURC": "EUR",
        "USDC": "USD",
    })


def _stop_after_sleeps(monkeypatch, count: int) -> list[float]:
    stop = _StopFlag()
    sleeps: list[float] = []

    def fake_sleep(_started: float, poll_seconds: float, _stop=None) -> None:
        sleeps.append(poll_seconds)
        if len(sleeps) >= count:
            stop.requested = True

    monkeypatch.setattr(vr, "StopFlag", lambda: stop)
    monkeypatch.setattr(vr, "sleep_remaining", fake_sleep)
    return sleeps


def test_run_requotes_four_orders_and_tightens_return_side_after_fill(monkeypatch):
    client = _FakeClient(fill_first_xsgd_bid=True)
    source = _SequencedSource({
        ("SGD", "USD"): ["1.0000", "1.0100"],
        ("EUR", "USD"): ["2.0000", "2.0200"],
    })
    _wire_runner(monkeypatch, config=_config(), client=client, source=source)
    _stop_after_sleeps(monkeypatch, 2)

    result = vr.run(
        config_path="vl.toml",
        poll_seconds=305.0,
        min_requote_seconds=0.0,
        log_level="ERROR",
        state_path=":memory:",
    )

    assert result == 0
    assert len(client.active_orders) == 4
    assert len(client.batch_places) == 2
    assert len(client.standalone_places) == 4
    assert ("cancel_vl", "batch-1") in client.events

    xsgd_asks = [
        row for row in client.standalone_places
        if row["market"] == "XSGD/USDC" and row["side"] == "ask"
    ]
    assert [row["price"] for row in xsgd_asks] == [
        Decimal("1.0050"),
        Decimal("1.0102"),
    ]

    xsgd_bids = [
        leg for batch in client.batch_places for leg in batch["legs"]
        if leg["market"] == "XSGD/USDC" and leg["side"] == "bid"
    ]
    assert [leg["price"] for leg in xsgd_bids] == [
        Decimal("0.9950"),
        Decimal("1.0049"),
    ]


def test_run_skips_failed_tick_and_places_on_next_tick(monkeypatch):
    client = _FakeClient()
    source = _SequencedSource(
        {
            ("SGD", "USD"): ["1.0000"],
            ("EUR", "USD"): ["2.0000"],
        },
        # Per-pair isolation means a full tick-skip needs both pairs to fail.
        fail_first_quotes=2,
    )
    _wire_runner(monkeypatch, config=_config(), client=client, source=source)
    sleeps = _stop_after_sleeps(monkeypatch, 2)

    result = vr.run(
        config_path="vl.toml",
        poll_seconds=305.0,
        min_requote_seconds=0.0,
        log_level="ERROR",
        state_path=":memory:",
    )

    assert result == 0
    assert sleeps == [305.0, 305.0]
    assert len(client.batch_places) == 1
    assert len(client.standalone_places) == 2
    assert len(client.active_orders) == 4


def test_run_once_places_quote_set_and_returns_zero(monkeypatch):
    # The fire-once scheduler path: one full reattach-cancel-place cycle, exit 0.
    client = _FakeClient()
    source = _SequencedSource({
        ("SGD", "USD"): ["1.0000"],
        ("EUR", "USD"): ["2.0000"],
    })
    _wire_runner(monkeypatch, config=_config(), client=client, source=source)
    monkeypatch.setattr(vr, "StopFlag", _StopFlag)

    result = vr.run(
        config_path="vl.toml",
        once=True,
        min_requote_seconds=0.0,
        log_level="ERROR",
        state_path=":memory:",
    )

    assert result == 0
    assert len(client.active_orders) == 4


def test_run_once_does_not_block_on_boot_cancel_cooldown(monkeypatch):
    # A scheduled fire-once run must never hang on Sera's cancel cooldown: the
    # boot cancel does a single pass (no multi-minute wait) in --once mode.
    client = _FakeClient(
        open_orders=[{
            "symbol": "XSGD/USDC",
            "side": "bid",
            "order_id": "old-order",
            "uuid_int": "42",
            "created_at": "2026-01-01T00:00:00Z",
        }],
        cancel_ok=False,
    )
    source = _SequencedSource({("SGD", "USD"): ["1.0000"]})
    _wire_runner(
        monkeypatch,
        config=_config(pairs=[_pair("XSGD/USDC")]),
        client=client,
        source=source,
    )
    monkeypatch.setattr(vr, "StopFlag", _StopFlag)
    sleeps: list[float] = []
    monkeypatch.setattr(vr.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = vr.run(
        config_path="vl.toml",
        once=True,
        min_requote_seconds=0.0,
        log_level="ERROR",
        state_path=":memory:",
    )

    # Boot cancel hit cooldown, so this fire could not requote and reports 1 —
    # but it returned promptly without the 300s boot-cooldown wait.
    assert result == 1
    assert all(seconds < 100 for seconds in sleeps)


def test_run_isolates_failing_pair_and_quotes_healthy_pair(monkeypatch):
    # XSGD's reference source always fails; EURC's works. The failing pair must
    # not sideline quoting for the healthy pair.
    client = _FakeClient()
    source = _SequencedSource(
        {("EUR", "USD"): ["2.0000"]},
        always_fail={("SGD", "USD")},
    )
    _wire_runner(monkeypatch, config=_config(), client=client, source=source)
    _stop_after_sleeps(monkeypatch, 1)

    result = vr.run(
        config_path="vl.toml",
        poll_seconds=305.0,
        min_requote_seconds=0.0,
        log_level="ERROR",
        state_path=":memory:",
    )

    assert result == 0
    # Only EURC produced intents (bid spends USDC, ask spends EURC) — both
    # singletons, so two standalone placements and no XSGD orders at all.
    assert len(client.standalone_places) == 2
    assert client.batch_places == []
    assert {row["market"] for row in client.standalone_places} == {"EURC/USDC"}


def test_run_auto_update_cleans_up_live_orders_and_restarts(monkeypatch):
    client = _FakeClient(open_orders=[{
        "symbol": "XSGD/USDC",
        "side": "bid",
        "order_id": "old-order",
        "uuid_int": "42",
        "created_at": "2026-01-01T00:00:00Z",
    }])
    source = _SequencedSource({("SGD", "USD"): ["1.0000"]})
    _wire_runner(
        monkeypatch,
        config=_config(pairs=[_pair("XSGD/USDC")]),
        client=client,
        source=source,
    )
    monkeypatch.setattr(vr, "StopFlag", _StopFlag)

    class UpdatedOnce:
        def __init__(self, *, interval_seconds: float) -> None:
            self.interval_seconds = interval_seconds

        def run_if_due(self, _log):
            return GitUpdateResult(status="updated", message="pulled")

    restarts: list[bool] = []
    monkeypatch.setattr(vr, "DailyGitUpdater", UpdatedOnce)
    monkeypatch.setattr(vr, "restart_current_process", lambda: restarts.append(True))

    result = vr.run(
        config_path="vl.toml",
        auto_update=True,
        cancel_on_exit=True,
        log_level="ERROR",
        state_path=":memory:",
    )

    assert result == 0
    assert restarts == [True]
    assert ("cancel_order", "old-order", 42) in client.events
    assert client.batch_places == []
    assert client.standalone_places == []
