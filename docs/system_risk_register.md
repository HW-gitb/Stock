# System Risk Register

Status: Active

Owner role: tracked queue for material security, data, PIT, schema, execution, and cross-LLM process risks that are not fixed immediately in the same reviewed slice.

This file exists to prevent audit findings from living only in chat. `docs/SESSION_LOG.md` records reasoning and review verdicts; this register records the durable open-risk queue. Do not use it as authorization to batch-fix everything at once. Each fix still follows `docs/AI_REVIEW_PROTOCOL.md`.

## Enforcement Rules

- Every material review or audit finding that affects data integrity, PIT safety, schema contract, execution simulation, security, ship-gate evidence, or cross-LLM continuity must be either fixed in the same reviewed slice or entered here before the round ends.
- `执行` must check this register before choosing the next task. Open P0 items outrank normal roadmap work unless the user explicitly approves a narrower override.
- `审查` must verify that new material findings were either fixed or registered here, and that resolved entries include concrete verification.
- `修复` may update this register only for approved Required fixes or Optional dispositions being handled in that repair round.
- A risk entry is not closed by intent. Closure requires file / test evidence and a reviewed commit or an explicit accepted-risk decision from the user.

## Status And Severity

Severity:
- P0: blocks the next unsafe execution path or can contaminate evidence / official outputs.
- P1: high risk before broader implementation, provider work, long-lane work, or production-like use.
- P2: medium risk; must be queued and fixed before the affected subsystem is promoted.
- P3: low risk or documentation hygiene.

Status:
- `open`: accepted for tracking; not fixed.
- `in_progress`: current reviewed change is addressing it.
- `blocked`: needs user decision or external dependency.
- `resolved`: fixed and verified.
- `accepted_risk`: user explicitly accepted the residual risk.
- `needs_revalidation`: audit claim is plausible enough to track, but line-level repo validation is still required before implementation.

## Hot Queue

1. `SR-EXEC-001` - Add a weekly screening PIT interlock before any historical `-AsOf` official-output run.
2. `SR-MEASURE-001` - Implement same-anchor benchmark excess with benchmark T+1 open for corrected A-share burst revalidation.
3. `SR-SEC-001` - Remove or narrow broad local Claude Bash allow rules before relying on Claude-side automation.
4. `SR-PIT-001` + `SR-CONTRACT-001` - Strengthen `analysis_input` PIT contract and make producer / consumer schema validation real.
5. `SR-EXEC-002` - Revalidate and queue execution-backtest risk-control limitations from audit #1.

## Entries

### SR-META-001 - Audit findings were not durably tracked

