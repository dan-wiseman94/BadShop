# Security reporting

Do not post exploit details, credentials, private images or affected project archives in a public
issue. On the [repository Security page](https://github.com/dan-wiseman94/BadShop/security), use
**Report a vulnerability**. Private reporting is enabled and was verified for the 0.4.0 release.
If that option is unavailable, open
a minimal issue requesting a private contact channel without including the vulnerability details.
No response SLA is promised until its owner and coverage are agreed.

A useful private report includes the affected version/OS, a minimal synthetic reproduction,
the trust boundary crossed, expected/observed behavior and impact. Avoid running destructive
payloads, accessing unrelated data or testing third-party providers without their authorization.

Release candidates must pass exact-lock Python, JavaScript and Rust advisory scans. Known Rust
vulnerabilities fail unconditionally. Other Rust notices require package/version/advisory-specific
reviews with expiry dates in `packaging/rust-advisory-review.json`; expiry or a changed warning
blocks the gate. A reviewed notice remains a residual risk, not a patched dependency.

The app's loopback token/actor authentication, Origin restrictions, project validation,
approval gates and DNS policy are defense in depth. Local only is not an OS firewall; worker
processes are resource boundaries, not security sandboxes. See [privacy](docs/privacy.md).

For a confirmed incident: preserve a sanitized reproduction, assess exposure and affected
versions, revoke compromised credentials/signing material if needed, fix and regression-test the
boundary, then publish an advisory and patched release with a clear upgrade path. Never silently
replace release assets or move a published tag. Signing-key rotation requires an explicit update
and recovery plan for already-installed clients.
