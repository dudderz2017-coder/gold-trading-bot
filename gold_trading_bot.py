from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, List, Optional


@dataclass
class Candle:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class Position:
    side: str
    size: float
    entry_price: float
    timestamp: str


@dataclass
class Trade:
    side: str
    size: float
    price: float
    timestamp: str


class GoldStrategy:
    def __init__(self, fast_period: int = 10, slow_period: int = 30, threshold: float = 0.02):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.threshold = threshold

    @staticmethod
    def sma(values: List[float], period: int) -> List[float]:
        result: List[float] = []
        for i in range(len(values)):
            if i + 1 < period:
                result.append(float("nan"))
            else:
                window = values[i - period + 1 : i + 1]
                result.append(sum(window) / period)
        return result

    @staticmethod
    def percent_change(current: float, prev: float) -> float:
        if prev == 0:
            return 0.0
        return (current - prev) / prev

    def generate_signal(self, candles: List[Candle]) -> str:
        closes = [c.close for c in candles]
        if len(closes) < max(self.fast_period, self.slow_period):
            return "HOLD"

        fast = self.sma(closes, self.fast_period)
        slow = self.sma(closes, self.slow_period)

        current_fast = fast[-1]
        current_slow = slow[-1]
        prev_fast = fast[-2] if len(fast) > 1 else current_fast
        prev_slow = slow[-2] if len(slow) > 1 else current_slow

        trend_strength = self.percent_change(current_fast, prev_fast) - self.percent_change(current_slow, prev_slow)

        if current_fast > current_slow and trend_strength > self.threshold:
            return "BUY"
        if current_fast < current_slow and trend_strength < -self.threshold:
            return "SELL"
        return "HOLD"


class Backtester:
    def __init__(self, initial_balance: float = 100000.0, risk_per_trade: float = 0.02):
        self.initial_balance = initial_balance
        self.cash = initial_balance
        self.position: Optional[Position] = None
        self.trades: List[Trade] = []
        self.equity_curve: List[float] = []
        self.risk_per_trade = risk_per_trade

    def _execute_trade(self, candle: Candle, side: str, size: float) -> float:
        price = candle.close
        if side == "BUY":
            cost = price * size
            if cost > self.cash:
                size = self.cash / max(price, 1e-9)
                cost = price * size
            self.cash -= cost
            self.position = Position(side="LONG", size=size, entry_price=price, timestamp=candle.timestamp)
            self.trades.append(Trade(side="BUY", size=size, price=price, timestamp=candle.timestamp))
            return size
        if side == "SELL":
            if self.position is None:
                return 0.0
            close_size = min(size, self.position.size)
            proceeds = price * close_size
            self.cash += proceeds
            self.trades.append(Trade(side="SELL", size=close_size, price=price, timestamp=candle.timestamp))
            self.position = None
            return close_size
        return 0.0

    def run(self, candles: List[Candle], strategy: GoldStrategy):
        self.equity_curve = []
        for idx, candle in enumerate(candles):
            if idx < max(strategy.fast_period, strategy.slow_period):
                continue

            signal = strategy.generate_signal(candles[: idx + 1])

            if signal == "BUY" and self.position is None:
                allowed_risk = self.cash * self.risk_per_trade
                unit_size = allowed_risk / max(candle.close, 1e-9)
                self._execute_trade(candle, "BUY", unit_size)

            elif signal == "SELL" and self.position is not None:
                self._execute_trade(candle, "SELL", self.position.size)

            nav = self.cash + (self.position.size * candle.close if self.position else 0.0)
            self.equity_curve.append(nav)

        final_nav = self.cash + (self.position.size * candles[-1].close if self.position else 0.0)
        return {
            "initial_balance": self.initial_balance,
            "final_balance": final_nav,
            "net_return": (final_nav - self.initial_balance) / self.initial_balance,
            "trades": len(self.trades),
            "position": self.position,
        }


def load_candles(csv_path: str) -> List[Candle]:
    candles: List[Candle] = []
    with open(csv_path, newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            candles.append(
                Candle(
                    timestamp=row.get("timestamp", ""),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume", 0.0) or 0.0),
                )
            )
    return candles


def main():
    parser = argparse.ArgumentParser(description="Gold trading bot backtest")
    parser.add_argument("--data", default="data/gold_prices.csv", help="CSV path with OHLCV gold data")
    parser.add_argument("--fast", type=int, default=10, help="Fast SMA period")
    parser.add_argument("--slow", type=int, default=30, help="Slow SMA period")
    parser.add_argument("--threshold", type=float, default=0.02, help="Trend threshold")
    parser.add_argument("--initial-balance", type=float, default=100000.0)
    args = parser.parse_args()

    candles = load_candles(args.data)
    if not candles:
        raise ValueError(f"No candle data found in {args.data}")

    strategy = GoldStrategy(fast_period=args.fast, slow_period=args.slow, threshold=args.threshold)
    backtester = Backtester(initial_balance=args.initial_balance)
    result = backtester.run(candles, strategy)

    print(json.dumps({
        "initial_balance": result["initial_balance"],
        "final_balance": round(result["final_balance"], 2),
        "net_return": round(result["net_return"], 4),
        "num_trades": result["trades"],
        "position": None if result["position"] is None else asdict(result["position"]),
    }, indent=2))


if __name__ == "__main__":
    main()
