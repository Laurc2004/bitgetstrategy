from dataclasses import dataclass
import math
import pandas as pd


@dataclass(frozen=True)
class Quote:
    timestamp: pd.Timestamp
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    mark: float
    source: str = "quote"

    def valid(self):
        values = (self.bid, self.ask, self.bid_size, self.ask_size, self.mark)
        return (all(math.isfinite(v) for v in values) and 0 < self.bid <= self.ask
                and self.mark > 0 and self.bid_size >= 0 and self.ask_size >= 0)


@dataclass(frozen=True)
class Fill:
    timestamp: pd.Timestamp
    leg: str
    quantity: float  # signed shares: buy positive, sell negative
    price: float
    fee: float
    slippage_cost: float
    reason: str


@dataclass
class Goal:
    created: pd.Timestamp
    spot_target: float
    perp_target: float
    reason: str

    @property
    def opening(self):
        return self.spot_target > 0
