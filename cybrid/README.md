# Cybrid transfer-state reconciliation harness

## What this is

A FastAPI demo that models Cybrid's Bank API transfer lifecycle as an explicit
state machine (pending → in_progress → completed, with failed, cancelled,
manual_intervention, and reversed branches), flags transfers stuck in
non-terminal states, and emits one audit-ready record per transfer. It runs
entirely on a local mock: no Cybrid account, credentials, customer data, or
real money is involved.

## Why I built it

I built this to understand Cybrid's product. Cybrid's public SDK model gives
transfers a distinctive state vocabulary, including `manual_intervention`
and `reversed`, and Cybrid Payments promises an exportable, audit-ready
record for every payment. This demo explores what an integrator's
reconciliation layer should do with that vocabulary: walk each transfer
through its states, catch the ones that need a human, and produce the audit
line. It is a study of their product, not a claim about how their
production system behaves.

## Run it

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./run.sh
```

Then open http://localhost:8000/docs for the interactive API docs, or
http://localhost:8000/health to confirm it is running.

Run the tests with:

```bash
pytest
```

## The 30-second demo

Live at https://cybrid.srinivankadari.com (interactive docs at `/docs`).

1. Open https://cybrid.srinivankadari.com/docs.
2. `POST /scenarios/run`: three mock transfers walk their states. The clean
   payout lands `completed`, the failed payout lands `failed` with a reason,
   and the stuck one lands `manual_intervention`.
3. Read the single response: it already contains everything — each
   transfer, its audit line (source, route, destination, fees, FX rate,
   recipient, timing), and the stuck transfer's next action, "escalate, do
   not retry blindly". Every transfer also shows the `quoteGuid` it
   executed against, proving quote → transfer ordering.

Locally, the same flow works via http://localhost:8000 (see "Run it"
above), where `GET /alerts` and `GET /transfers/{guid}/audit` re-derive
the same flag and audit line across requests.

## Deployment note: serverless state

This deployment runs on Vercel serverless, where the in-memory store is
per-instance: requests are not guaranteed to hit the same instance, so
transfers created with `POST /transfers` in one request may not be visible
to a later `GET /alerts` or `GET /transfers/{guid}/audit` request. That is
why the scripted demo above is a single `POST /scenarios/run` response —
it contains the transfers, the stuck-transfer flag, and the audit lines all
at once, so the demo flow never depends on state surviving between
requests. The app code is otherwise unchanged from the local version.

## Tech

- Python, FastAPI, Uvicorn
- In-memory store (no database or credentials needed)
- pytest + httpx for tests

## Sources

Copied from the research brief (`../research/cybrid.md`); only VERIFIED claims
are used in the code and copy above.

- "US$10M Series A, announced Oct 22, 2025, led by BDC Capital's Growth
  Venture Fund, with Golden Ventures, Luge Capital and Panache Ventures
  participating." — https://pulse2.com/cybrid-10-million-closed-to-advance-stablecoin-adoption-among-financial-institutions/ (VERIFIED)
- "Every payment generates a complete, exportable record - source, route,
  destination, fees, FX rate, recipient, and timing — ready for auditors and
  bookkeeping." — https://cybridpayments.com/ (VERIFIED, company claim)
- Bank API endpoints (`POST /api/quotes`, `POST /api/trades`,
  `POST /api/transfers`) and "Quote | /api/quotes | Create and list quotes,
  which are required to execute trades" — https://www.rubydoc.info/gems/cybrid_api_bank_ruby/0.119.154 (VERIFIED)
- Transfer model: states `pending`, `in_progress`, `completed`, `failed`,
  `cancelled`, `manual_intervention`, `reversed`; types `funding`, `book`,
  `crypto`; required `quoteGuid`; "The optional expected error to simulate
  transfer failure" — generated Java model, older SDK v0.58.38,
  https://jar-download.com/artifacts/app.cybrid/cybrid-api-bank-java/v0.58.38/source-code/app/cybrid/cybrid_api_bank/client/model/PostTransferBankModel.java (VERIFIED as SDK-model text; see caveat below)

## Caveats (unverified items, stated plainly)

- Whether the seven transfer states and the `expected_error` simulation
  control behave identically in the current (0.119.x) sandbox/production
  build is UNVERIFIED: the state vocabulary comes from an older SDK model.
  The mock is labelled as a mock, and a real sandbox adapter (behind
  env-var credentials, off by default) would be the path to proving it live.
- The 0.15–0.25% FX margin and mid-market FX figures are Cybrid's own
  published claims; the demo's fees/FX values are placeholder demo values,
  not live rates.
- Whether Cybrid Payments is served by the same Bank API is UNVERIFIED.
- No real sanctions screening, KYC verification, or payment execution is
  performed or claimed by this demo.
