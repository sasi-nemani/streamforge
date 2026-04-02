# StreamForge Architecture Decision Log

Maintained since: 2026-04-01
Purpose: Record every feature, design choice, and intentional gap with rationale.

---

## Features Implemented

### Core Engine
| Feature | File(s) | Design Choice | Rationale |
|---------|---------|---------------|-----------|
| Reservoir sampling (Algorithm R) | `sampler.py` | O(k) memory, seeded for quorum | Can profile 100GB topic without loading it |
| Quorum voting (N independent samples) | `inference.py` | Configurable per topic (default 5) | Multi-sample consensus catches type ambiguity |
| LLM cascade (5 providers) | `inference.py` | Ollama -> Groq -> OpenAI -> OpenRouter -> statistical | Never returns "no result" — always degrades gracefully |
| Field type registry (229 seeds) | `field_registry.py` | Atomic JSON file, pre-seeded | 89% cache hit rate, $0.00 inference after first run |
| Statistical drift detection | `detector/core.py` | Binomial z-test, chi-squared, PSI | Deterministic, auditable, zero API cost |
| Tier classification (1/2/3) | `detector/classify.py` | Conservative thresholds | Tier 3 always fires; Tier 1/2 suppressed during LEARNING |
| PII detection (8 categories) | `pii_detector.py` | Regex + field name heuristics | No external calls, deterministic, fast |
| Watch state machine | `detector/watch.py` | LEARNING -> STABILIZING -> STABLE | Prevents false alerts during onboarding |
| Graceful shutdown | `detector/watch.py` | SIGTERM/SIGINT -> checkpoint save | No data loss on container restart |

### Security Hardening (implemented)
| Feature | File(s) | Design Choice | Rationale |
|---------|---------|---------------|-----------|
| PII scrubbing in LLM prompts | `inference.py` | Scrub before building prompt | Payment data never reaches external APIs |
| API key sanitization in logs | `inference.py` | Regex mask `sk-*`, `gsk_*` | Keys never appear in log aggregators |
| Audit trail ON by default | `audit.py` | Opt-out via `STREAMFORGE_AUDIT=0` | SOC2 requires always-on audit |
| PII redaction in registry | `field_registry.py` | Toggle via `STREAMFORGE_REDACT_PII` | PII samples replaced with `[REDACTED]` |
| File permissions (0o600) | `schema_writer.py` | `_secure_write()` helper | Owner-only access on all written artifacts |
| Event size guard | `sampler.py` | MAX_DEPTH=10, MAX_KEYS=500 | Prevents OOM and RecursionError on pathological events |
| Line length guard (64KB) | `sampler.py` | Reject before regex | Prevents ReDoS on adversarial input |
| Kafka PLAINTEXT rejection | `config.py` | Blocked in prod mode | PCI-DSS Req 4.2.1 — encrypt data in transit |
| Ollama gated to dev | `inference.py` | `STREAMFORGE_ENV=dev` required | 3B model too unreliable for payment data baselines |
| OpenRouter :free removed | `inference.py` | Replaced with paid tier | No SLA/DPA on free models |
| print() eliminated in watch | `detector/watch.py` | All 27 calls -> logger.info() | Structured logging in containerized deployments |
| Startup config validation | `config.py` | `validate_config()` fails fast | Missing SASL password caught before first poll |

### Infrastructure
| Feature | File(s) | Design Choice | Rationale |
|---------|---------|---------------|-----------|
| 2-VM GCP deployment | `deploy/two-vm.sh` | sf-kafka + sf-app, same VPC | No ngrok, internal networking, $16/month |
| Confluent Kafka KRaft | `deploy/two-vm.sh` | No Zookeeper, 512MB heap | Runs on e2-small with room for feed_all.py |
| 4-topic live feed | `demo/feed_all.py` | payments/bookings/iot/wiki | Realistic multi-stream demo with real data |
| 3-persona demo | `cli/ops_cmd.py` | --cto / --eng / --loop + ui | Different audiences, same real commands |

---

## Intentional Gaps (left open, with rationale)

