# Security model

## Who can do what (RBAC)
| Capability | viewer | analyst | admin |
|---|:-:|:-:|:-:|
| Read analytics, uploads, review queues, model info | ✅ | ✅ | ✅ |
| Upload CSVs, correct classifications, merge/reject suppliers | ❌ | ✅ | ✅ |
| Use the AI copilot (consumes LLM quota) | ❌ | ✅ | ✅ |
| Retrain the model | ❌ | ❌ | ✅ |
| Manage users and API keys, read the audit log | ❌ | ❌ | ✅ |

## Credentials
- **People:** `POST /auth/login` returns a signed JWT (HS256, 60 min). Send it as `Authorization: Bearer <token>`.
- **Machines:** API keys (`X-API-Key`), each bound to a tenant and a role. Created by an admin; the key is shown **once**.

## What is protected, and how
| Risk | Control |
|---|---|
| Stolen database | Passwords are stored as salted **scrypt** hashes; API keys only as **SHA-256** hashes (no plain-text credentials anywhere). |
| Password guessing | Login is throttled (10 attempts / 15 min per email); unknown e-mails take the same time as wrong passwords. |
| Forged or stale tokens | Signature and expiry are verified; the user's **role, tenant and active flag are re-read from the database on every request**, so demoting or disabling a user takes effect immediately and a token cannot claim a higher role. |
| Cross-tenant access | The tenant always comes from the verified credential, never from the request; every query is filtered by tenant (tests prove a user cannot see or touch another tenant's data). |
| Abuse | Per-tenant rate limit (HTTP 429). |
| Accountability | Audit log records the **actor** (user e-mail or `key:<name>`) for uploads, reviews, retraining, user/key changes and logins. |
| Insecure deployment | With `APP_ENV=production` the app refuses to start if `SEED_DEMO` is on or `JWT_SECRET` is the default/short. |

## Production checklist
1. `APP_ENV=production`, `SEED_DEMO=false`, `JWT_SECRET` = 32+ random characters.
2. Create the first admin: `python scripts/create_admin.py --tenant <id> --name "<Company>" --email <you>`.
3. Serve only over HTTPS (terminate TLS at the proxy/host).

## Known limitations (honest)
- No refresh tokens, MFA/SSO, password-reset flow or per-IP login throttling.
- JWT uses a shared secret (HS256); rotating it logs everyone out.
- Tenant isolation is enforced in application code; PostgreSQL row-level security is a planned defence in depth.
- Demo accounts (`admin|analyst|viewer@<tenant>.demo`, password from `DEMO_USER_PASSWORD`) exist only when `SEED_DEMO=true`.
