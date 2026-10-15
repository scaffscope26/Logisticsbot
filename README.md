# Florida Logistics Control Tower — v0.2

Excel/CSV-first regional material planning, now with a Vercel Flask entrypoint and
shared Supabase persistence. Quantify remains the operational source of truth;
this application proposes opportunities and records internal approvals only.

## Run locally

Use Python 3.12:

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Set the variables listed in .env.example in your shell (or your hosting dashboard).
python app.py
```

Open http://127.0.0.1:8765. The app does not automatically load `.env` files.
It requires a configured Supabase project and an invited workspace member to sign
in. Without configuration it serves the sign-in screen and returns a clear setup
error. There is no automatic SQLite fallback in cloud mode.

The original `python server.py` entrypoint remains an unauthenticated,
single-user SQLite development tool. Keep it on localhost and use synthetic data.
Vercel uses `app.py`, never `server.py`.

## Current pilot deployment

The approved Free-plan test project `cazqeiyrkqjezcanriow` follows
`development/import-v0.1-prototype` through Supabase's GitHub deployment setting.
Supabase labels this existing database "production", but it is the Logistics Bot
test project. PR preview database branching remains disabled on the Free plan.
Vercel connection variables are scoped only to Preview. Git `main` is unchanged.
The remote-specific Auth configuration keeps invitations pointed at the stable
Vercel branch preview URL. Changing that URL requires updating the remote config.

## Supabase / GitHub setup

The versioned schema lives in `supabase/migrations/`. Supabase's GitHub integration
can deploy these migrations to PR previews when branching is enabled. A connected
repository alone does not prove migrations were deployed. Check the Supabase PR
check and preview database before merging. Do not connect a Vercel preview to
production data while testing migrations.

1. Apply the migration to the intended preview/test project through Supabase
   branching or the Supabase CLI. It creates only Logisticsbot-owned objects.
2. Invite the first user using Supabase Authentication and establish a password
   through the project's configured invitation/password setup flow. This app
   supports email/password sign-in plus invitation/recovery links that return an
   access token in the URL fragment. Set Supabase Auth's Site URL to the intended
   Vercel preview URL so those links land on the app's password setup form. Users
   set their own passwords. Public registration and MFA challenges are not implemented.
3. Run `supabase/bootstrap.example.sql` in that project's SQL editor after
   replacing the email. Save the returned workspace ID.
4. Add these environment variables to Vercel's appropriate environment:

| Variable | Meaning |
| --- | --- |
| `SUPABASE_URL` | Intended Supabase project's API URL |
| `SUPABASE_PUBLISHABLE_KEY` | Publishable key; `SUPABASE_ANON_KEY` also supported |
| `SUPABASE_SECRET_KEY` | Server-only secret; `SUPABASE_SERVICE_ROLE_KEY` also supported |
| `LOGISTICS_WORKSPACE_ID` | Workspace UUID returned by bootstrap |

Never prefix the secret with `NEXT_PUBLIC_`, put it in HTML, or commit it.
No OpenAI key or LLM is required for deterministic planning.

Use the repository root in Vercel with the Flask framework preset. `app.py` is the
entrypoint, `.python-version` selects Python 3.12, and `vercel.json` supplies the
function settings. The current dependency versions are pinned in requirements.
No build command or writable local database is needed. Redeploy after changing
Vercel environment variables. Public `/api/health` reports process health only;
it does not verify the database connection or authorization.

## Roles and access

Workspace membership is provisioned by an administrator in the private database
schema. `viewer` can read/preview, `editor` can import and investigate, and
`approver` can also approve and release commitments. There is no self-enrollment.
Signed-in nonmembers cannot read logistics data. Operational tables are in the
unexposed `logistics_private` schema with RLS and no client table grants. A narrow
read function checks the signed-in user's membership. Write functions are granted
only to `service_role`; the server verifies the session and the database checks
actor membership and role again.

Access tokens are kept in HttpOnly, SameSite=Strict cookies (Secure on HTTPS),
never browser local storage. Requests that change data require the same Origin.
Sessions expire after at most one hour; users sign in again. Sign-out clears the
browser cookie; an already copied access token remains valid until its expiry.
The server verifies each session against Supabase Auth and sends no secrets to the
browser. Enable the appropriate Supabase/Vercel rate limits for your deployment.

## Import and plan

Run `python generate_sample.py` to refresh the illustrative CSV dates. Import the
four files from `sample_data/` after sign-in. All samples are synthetic.

Upload `.csv` or `.xlsx`, preview, then map every required field. The parser uses
the first worksheet and one header row. Limits: 2.5 MB uploaded file, 20,000 rows,
200 columns, and 40 MB expanded XLSX. Keep part numbers as Excel text to preserve
leading zeros. Dates must be ISO `YYYY-MM-DD` or actual Excel dates. This version
requires return-date values for project forecasts; missing dates must be supplied
before importing that report. Duplicate business lines are rejected; consolidate
quantities by facility/part and project/reservation first. Invalid rows reject the
whole upload without changing existing reports.

Each import atomically replaces one report type, increments the workspace version,
and archives previous decisions to the audit log. Other report types remain.
The dashboard displays report import times. Export refreshes are manual; no
background polling of Quantify is configured.

The deterministic engine matches exact parts for the next 30 days, prefers the same
facility, and consumes each proposed supply quantity only once. Source IDs are
based on business identifiers, so reordering an import cannot move a decision to a
different source. Project forecasts are informational only. Scheduled returns have
a two-day inspection allowance; overdue returns are excluded until reconfirmed.
Planning uses the Florida/Eastern calendar date.

## Internal approvals

The app checks that the selected opportunity still exists in the current plan;
users cannot submit arbitrary supply/quantity payloads. Approvals require an explicit
confirmation of availability, inspection, transport, and Quantify commitments.
Workspace row locks and optimistic versions serialize imports and decisions:
concurrent changes return a conflict and require refresh. Approval updates increment
the version too, so one user's old screen cannot silently overwrite another user's
decision.

Approved commitments block report replacement until an approver marks them
Completed or Rejected. Approvals from an earlier planning day must be resolved
before new approvals, to prevent overlapping commitments as the horizon advances.
Earlier approvals remain selectable in the queue. Completed movements cannot be
approved again until a fresh report snapshot is imported. Other statuses are planning
annotations; rejected suggestions remain visible and continue consuming their
proposed quantities until the next report/plan revision. Every import and decision
is audited with actor and timestamp. These are internal coordination records,
not reservations written to Quantify.

## Verification

```sh
python -m unittest discover -s tests -v
```

Tests use temporary SQLite databases or a mocked Supabase adapter, with no live
company data. They cover CSV/XLSX parsing, sample matching (five matches and zero
shortages), forecast separation, inspection timing, stable identities, duplicate
and invalid quantities, session checks, Origin checks, stale revisions, and
approval confirmation. GitHub Actions also runs the migration and authorization,
revision, approval-blocking, and audit checks against disposable PostgreSQL 17.

The disposable database bootstrap under `tests/` is **not** for a real Supabase
project; Supabase already supplies its auth schema and roles.

## Remaining pilot validation

Validate real Quantify headings, expected-return dates, holds, and report freshness.
Freight cost, journey time, capacity, inspection results, substitutions, and
purchase savings still require manual review. There is no automatic dispatch,
purchase approval, Quantify write-back, national multi-region UI, or automatic
notifications. The live deployment, invitations, and live RLS/advisor checks must
be verified in the intended Supabase project and Vercel preview before operational
use. GitHub checks do not substitute for that live configuration check.
