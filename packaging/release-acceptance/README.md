# Candidate acceptance records

Follow [the release promotion procedure](../../docs/releasing.md#accept-and-promote-an-exact-candidate).
Generate a pending `<tag>.json` using `packaging/release_gate.py template`, perform
the required checks, and commit real evidence through a PR to main before promotion.
Both stable and nightly candidates require acceptance. Do not copy approvals from
another build or mark unresolved license reviews approved to make a gate pass.