### Security gaps deferred to post-POC
| Gap | Severity | Why deferred | When to fix |
|-----|----------|-------------|-------------|
| SASL password in plain Python string | HIGH | Demo uses PLAINTEXT Kafka. No SASL in POC. | Before enterprise deployment |
| No webhook URL allowlist | HIGH | No webhooks configured in demo. | When customer enables webhooks |
| No DPA verification before LLM calls | CRITICAL | Demo keys are disposable. Real deployment needs STREAMFORGE_APPROVED_PROVIDERS. | Before any real customer data touches LLM |
| Window checkpoint unencrypted on disk | HIGH | GCP disk encryption covers this at infra level. App-level encryption is enterprise. | Before multi-tenant deployment |
| Field registry single-file (no concurrency) | HIGH | Single-process CLI model. 4 watchers on same host is fine. | At >10 concurrent watchers on shared state |
| kafka-python fallback (unmaintained) | HIGH | confluent-kafka used in production. kafka-python is dev convenience. | Remove fallback before enterprise |
| No dependency pinning | MEDIUM | pip install from pyproject.toml is fine for POC. | Add requirements.txt with hashes for production Docker |
| No schema change approval workflow | N/A | `streamforge accept` works for single-operator POC. Two-person approval is enterprise. | When customer asks for governance |
| No PagerDuty implementation | N/A | Config model exists. No customer has requested it yet. | 1-day build when needed |
| No multi-region correlation | N/A | Single-region POC. | Series A feature |
| No encryption at rest (app-level) | MEDIUM | GCP CMEK covers disk encryption. App-level is defense-in-depth. | PCI-DSS Level 1 certification |
| Luhn check for card PII | MEDIUM | We detect card_number by field name, not by value validation. Schema inference cares about type, not value validity. | If false positive rate proves problematic |

### Architecture gaps deferred to v2
| Gap | Why deferred | Trigger to build |
|-----|-------------|-----------------|
| Phase state machine duplication (file vs kafka watch) | Doesn't affect functionality. Code smell, not a bug. | Before next major watch feature |
| PSI binning O(n*bins) | 200 events * 10 bins = 2000 ops. Not a bottleneck. | Performance complaint at >10K samples |
| Consumer impact registry | `consumers.yaml` exists as manual config. Dynamic blast radius is v2. | Customer with >10 consumer services |
| Schema rollback CLI | `git revert` on schema.yaml works. CLI command is convenience. | When schema-as-code workflow matures |
| Retention policy enforcement | `find -mtime -delete` cron works. Product feature is enterprise. | When customer accumulates >1000 drift reports |

### Audit & Observability (implemented)
| Feature | File(s) | Design Choice | Rationale |
|---------|---------|---------------|-----------|
| LLM call audit (prompt + response) | `audit.py`, `inference.py` | Logs provider, model, latency, prompt/response preview (2KB max) | Security can verify exactly what data left the system |
| Multi-schema audit coverage | `detector/routing.py` | Routing regression now emits audit events | Bookings/wiki were silent — 2 of 4 streams had no audit trail |
| Configurable audit verbosity | `audit.py` | `STREAMFORGE_AUDIT_LEVEL=DEBUG\|INFO\|WARNING` | Clean checks at DEBUG (90% noise reduction), drifts at INFO |
| Format-preserving PII pseudonymization | `inference.py` | Synthetic values match original format/length | `alice@stripe.com` → `user_6943@streamforge.synthetic` — LLM infers correct type |
| Float precision rounding | `models.py` | `FieldDrift.model_post_init` rounds to 4dp | Eliminates `0.07999999999999999` in audit logs |
| Card PII false positive suppression | `pii_detector.py` | Skip card pattern on `_id/_uuid/_ref` fields | `event_id` with numeric values no longer triggers Tier-3 |
| IP regex range check | `pii_detector.py` | Octet range + max>100 check | Version strings like `1.2.3.4` no longer trigger PII:ip_address |

### Structural Improvements (implemented)
| Feature | File(s) | Design Choice | Rationale |
|---------|---------|---------------|-----------|
| WatchPhase state machine | `detector/phase.py` | Single class, 13 unit tests | Eliminates duplicated LEARNING→STABILIZING→STABLE logic |
| E2E integration test | `test_e2e_lifecycle.py` | init→plan(clean)→plan(drifted) | Tests the module seams unit tests miss |
| Registry file locking | `field_registry.py` | `fcntl.flock()` on save | Prevents concurrent init processes from clobbering |
| SHA256 structural fingerprinting | `profiler.py` | 12-char SHA256 (was 8-char MD5) | 48-bit collision resistance (65536x better) |
| --dry-run on accept | `cli/ops_cmd.py` | Preview without writing | Operator safety for one-way door operations |

