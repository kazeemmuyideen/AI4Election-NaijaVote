# Production Hardening & Operations

This document covers the controls that cannot be fully enforced by application code alone.

## 1. Distributed / Strong Rate Limiting

- Set `REDIS_URL` (e.g. `redis://redis:6379/0`) in production so rate limits are shared across workers and instances.
- Keep SQLite fallback only for local/dev; SQLite counters are best-effort and require a shared DB file across workers.
- Run the app behind a trusted gateway/WAF/CDN that also enforces coarse IP and bot rate limits.
- Set `TRUST_PROXY_HEADERS=true` only when the trusted proxy overwrites `X-Forwarded-For`/`X-Real-IP`. Never trust client-supplied forwarded headers directly.

## 2. SSRF / DNS Rebinding / TOCTOU

Application controls in place:
- Public HTTPS URL validation.
- Private/loopback/link-local/reserved/multicast literal IP rejection.
- DNS resolution rejects private targets.
- `OUTBOUND_ALLOWED_HOSTS` optional allowlist.
- Outbound HTTP redirects disabled.

Infrastructure controls required:
- Egress firewall/proxy allowlist only required destinations (Open-Meteo, NiMet, NIHSA, configured LLM/Twilio endpoints).
- Block direct public DNS egress from app containers; use controlled DNS/resolver.
- Prefer static IP allowlists or egress proxy policies where providers support them.
- Do not give the app broad internet egress.

## 3. Body Buffering / Memory

Application controls in place:
- `MAX_REQUEST_BODY_BYTES` and `MAX_ADMIN_IMPORT_BYTES` caps.
- POST/PUT/PATCH request-size middleware rejects oversized bodies before handler parsing.

Infrastructure controls required:
- Enforce the same/smaller limits at reverse proxy/WAF (`client_max_body_size`, request body limits).
- Set conservative timeout and connection limits.
- Keep admin import caps low in public deployments; prefer offline ingestion for large datasets.

## 4. Supply Chain Enforcement

Application/repo controls in place:
- Pinned dependencies in `requirements.txt` and `requirements-dev.txt`.
- CI runs tests, syntax checks, and blocking `pip-audit`.

Release controls required:
- Build from pinned deps in CI/release pipeline; generate hash-locked install artifacts for deployment images.
- Enable Dependabot/Renovate, secret scanning, SAST, container scanning.
- Require signed commits/tags and protected main branch reviews.
- Use minimal base images and rebuild regularly for CVE patches.

## 5. Ops / Data Readiness

- **Audit logging**: ship stdout JSON audit events to centralized logging/SIEM; alert on admin auth failures, rate-limit spikes, import/sync failures, webhook signature failures.
- **Monitoring**: uptime, latency, 4xx/5xx, queue/import duration, DB size, Redis health, TLS cert expiry.
- **Backups**: scheduled DB backups, encrypted at rest, regular restore drills.
- **TLS/WAF/CDN**: terminate TLS at trusted edge, HSTS, WAF rules, bot protection, CDN for static assets.
- **Secrets**: managed secret store/KMS, rotation policy, least-privilege access.
- **Data governance**: confirm INEC data rights; load audited official polling-unit data; obtain NiMet/NIHSA production contracts/endpoints; keep hazard/risk claims source-backed.
- **Language/accessibility**: independent native civic/legal review for translations; accessibility audit (WCAG), screen-reader/manual keyboard testing, low-bandwidth/device testing.
- **Nonpartisanship/privacy**: content review for neutrality, privacy impact assessment, retention limits, incident response plan, SLA/runbooks.
