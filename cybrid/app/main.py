"""Cybrid transfer-state reconciliation harness (demo, local mock only).

Models the transfer lifecycle documented in Cybrid's public Bank API SDK
model: states pending, in_progress, completed, failed, cancelled,
manual_intervention, reversed; transfer types funding, book, crypto; and a
required quoteGuid linking each transfer to the quote it executed against.

This is a study built to understand Cybrid's product. It talks to NO Cybrid
service, moves no money, and uses no credentials or customer data: every
transfer here is a local mock shaped on the public SDK model text.
"""

from datetime import datetime, timezone

import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(
    title="Cybrid Transfer-State Reconciliation Harness",
    version="0.1.0",
    description=(
        "Local mock of Cybrid's Bank API transfer lifecycle: state machine, "
        "stuck-transfer alerts, and audit-ready records. No Cybrid "
        "credentials, account, or real payments involved."
    ),
)

# ---------------------------------------------------------------------------
# State machine (state vocabulary from Cybrid's generated transfer model)
# ---------------------------------------------------------------------------
TERMINAL_STATES = {"completed", "failed", "cancelled", "reversed"}
ALL_STATES = {"pending", "in_progress", *TERMINAL_STATES, "manual_intervention"}

TRANSITIONS: dict[str, set[str]] = {
    "pending": {"in_progress", "failed", "cancelled"},
    "in_progress": {"completed", "failed", "cancelled", "manual_intervention", "reversed"},
    "manual_intervention": {"completed", "failed", "cancelled", "reversed"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
    "reversed": set(),
}

TRANSFER_TYPES = {"funding", "book", "crypto"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TransferCreate(BaseModel):
    """Fields mirror the public Bank API transfer model (mock subset)."""

    type: str = Field(description="funding, book, or crypto")
    quote_guid: str = Field(description="quoteGuid: the quote this transfer executes against")
    source: str = "USD account"
    route: str = "USD -> USDC -> local payout"
    destination: str = "Recipient bank"
    recipient: str = "Demo recipient"
    fees: str = "0.20%"
    fx_rate: str = "mid-market (demo value, not a live rate)"
    expected_error: str | None = Field(
        default=None,
        description=(
            "Optional simulated failure, mirroring the SDK model's "
            "'expected error to simulate transfer failure' control."
        ),
    )
    created_at: str | None = Field(
        default=None,
        description="Override for testing stuck-transfer windows; defaults to now.",
    )


class AdvanceRequest(BaseModel):
    to_state: str


_store: dict[str, dict] = {}


def _new_transfer(data: TransferCreate) -> dict:
    if data.type not in TRANSFER_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown transfer type {data.type!r}; expected one of {sorted(TRANSFER_TYPES)}",
        )
    created = data.created_at or _now()
    record = {
        "guid": str(uuid.uuid4()),
        "type": data.type,
        "quoteGuid": data.quote_guid,
        "state": "pending",
        "source": data.source,
        "route": data.route,
        "destination": data.destination,
        "recipient": data.recipient,
        "fees": data.fees,
        "fx_rate": data.fx_rate,
        "failure_reason": None,
        "expected_error": data.expected_error,
        "created_at": created,
        "updated_at": created,
        "history": ["pending"],
    }
    _store[record["guid"]] = record
    return record


def _advance(record: dict, to_state: str) -> dict:
    if to_state not in ALL_STATES:
        raise HTTPException(status_code=422, detail=f"Unknown state {to_state!r}")
    if to_state not in TRANSITIONS[record["state"]]:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot move transfer from {record['state']} to {to_state}",
        )
    record["state"] = to_state
    record["updated_at"] = _now()
    record["history"].append(to_state)
    if to_state == "failed" and record["expected_error"]:
        record["failure_reason"] = record["expected_error"]
    return record


def _audit_line(record: dict) -> str:
    """One audit-ready line in Cybrid Payments' own record vocabulary."""
    return (
        f"transfer {record['guid']} | state={record['state']} | "
        f"source={record['source']} | route={record['route']} | "
        f"destination={record['destination']} | fees={record['fees']} | "
        f"fx_rate={record['fx_rate']} | recipient={record['recipient']} | "
        f"created={record['created_at']} | updated={record['updated_at']} | "
        f"quoteGuid={record['quoteGuid']}"
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/transfers", status_code=201)
def create_transfer(data: TransferCreate) -> dict:
    return _new_transfer(data)


@app.get("/transfers")
def list_transfers(state: str | None = None) -> list[dict]:
    records = list(_store.values())
    if state is not None:
        records = [r for r in records if r["state"] == state]
    return records


@app.get("/transfers/{guid}")
def get_transfer(guid: str) -> dict:
    record = _store.get(guid)
    if record is None:
        raise HTTPException(status_code=404, detail="Transfer not found")
    return record


@app.post("/transfers/{guid}/advance")
def advance_transfer(guid: str, req: AdvanceRequest) -> dict:
    record = _store.get(guid)
    if record is None:
        raise HTTPException(status_code=404, detail="Transfer not found")
    return _advance(record, req.to_state)


@app.get("/transfers/{guid}/audit")
def audit_transfer(guid: str) -> dict:
    record = _store.get(guid)
    if record is None:
        raise HTTPException(status_code=404, detail="Transfer not found")
    return {"guid": guid, "audit_line": _audit_line(record)}


@app.get("/alerts")
def alerts(stuck_after_seconds: float = 0) -> list[dict]:
    """Transfers in non-terminal states past the window (default: any age).

    manual_intervention is always an alert: a human must act. pending and
    in_progress transfers alert once older than stuck_after_seconds.
    """
    now = datetime.now(timezone.utc)
    out = []
    for record in _store.values():
        if record["state"] in TERMINAL_STATES:
            continue
        created = datetime.fromisoformat(record["created_at"])
        age = (now - created).total_seconds()
        if record["state"] == "manual_intervention" or age >= stuck_after_seconds:
            out.append(
                {
                    **record,
                    "alert": "manual_intervention: escalate, do not retry blindly"
                    if record["state"] == "manual_intervention"
                    else f"stuck in {record['state']} for {age:.0f}s",
                }
            )
    return out


# ---------------------------------------------------------------------------
# Scripted scenarios: the 30-second demo
# ---------------------------------------------------------------------------
SCENARIOS = {
    "clean": ["in_progress", "completed"],
    "failed": ["in_progress", "failed"],
    "manual_intervention": ["in_progress", "manual_intervention"],
}


@app.post("/scenarios/run")
def run_scenarios() -> list[dict]:
    """Run the three demo scenarios and return each transfer + audit line."""
    results = []
    for name, steps in SCENARIOS.items():
        record = _new_transfer(
            TransferCreate(
                type="funding",
                quote_guid=f"demo-quote-{name}",
                recipient=f"Demo recipient ({name})",
                expected_error="simulated provider rejection" if name == "failed" else None,
            )
        )
        for step in steps:
            _advance(record, step)
        results.append(
            {
                "scenario": name,
                "transfer": record,
                "audit_line": _audit_line(record),
                "next_action": (
                    "escalate, do not retry blindly"
                    if record["state"] == "manual_intervention"
                    else "none"
                ),
            }
        )
    return results
