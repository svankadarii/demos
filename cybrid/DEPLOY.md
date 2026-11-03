# Deployment (live)

Live at https://cybrid.srinivankadari.com (interactive docs at `/docs`).

## What runs here

A Python FastAPI service (see `requirements.txt`: fastapi, uvicorn). It
holds state in memory only, so it needs no database, no environment
variables, and no credentials to run. Health check: `GET /health` returns
`{"status": "ok"}`.

## Vercel adaptation (app code unchanged)

The FastAPI app in `app/main.py` is identical to the local version. Two
files were added to run it on Vercel serverless, nothing else changed:

- `api/index.py` — re-exports the FastAPI app for Vercel's Python runtime.
- `vercel.json` — rewrites all paths to the `api/index.py` function.

## Serverless state caveat (read before demoing)

Vercel serverless instances do not share in-memory state, so transfers
created with `POST /transfers` in one request may not be visible to a later
`GET /alerts` or `GET /transfers/{guid}/audit` request. The scripted demo
does not depend on that: a single `POST /scenarios/run` response contains
all three transfers, their audit lines, and the stuck-transfer flag
(`next_action: "escalate, do not retry blindly"`). Use that response for
the 30-second demo; treat the ad-hoc multi-request endpoints as
per-instance exploration.

## What is NOT done here

- No Cybrid service is contacted, no money moves, and no credentials or
  customer data are involved: every transfer is a local mock shaped on the
  public SDK model text (see README.md caveats).
- This demo project is separate from the main personal site: it lives in
  its own repo and its own Vercel project, and nothing here touches the
  `personalwebsite` repo or the main site's Vercel project.
