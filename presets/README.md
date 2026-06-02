# Presets

Market and horizon specific configuration lives here.

- `a_short.yaml`: A-share short-term system.
- `us_short.yaml`: US short-term system.
- `a_long.yaml`: A-share long-term system.
- `us_long.yaml`: US long-term system.
- `a_short_screening_threshold_governance_20260602.json`: reviewed A-short screening threshold parity artifact mirrored from current `A-EGS/egs_main.py::CONF`.

Shared logic must stay in `engine/`; thresholds and market-cycle settings belong in these preset files.
