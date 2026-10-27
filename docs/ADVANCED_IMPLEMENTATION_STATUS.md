# Advanced feature implementation

The user authorized the complete attached specification on 28 October 2026.
The source specification is preserved in EVERYFAN_ADVANCED_FEATURES.md.

Build sequence: foundations → T1/T2 → T3/T5 → T4 → T6/T7/T8 →
P1/P2/P3 → P4/P5/P6 → P7/P8 → MCP → reports → coach → ask → demo → docs.
MCP foundation hooks are delivered after their providers exist, as required by
task 9. Reports may initially consume deterministic coach data before the coach
writer is connected; there is no dependency cycle in the fact providers.

- [x] F possession/tactics index and pitch-layer infrastructure
- [x] T1/T2 formation, shape, compactness
- [x] T3/T5 links and defensive/offside lines
- [x] T4 nearest-player space control
- [x] T6/T7/T8 line breaking, counters, pressing
- [x] P1/P2/P3 reference pools, benchmark/progress/role index
- [x] P4/P5/P6 heatmaps, trails, sprints, output curve
- [x] P7/P8 matchups and off-ball runs
- [x] MCP endpoint equivalence/authentication
- [x] A3 reports
- [x] A2 coach
- [x] A1 ask and evaluation
- [x] Offline demo artifacts for all matches
- [x] Documentation/performance/bilingual/browser checks
- [ ] Native Arabic editorial review (human)
- [ ] Deployed Foundry/live smoke check (deployment environment)

Verification: full pytest 698 passed, latest focused Ask/range checks 13 passed,
pyflakes clean; frontend formatting, 11 unit tests, build and npm audit (zero
vulnerabilities) pass. All 11 Chrome acceptance tests pass, including a complete
replay and live viewer controls. The required existing agent evaluation publishes
236/236 faithful overlays and catches 80/80 injected numbers. Ask evaluates 44
bilingual questions with 100% published numeric faithfulness, correct refusals and
expected facts. Actual endpoint warm p95: tactics 99.73 ms, profile 71.15 ms.
Cold index/reference costs are separately recorded. The percentile regression test
was also verified to fail under a reversed comparison and the source was restored.

There are 80 recorded reports, 576 suggested answers, and ten coach variants per
match. Stub-generated prose is labelled as a template. Original bundle items,
recaps and fingerprints are unchanged; advanced content is optional and packed.

Every stage retains frozen contracts, source IDs/frame evidence and as-of
cutoffs. Local verification uses off/stub modes. Live model recording and native
Arabic review are reported separately; automated checks never impersonate them.
