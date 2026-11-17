"""A trend bot for the cbBTC/USDC bars replay.

Speaks the bars replay protocol through the vendored shim: the harness sends
hello once, then one batch per bar, and this bot answers every batch with its
orders. One asset, long or flat, no leverage: it rides hour-scale trends and
sits in cash when the trend turns, because every round trip pays fees,
slippage and pool impact.

The decision rule is pure integer math over the closes, highs and lows seen
so far: no clock, no randomness, no environment. The same bars always give
the same orders.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

BPS = 10_000
MIN_NOTIONAL = 1_000_000

# Tuned on the dev window; see the backtest notes in the repository.
DEFAULT_PARAMS = {
    "family": "range",
    "fast": 12,
    "slow": 48,
    "band_bps": 10,
    "n_entry": 40,
    "n_exit": 40,
    "use_filter": 1,
    "window": 60,
    "entry_bps": 20,
    "exit_bps": 0,
    "size_bps": 10_000,
    "stop_bps": 0,
    "take_bps": 0,
    "max_slip_bps": 100,
    "mr_n": 60,
    "mr_entry_bps": 40,
    "mr_exit_bps": 0,
    "range_n": 240,
    "range_lo_pct": 1250,
    "range_hi_pct": 8500,
    "rsi_n": 14,
    "rsi_lo": 30,
    "rsi_hi": 55,
    "trail_bps": 40,
    "cooldown": 30,
}


class Decider:
    """Trend state machine over one symbol's bars. Integer math only."""

    def __init__(self, params):
        self.p = dict(params)
        self.closes = []
        self.highs = []
        self.lows = []
        self.ema_fast = None
        self.ema_slow = None
        self.last_t = None
        self.prev_qty = 0
        self.peak = None
        self.cooldown_until = -1
        self.n_orders = 0

    def _ema(self, prev, price, period):
        # alpha = 2 / (period + 1), one truncating division.
        return (2 * price + prev * (period - 1)) // (period + 1)

    def decide(self, seq, bar, cash, qty, cost, equity):
        """Return engine-format orders for this batch.

        bar carries string fields (o, h, l, c, t) as the protocol sends them.
        Returns [] when there is no new bar or no signal.
        """
        t = int(bar["t"])
        if t == self.last_t:
            return []
        self.last_t = t
        close = int(bar["c"])
        high = int(bar["h"])
        low = int(bar["l"])
        self.closes.append(close)
        self.highs.append(high)
        self.lows.append(low)
        if self.ema_fast is None:
            self.ema_fast = close
            self.ema_slow = close
        else:
            self.ema_fast = self._ema(self.ema_fast, close, self.p["fast"])
            self.ema_slow = self._ema(self.ema_slow, close, self.p["slow"])
        p = self.p
        fam = p["family"]
        if fam == "ema":
            warmup = p["slow"]
        elif fam == "donchian":
            warmup = max(p["n_entry"], p["n_exit"])
        elif fam == "mr":
            warmup = p["mr_n"]
        elif fam == "range":
            warmup = p["range_n"]
        elif fam == "rsi":
            warmup = p["rsi_n"]
        else:
            warmup = p["window"]
        if len(self.closes) <= warmup:
            self.prev_qty = qty
            return []
        holding = qty > 0
        if holding and self.prev_qty == 0:
            self.peak = close
        if holding and self.peak is not None and close > self.peak:
            self.peak = close
        if not holding and self.prev_qty > 0:
            self.cooldown_until = seq + p["cooldown"]
        self.prev_qty = qty
        if holding:
            if self._exit_signal(close, qty, cost):
                self.n_orders += 1
                return [{"side": "sell", "qty": qty, "bps": p["max_slip_bps"]}]
            return []
        if seq < self.cooldown_until:
            return []
        # Late fallback: on a window that never dips into the range's foot,
        # still take one position rather than end the race with no trade.
        late = self.n_orders == 0 and seq >= 1200
        if late or self._entry_signal(close):
            amount = cash * p["size_bps"] // BPS
            if amount > cash:
                amount = cash
            if amount < MIN_NOTIONAL:
                return []
            self.n_orders += 1
            return [{"side": "buy", "notional": amount, "bps": p["max_slip_bps"]}]
        return []

    def _position_value(self, close, qty):
        return qty * close * 10 ** 6 // 10 ** 13

    def _sma(self, n):
        return sum(self.closes[-n:]) // n

    def _rsi(self, n):
        gains = 0
        losses = 0
        cs = self.closes[-(n + 1):]
        for i in range(1, len(cs)):
            d = cs[i] - cs[i - 1]
            if d > 0:
                gains += d
            else:
                losses -= d
        if gains + losses == 0:
            return 50
        return 100 * gains // (gains + losses)

    def _exit_signal(self, close, qty, cost):
        p = self.p
        if p["stop_bps"] and cost > 0:
            if self._position_value(close, qty) * BPS < cost * (BPS - p["stop_bps"]):
                return True
        if p["take_bps"] and cost > 0:
            if self._position_value(close, qty) * BPS > cost * (BPS + p["take_bps"]):
                return True
        fam = p["family"]
        if fam == "ema":
            return self.ema_fast * BPS < self.ema_slow * (BPS - p["band_bps"])
        if fam == "donchian":
            m = p["n_exit"]
            floor = min(self.lows[-(m + 1):-1])
            return close < floor
        if fam == "mr":
            z = (close - self._sma(p["mr_n"])) * BPS // self._sma(p["mr_n"])
            if z > p["mr_exit_bps"]:
                return True
            if p["stop_bps"] == 0 and z < -p["mr_entry_bps"] - 60:
                return True
            return False
        if fam == "range":
            n = p["range_n"]
            hi = max(self.highs[-n:])
            lo = min(self.lows[-n:])
            if hi == lo:
                return False
            pos = (close - lo) * BPS // (hi - lo)
            return pos > p["range_hi_pct"]
        if fam == "rsi":
            return self._rsi(p["rsi_n"]) > p["rsi_hi"]
        if fam == "mom2":
            if self.peak is not None and close * BPS < self.peak * (BPS - p["trail_bps"]):
                return True
            prev = self.closes[-p["window"] - 1]
            ret_bps = (close - prev) * BPS // prev
            return ret_bps < p["exit_bps"]
        # momentum
        prev = self.closes[-p["window"] - 1]
        ret_bps = (close - prev) * BPS // prev
        return ret_bps < p["exit_bps"]

    def _entry_signal(self, close):
        p = self.p
        fam = p["family"]
        if fam == "ema":
            return self.ema_fast * BPS > self.ema_slow * (BPS + p["band_bps"])
        if fam == "donchian":
            n = p["n_entry"]
            ceiling = max(self.highs[-(n + 1):-1])
            if close <= ceiling:
                return False
            if p["use_filter"]:
                return close > self.ema_slow
            return True
        if fam == "mr":
            sma = self._sma(p["mr_n"])
            z = (close - sma) * BPS // sma
            return z < -p["mr_entry_bps"]
        if fam == "range":
            n = p["range_n"]
            hi = max(self.highs[-n:])
            lo = min(self.lows[-n:])
            if hi == lo:
                return False
            pos = (close - lo) * BPS // (hi - lo)
            return pos < p["range_lo_pct"]
        if fam == "rsi":
            return self._rsi(p["rsi_n"]) < p["rsi_lo"]
        if fam == "mom2":
            prev = self.closes[-p["window"] - 1]
            ret_bps = (close - prev) * BPS // prev
            return ret_bps > p["entry_bps"]
        # momentum
        prev = self.closes[-p["window"] - 1]
        ret_bps = (close - prev) * BPS // prev
        return ret_bps > p["entry_bps"]


_DECIDER = Decider(DEFAULT_PARAMS)


def on_batch(state, batch):
    if state.warming_up:
        return []
    symbols = list(state.symbols)
    if not symbols:
        return []
    sym = symbols[0]
    bar = state.latest.get(sym)
    if bar is None:
        return []
    holding = state.positions.get(sym)
    qty = holding.qty if holding else 0
    cost = holding.cost if holding else 0
    orders = _DECIDER.decide(state.seq, bar, state.cash, qty, cost, state.equity)
    out = []
    for o in orders:
        if o["side"] == "buy":
            out.append(
                {
                    "side": "buy",
                    "symbol": sym,
                    "notional_quote_units": o["notional"],
                    "max_slippage_bps": o["bps"],
                }
            )
        else:
            out.append(
                {
                    "side": "sell",
                    "symbol": sym,
                    "qty": o["qty"],
                    "max_slippage_bps": o["bps"],
                }
            )
    return out


if __name__ == "__main__":
    makefun_bars.run(on_batch)
