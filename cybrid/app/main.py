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
from fastapi.responses import HTMLResponse
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


# ---------------------------------------------------------------------------
# Vercel routing: live evidence (Nov 3 diagnostic) showed requests arrive
# at this app with the path /api/index.py/<original> — Vercel serves this
# app directly, bypassing the prefix stripper in api/index.py. Strip the
# prefix here so the app routes the same on Vercel as it does locally.
# No-op for plain paths.
# ---------------------------------------------------------------------------
@app.middleware("http")
async def _strip_vercel_prefix(request, call_next):
    path = request.scope["path"]
    for prefix in ("/api/index.py", "/api/index"):
        if path == prefix:
            request.scope["path"] = "/"
            break
        if path.startswith(prefix + "/"):
            request.scope["path"] = path[len(prefix):]
            break
    return await call_next(request)


@app.get("/", response_class=HTMLResponse)
def landing() -> str:
    """Front door: an interactive reconciliation explorer, not a JSON dump.

    Loads the three scripted scenarios from /scenarios/run (one stateless
    call, safe on serverless) and renders them as cards with timelines,
    audit lines, and a retry-vs-escalate decision moment on the stuck one.
    """
    return """<!doctype html><html><head><meta charset="utf-8">
<title>Cybrid Transfer-State Reconciliation Harness</title>
<style>
body{font-family:system-ui,sans-serif;max-width:860px;margin:40px auto;padding:0 20px;line-height:1.5;color:#111}
h1{font-size:30px;margin-bottom:4px}.sub{color:#555;margin-top:0}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0}
.card{flex:1;min-width:200px;border:2px solid #ddd;border-radius:10px;padding:14px;cursor:pointer;background:#fff}
.card.sel{border-color:#111;background:#f7f7f7}
.card h3{margin:0 0 4px}.badge{display:inline-block;padding:2px 10px;border-radius:20px;font-size:13px;font-weight:600}
.ok{background:#d8f3dc}.bad{background:#fde2e2}.warn{background:#fff3bf}
.timeline{display:flex;gap:0;margin:16px 0;flex-wrap:wrap}
.step{padding:6px 12px;border:1px solid #ccc;border-radius:20px;margin-right:6px;font-size:14px;color:#999}
.step.hit{background:#111;color:#fff;border-color:#111}
.step.hitbad{background:#b91c1c;color:#fff;border-color:#b91c1c}
.panel{border:1px solid #ddd;border-radius:10px;padding:18px;margin:16px 0}
.audit{background:#111;color:#eee;padding:12px;border-radius:6px;overflow:auto;font-size:13px}
button{padding:10px 18px;font-size:15px;cursor:pointer;margin-right:8px}
.decision{border:2px solid #b91c1c;border-radius:10px;padding:16px;margin:16px 0}
.verdict{padding:12px;border-radius:6px;margin-top:12px;font-weight:600}
.verdict.bad{background:#fde2e2}.verdict.good{background:#d8f3dc}
details{margin-top:16px}pre{background:#111;color:#eee;padding:12px;overflow:auto;font-size:13px}
</style></head><body>
<h1>Cybrid Transfer-State Reconciliation Harness</h1>
<p class="sub">A local mock of Cybrid's Bank API transfer lifecycle: state machine,
stuck-transfer alerts, and audit-ready records. It talks to no Cybrid
service, moves no money, and uses no credentials or customer data.</p>
<p><button onclick="load()">Run the three demo scenarios</button> <a href="/docs">API docs</a></p>
<div id="cards" class="cards"></div>
<div id="detail"></div>
<details><summary>Raw JSON (for engineers)</summary><pre id="raw">Press the button above.</pre></details>
<script>
var DATA=null, SEL=null;
var ORDER=["pending","in_progress","completed","failed","cancelled","reversed","manual_intervention"];
function esc(s){return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;");}
function badge(state){var c=state==="completed"?"ok":(state==="failed"||state==="manual_intervention"?"bad":"warn");return '<span class="badge '+c+'">'+esc(state)+'</span>';}
async function load(){var el=document.getElementById("cards");el.textContent="Running…";
var r=await fetch("/scenarios/run",{method:"POST"});DATA=await r.json();
document.getElementById("raw").textContent=JSON.stringify(DATA,null,2);
el.innerHTML="";DATA.forEach(function(d,i){var t=d.transfer;var div=document.createElement("div");div.className="card";div.id="card-"+i;
div.innerHTML="<h3>"+esc(d.scenario)+"</h3>"+badge(t.state)+"<p style='margin:8px 0 0'>"+esc(t.route)+"<br>"+esc(t.source)+" → "+esc(t.destination)+"</p>";
div.onclick=function(){select(i);};el.appendChild(div);});select(0);}
function select(i){SEL=i;DATA.forEach(function(d,j){document.getElementById("card-"+j).className="card"+(j===i?" sel":"");});
var d=DATA[i],t=d.transfer,det=document.getElementById("detail");
var hist=t.history||[];var tl=ORDER.map(function(s){var cls="step";if(hist.indexOf(s)>=0){cls+=" hit";if(s==="manual_intervention"||s==="failed"){cls+=" hitbad";}}return '<span class="'+cls+'">'+esc(s)+"</span>";}).join(" → ");
var html='<div class="panel"><h2 style="margin-top:0">'+esc(d.scenario)+" transfer</h2>"+badge(t.state)+"<div class='timeline'>"+tl+"</div>"+
"<p><b>Type:</b> "+esc(t.type)+" &nbsp; <b>Fees:</b> "+esc(t.fees)+" &nbsp; <b>FX:</b> "+esc(t.fx_rate)+"<br>"+
"<b>Route:</b> "+esc(t.route)+"<br><b>Recipient:</b> "+esc(t.recipient)+"<br><b>quoteGuid:</b> "+esc(t.quoteGuid)+
(t.failure_reason?"<br><b>Failure reason:</b> "+esc(t.failure_reason):"")+"</p>"+
"<p><b>Audit trail</b></p><div class='audit'>"+esc(d.audit_line)+"</div>";
if(d.scenario==="manual_intervention"){html+='<div class="decision"><h3 style="margin-top:0">Your call: this transfer is stuck</h3>'+
"<p>A provider step went quiet mid-payout. The money may or may not have moved. What do you do?</p>"+
'<button onclick="verdict(false)">Retry it</button><button onclick="verdict(true)">Escalate to a human</button><div id="verdict"></div></div>';}
html+="</div>";det.innerHTML=html;}
function verdict(escalate){var v=document.getElementById("verdict");
if(escalate){v.className="verdict good";v.textContent="Correct. The transfer is frozen for human review with its full audit trail intact. No duplicate payout, no lost money — exactly what the harness flags: escalate, do not retry blindly.";}
else{v.className="verdict bad";v.textContent="Risky. The original transfer may still settle. Retrying blindly is how money gets sent twice — the exact failure this harness exists to catch.";}}
load();
</script></body></html>"""
