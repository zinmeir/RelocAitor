# Security and privacy

RelocAitor gives information, not legal representation, and does not guarantee any immigration outcome.

## What is protected, and how

| Area | Implementation |
|---|---|
| Passwords | scrypt (n=2¹⁴, r=8, p=1, 16-byte salt); minimum 10 characters; constant-time comparison |
| Sessions | 256-bit random token in an `HttpOnly`, `SameSite=Lax` cookie (`Secure` when `RELOC_SECURE_COOKIES=1`); only its SHA-256 is stored; 14-day expiry; sign-out deletes it |
| CSRF | Every state-changing `/api/me` request needs the per-session token in `X-CSRF-Token` |
| Authorisation | Every workspace query filters by the session's user id; tests check one user can't read or change another's rows |
| Encryption at rest | Saved profiles (passport, income, savings, family, education) are encrypted with Fernet (AES-128-CBC + HMAC-SHA256). Key from `RELOC_ENCRYPTION_KEY` (a Fernet key or any 32+ character secret), else generated once into `instance/encryption.key` (mode 600) |
| Encryption in transit | Terminate TLS at the host (Render, a load balancer or a reverse proxy) and set `RELOC_SECURE_COOKIES=1` |
| Documents | Not uploaded or stored. The checklist records what you've prepared, not the files |
| Input validation | All profile fields validated on every endpoint; request bodies capped at 256 KB |
| Rate limiting | Per client: 240 requests/min on the API, 10/min sign-in, 5/min registration, 30/min assistant (`RELOC_RATE_LIMIT`) |
| Headers | `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`, `Permissions-Policy`; `Cache-Control: no-store` on personal data |
| Audit log | Registration, sign-in, profile saves and exports are logged per user (no content) |
| Logs | `RELOC_LOG_JSON=1` writes method, path, status and timing only; request bodies are never logged |
| Deletion | `DELETE /api/me` (password confirmation) removes the account and every row that belongs to it; audit entries are anonymised. `GET /api/me/export` downloads everything first |

## AI and third parties

- No profile data leaves the server unless an LLM key is configured **and** the person ticks "Let the AI see my
  profile" for that question. Without consent the assistant answers from templates.
- The LLM receives tool results, not the database, and its wording is rejected if it contains a number that
  doesn't come from a tool result.
- Job searches send only the occupation keyword and country to the job API, never the profile.

## Known gaps before handling real users at scale

- No email verification, password reset or two-factor sign-in.
- No Content Security Policy yet (the page uses inline scripts and CDN map files; both need moving first).
- The rate limiter is per process; behind several workers or machines use a shared one (e.g. Redis).
- SQLite suits one server; move the workspace tables to PostgreSQL for several.
- No independent security review or penetration test has been done.