- Severity: P0
- Status: in_progress
- Owner phase: process / cross-LLM workflow
- Evidence: before this register, repo routing had `CURRENT.md` and `SESSION_LOG.md` entries for measurement-basis only; no tracked vulnerability / risk ledger existed.
- Accepted calibration: measurement-basis lock was necessary but did not capture the wider audit backlog.
- Required next action: keep this file routed from `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, and `docs/AI_REVIEW_PROTOCOL.md`; close only after Claude Pass and commit for the register-introduction change.

### SR-MEASURE-001 - Benchmark excess entry-anchor mismatch

- Severity: P0
- Status: open
- Owner phase: alpha measurement integrity / A-share burst research
- Evidence: current A-share burst preregistration is `BLOCKED_DO_NOT_RUN`; `docs/ALPHA_VALIDATION_ACTION_GUIDE.md` requires stock T+1 open and benchmark T+1 open to the same exit close.
- Accepted calibration: old 5d `excess_csi1000` is measurement-contaminated / uncorrected, not proven false.
- Required next action: extend benchmark materializer / forward-daily benchmark fetch to request, persist, validate, and use CSI1000 / CSI300 index open; corrected 5d CSI1000 is the only primary revalidation.

### SR-EXEC-001 - Historical weekly screening can contaminate official outputs

- Severity: P0
- Status: open
- Owner phase: A-short operation / Phase 6b maintenance
- Evidence: `runners/weekly_screening.ps1` calls `A-EGS/egs_main.py --as-of $AsOf` without `--l3-mode`; `A-EGS/egs_main.py` defaults `--l3-mode` to `today` and writes official `result/a_short/<trade_date>/` outputs by default.
- Accepted calibration: `pit` lookup itself uses the effective as-of date after `set_asof`; the risk is the weekly script defaulting to `today` for historical `-AsOf` and allowing official-output overwrite.
- Required next action: for `-AsOf` not equal to the current run date, require explicit PIT / neutralize mode and refuse to overwrite an existing official result directory unless the user explicitly approves a reviewed override.

### SR-PIT-001 - PIT invariants are not enforceable in the root input contract

- Severity: P1
- Status: open
- Owner phase: Phase 7c DataHub / report contract precondition; long-lane blocker
- Evidence: `schemas/analysis_input.schema.json` has `trade_date` and L3 metadata but cannot express `ann_date <= trade_date` for fundamentals, cannot compare `source.l3_snapshot_date <= trade_date`, and does not require PIT snapshot presence when `source.l3_mode = pit`.
- Accepted calibration: `A-EGS/egs_main.py` currently filters `fina_indicator.ann_date <= TODAY_DT`; the risk is contract-level non-enforcement and future producer regression, not proof of current look-ahead.
- Required next action: introduce an `analysis_input` contract revision or adjunct validation that can express PIT dates for fundamentals / L3 and reject future-dated or missing PIT metadata where required.

### SR-CONTRACT-001 - Producer and consumer do not validate `analysis_input` against schema

- Severity: P1
- Status: open
- Owner phase: Phase 1 / Phase 4 contract hardening
- Evidence: `A-EGS/egs_main.py` writes `analysis_input.json` without jsonschema validation; `runners/run_analysis_report.py` loads `analysis_input` and validates only its own output report.
- Accepted calibration: `build_data_health` performs some bespoke checks, but it is not equivalent to schema validation at producer and consumer boundaries.
- Required next action: add shared schema validation for `analysis_input` on write and read, with tests covering malformed payload rejection.

### SR-SEC-001 - Broad local Claude Bash allow rules

- Severity: P1
- Status: open
- Owner phase: local AI tooling security
- Evidence: root `.claude/settings.local.json` allows broad `Bash(python *)`; `A-EGS/.claude/settings.local.json` allows `Bash(python -c ' *)`. These files are local and currently untracked.
- Accepted calibration: this is local automation exposure, not repository business-code behavior.
- Required next action: narrow allow rules to concrete project scripts or remove them from local Claude settings; record the local change in `SESSION_LOG.md` if it affects review/execution behavior.

### SR-EXEC-002 - Execution backtest risk-control limitations need a tracked fix path

- Severity: P1
- Status: needs_revalidation
- Owner phase: Phase 5 / Phase 8 monitoring and ship-gate readiness
- Evidence: audit #1 reported execution-backtest drawdown underestimation, unimplemented cooldown / circuit-breaker / concurrency limits, and capital-ceiling enforcement gaps.
- Accepted calibration: some limitations may already be documented in execution reports; before fixing, re-read `runners/backtest_execution.py`, related schemas, and tests to separate real defects from already-disclosed scope limits.
- Required next action: create line-level findings and either fix or explicitly document each as a blocking limitation before any execution evidence is used for ship-gate-like conclusions.

### SR-GOV-001 - A-short screening thresholds are not governed by preset schema

- Severity: P2
- Status: open
- Owner phase: A-short screening governance
- Evidence: `presets/a_short.yaml` is a capital / routing preset and still says detailed thresholds will be filled later; many live screening thresholds live in `A-EGS/egs_main.py` `CONF` and scoring code.
- Accepted calibration: `backtest_execution.py` does read `presets/a_short.yaml` for capital profile, so the issue is screening-threshold governance, not total preset non-use.
- Required next action: move production-relevant A-short thresholds into a governed preset contract or add tests that assert docs / preset / code parity.

### SR-SKILL-001 - US-short reference docs are copy-paste runtime prompt shaped

- Severity: P2
- Status: open
- Owner phase: US-short Skill / reference hygiene
- Evidence: `skills/us_short_analysis/reference/us_short_analysis_spec.md` and `us_short_screening_spec.md` start with imperative persona / execution instructions, while `skills/us_short_analysis/SKILL.md` is reserved for Phase 8.
- Accepted calibration: the reserved `SKILL.md` prevents normal Skill invocation, but it does not prevent a future LLM from pasting reference material directly into a chat.
- Required next action: add a clear banner to US-short reference docs: design reference only, not a runtime prompt, no operation advice / sizing without schema-first implementation and ship-gate evidence.

### SR-LLM-001 - Web-news policy-risk prompt injection surface

- Severity: P2
- Status: open
- Owner phase: A-short Stage 3 LLM policy-risk check
- Evidence: `A-EGS/egs_main.py` builds a DeepSeek prompt by embedding raw Sina / Baidu news titles into user content.
- Accepted calibration: bounded impact; it can flip a policy-risk veto but does not directly create broker action or automatic buying.
- Required next action: sanitize / delimit external titles and add an instruction boundary test, or replace the LLM call with deterministic keyword / source scoring for this veto.

### SR-CANARY-001 - Data canary status is advisory but can be overread

- Severity: P2
- Status: open
- Owner phase: Phase 2.6 data lineage / weekly operation
- Evidence: `runners/data_canary.py` intentionally returns exit 0 for drift / missing / fetch errors; `runners/weekly_screening.ps1` treats canary as bypass and exits with the EGS code.
- Accepted calibration: bypass behavior is intentional; the risk is naming / documentation causing future LLMs to treat "pipeline green" as data validation pass.
- Required next action: make weekly output and docs distinguish "canary ran / advisory warning" from "data passed"; do not let canary status support alpha or production evidence.

### SR-DET-001 - Deterministic report depends on wall-clock state for circuit breaker status

- Severity: P2
- Status: open
- Owner phase: Phase 4 deterministic report / state replay
- Evidence: `runners/run_analysis_report.py` calls `state_manager.is_circuit_breaker_active()` without an as-of replay time; state manager defaults to `datetime.now(timezone.utc)`.
- Accepted calibration: schema validation is real for report output; the issue is replay determinism, not schema validity.
- Required next action: allow report generation to pass a deterministic `now` / as-of timestamp when replaying historical reports, or document this as an explicit live-state limitation.

### SR-OPS-001 - Audit #1 operational findings need line-level revalidation

- Severity: P2
- Status: needs_revalidation
- Owner phase: A-short operation / Phase 3-6 maintenance
- Evidence: audit #1 reported L3 today default risk, silent degradation paths, forward tracker atomic-write concern, missing tests, and possible delisted-universe handling issues.
- Accepted calibration: at least some items have partial counter-evidence in current code, so this entry tracks the need to revalidate rather than pre-judging every claim as a defect.
- Required next action: re-run a focused repo review of each audit #1 item and split confirmed issues into separate entries or close them with evidence.
