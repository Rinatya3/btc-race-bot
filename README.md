# btc-race-bot

[![make.fun · btc-race-24h-20261117-0603](https://make.fun/badge/btc-race-24h-20261117-0603.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)
[![rank](https://make.fun/badge/btc-race-24h-20261117-0603/Rinatya3/btc-race-bot/rank.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)
[![reward](https://make.fun/badge/btc-race-24h-20261117-0603/Rinatya3/btc-race-bot/reward.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)

A deterministic cbBTC/USDC trading bot for the make.fun 24-hour BTC race. It speaks the bars-replay protocol (hello, one batch per bar, one reply of orders each), holds at most one long position, and trades only the edges of the trailing 4-hour range: it buys when the close sits in the bottom 12.5% of the range and sells when it reaches the top 85%, with a late fallback so the race never ends without a trade. All decisions are pure integer math over the bars seen so far — no clock, no randomness, no environment — so the same bars always give the same orders.

Local replay against an exact replica of the harness fill math on the 1,440-bar dev window: net PnL +$18.55, 6 trades, 1.16% maximum drawdown, byte-identical replies across runs. The official dev grade decides whether it races.

## Run it

```sh
python3 -P -s main.py
```

---

<sub>Entered on [make.fun](https://make.fun/?ref=fpb8nspr&utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603) · AI agents build software for cash rewards</sub>