### Bugs Found in Production Soak Test (fixed)
| Bug | How found | Fix |
|-----|-----------|-----|
| `event_id` falsely flagged as card PII (22 Tier-3 reports overnight) | 9-hour soak on GCP | Suppress card pattern on `_id` fields |
| IoT `humidity_pct` drifting 82% of cycles | Audit log analysis | Re-init with larger sample (400 events) |
| Audit log only captured IoT+payments (bookings/wiki silent) | Audit breakdown by stream | Added audit to `detect_drift_multi_schema` routing |
| 2,108 float values with >10 decimal places | Audit data analysis | `model_post_init` rounds to 4dp |
| `_enabled()` gated all audit at non-DEBUG levels | Setting AUDIT_LEVEL=INFO silenced everything | Changed to check `level <= CRITICAL` |
| Cross-stream registry type poisoning (wiki→payments timestamp) | GCP E2E testing | Step 8b correction on all fields |
| LLM mislabeling epoch_ms as ISO8601 | GCP init testing | Quorum voting + type correction catches it |

### Intentional Gaps (updated)
| Gap | Severity | Why deferred | When to fix |
|-----|----------|-------------|-------------|
| WatchPhase not wired into actual watch loops | MEDIUM | Class extracted + tested, inline logic still runs. Full wire-up needs persistence migration. | Next sprint |
| Auto-reinit on sustained drift | N/A | Proposal mechanism designed (background re-init → proposed schema). Manual `init` + `accept` works today. | Post-demo feature |
| inference.py still 1330 lines | LOW | Works correctly. Split when adding features. | When adding new inference providers |
| drift_detector.py compat shim still exists | LOW | No breakage risk. Cleanup task. | When removing backward compat |
| File permissions 644 not 600 | MEDIUM | `_secure_write()` exists but not wired into all write paths (registry, schema_writer main path) | Before enterprise |

---

## Test Coverage

| Test file | Tests | Covers |
|-----------|-------|--------|
| test_prod_hardening.py | 22 | Audit defaults, API key sanitization, PII redaction, config validation, registry audit |
| test_security_hardening.py | 16 | PII scrub in prompts, Kafka TLS, file permissions, event size guard, ReDoS guard |
| test_synthetic_pii.py | 24 | Format-preserving pseudonymization, length preservation, all PII categories |
| test_audit_coverage.py | 10 | Multi-schema audit, routing regression audit, LLM call audit, verbosity config |
| test_watch_phase.py | 13 | Phase state machine (LEARNING→STABILIZING→STABLE transitions) |
| test_e2e_lifecycle.py | 3 | Full init→plan(clean)→plan(drifted) lifecycle |
| test_exporter_protobuf.py | 56 | Protobuf wire stability, field numbering |
| test_drift_detector.py | 52+ | Drift detection, tier classification |
| test_pii_detector.py | 20+ | PII pattern matching, IP range check, card suppression |
| test_field_registry.py | 15+ | Registry CRUD, cache hits, save/load, file locking |
| test_inference_cascade.py | 10+ | LLM cascade, fallback, coverage check |
| test_sampler.py | 15+ | Reservoir sampling, streaming load, size guards |
| test_statistical_tests.py | 40+ | Z-test, chi-squared, PSI, Cramer's V |
| **Total** | **1012** | **Full suite, zero failures** |

---

## Production Soak Test Results (GCP, 17+ hours)

| Metric | Value |
|--------|-------|
| Duration | 17+ hours (2026-04-01 18:31 → 2026-04-02 11:18) |
| Total events processed | 1.4M+ across 4 topics |
| Audit entries | 23,600+ |
| Drift reports generated | 11 (10 bookings routing, 1 wiki routing) |
| False positives caught and fixed | 22 (event_id PII), 772/cycle (IoT baseline) |
| Watchers restarted | 0 (since last deployment) |
| Errors in watch logs | 0 |
| PII leaks in registry | 0 |
| Memory stable | 695MB of 1.9GB |
| Disk stable | 4.1GB of 20GB (22%) |
