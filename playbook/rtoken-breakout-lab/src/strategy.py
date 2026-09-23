"""Nautilus strategy: rToken Breakout Lab (4h bars, hold_level confirmation).

Faithful 4h-bar expression of the v3 frozen rules:
  - enter: close breaks prior `window`-bar high (shifted), confirmed by
    `confirmation_bars` consecutive closes holding above the ORIGINAL
    breakout anchor level
  - leave: close below prior `window`-bar low (channel exit)
  - sizing: fixed quote budget per entry (vol-scaling lives in live sizing)
"""
from decimal import Decimal
from typing import Optional

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy


class RtokenBreakoutConfig(StrategyConfig):
    instrument_ids: tuple[InstrumentId, ...] = ()
    bar_types: tuple[BarType, ...] = ()
    window: int = 18
    confirmation_bars: int = 2
    quote_budget: str = "1000"


class RtokenBreakoutStrategy(Strategy):
    def __init__(self, config: RtokenBreakoutConfig) -> None:
        super().__init__(config)
        self.cfg = config
        self._closes: dict[InstrumentId, list[float]] = {}
        self._highs: dict[InstrumentId, list[float]] = {}
        self._lows: dict[InstrumentId, list[float]] = {}
        self._instruments: dict[InstrumentId, Instrument] = {}
        self._anchor: dict[InstrumentId, float] = {}
        self._anchor_age: dict[InstrumentId, int] = {}

    def on_start(self) -> None:
        for bt in self.cfg.bar_types:
            self.subscribe_bars(bt)
        for iid in self.cfg.instrument_ids:
            self._instruments[iid] = self.cache.instrument(iid)
            self._closes[iid] = []
            self._highs[iid] = []
            self._lows[iid] = []

    def on_bar(self, bar: Bar) -> None:
        iid = bar.bar_type.instrument_id
        self._closes[iid].append(float(bar.close))
        self._highs[iid].append(float(bar.high))
        self._lows[iid].append(float(bar.low))

        w = self.cfg.window
        n = len(self._closes[iid])
        if n < w + 2:
            return

        closes, highs, lows = self._closes[iid], self._highs[iid], self._lows[iid]
        last = n - 1
        prior_high = max(highs[last - w:last])
        prior_low = min(lows[last - w:last])

        # track the anchor: highest breakout level currently being confirmed
        if closes[last] > prior_high:
            self._anchor[iid] = prior_high
            self._anchor_age[iid] = 0
        else:
            self._anchor_age[iid] = self._anchor_age.get(iid, 0) + 1

        anchor = self._anchor.get(iid)
        c = self.cfg.confirmation_bars

        # entry: anchor exists, this bar is within confirmation window and holds above it
        if (anchor is not None and 0 <= self._anchor_age[iid] < c
                and closes[last] > anchor and not self._position_open(iid)):
            qty = self._qty_for_budget(iid, Decimal(self.cfg.quote_budget))
            if qty is not None and qty > 0:
                self.submit_order(self.order_factory.market(
                    instrument_id=iid, order_side=OrderSide.BUY,
                    quantity=qty, time_in_force=TimeInForce.GTC))
        if self._anchor_age.get(iid, 0) >= c:
            self._anchor.pop(iid, None)

        # exit: channel break
        if closes[last] < prior_low and self._position_open(iid):
            for pos in self.cache.positions_open(instrument_id=iid):
                self.submit_order(self.order_factory.market(
                    instrument_id=iid, order_side=OrderSide.SELL,
                    quantity=pos.quantity, time_in_force=TimeInForce.GTC))

    def _position_open(self, iid: InstrumentId) -> bool:
        return len(self.cache.positions_open(instrument_id=iid)) > 0

    def _qty_for_budget(self, iid: InstrumentId, budget: Decimal) -> Optional[Quantity]:
        inst = self._instruments.get(iid)
        if inst is None or not self._closes[iid]:
            return None
        px = Decimal(str(self._closes[iid][-1]))
        if px <= 0:
            return None
        raw = budget / px
        return Quantity(raw.quantize(inst.size_precision), inst.size_precision)

    def on_stop(self) -> None:
        for iid in self._instruments:
            self.cancel_all_orders(iid)
            self.close_all_positions(iid)
