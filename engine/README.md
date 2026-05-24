# Engine

Shared code for all four stock systems will live here.

Planned modules:

- `data/`: market data providers.
- `factors/`: market-independent factor calculations.
- `scoring/`: shared scoring logic.
- `analyzer/`: deterministic analysis rules.
- `backtest/`: rank and execution backtests.

`A-EGS/egs_main.py` remains in place until Phase 7 modularization.
