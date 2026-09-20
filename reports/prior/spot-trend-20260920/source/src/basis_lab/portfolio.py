from dataclasses import dataclass
from .models import Fill


@dataclass
class Position:
    quantity: float = 0.0
    average: float = 0.0
    realized: float = 0.0

    def trade(self, quantity: float, price: float):
        old = self.quantity
        realized = 0.0
        if old == 0 or old * quantity > 0:
            self.average = (abs(old) * self.average + abs(quantity) * price) / abs(old + quantity)
        else:
            closed = min(abs(old), abs(quantity))
            realized = closed * (price - self.average) * (1 if old > 0 else -1)
            if abs(quantity) > abs(old):
                self.average = price
        self.quantity += quantity
        if abs(self.quantity) < 1e-9:
            self.quantity = self.average = 0.0
        self.realized += realized
        return realized

    def unrealized(self, mark: float):
        return self.quantity * (mark - self.average)


class Portfolio:
    def __init__(self, initial_cash: float):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.spot = Position()
        self.perp = Position()
        self.fees = 0.0
        self.funding = 0.0
        self.slippage_cost = 0.0

    def apply_fill(self, fill: Fill):
        if fill.leg == "spot":
            if self.spot.quantity + fill.quantity < -1e-8:
                raise ValueError("Spot borrowing/shorting is unsupported")
            self.spot.trade(fill.quantity, fill.price)
            self.cash -= fill.quantity * fill.price
        elif fill.leg == "perp":
            self.cash += self.perp.trade(fill.quantity, fill.price)
        else:
            raise ValueError(fill.leg)
        self.cash -= fill.fee
        self.fees += fill.fee
        self.slippage_cost += fill.slippage_cost  # attribution only; already in fill price

    def settle_funding(self, rate: float, mark: float):
        # Positive funding: shorts receive, longs pay. Signed quantity is essential.
        payment = -self.perp.quantity * mark * rate
        self.cash += payment
        self.funding += payment
        return payment

    def equity(self, spot_mark: float, perp_mark: float):
        return self.cash + self.spot.quantity * spot_mark + self.perp.unrealized(perp_mark)

    def collateral(self, perp_mark: float):
        # No assumed collateral credit for tokenized spot holdings.
        return self.cash + self.perp.unrealized(perp_mark)

    @property
    def flat(self):
        return self.spot.quantity == 0 and self.perp.quantity == 0
