from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _create(**overrides):
    payload = {"type": "funding", "quote_guid": "quote-123"}
    payload.update(overrides)
    response = client.post("/transfers", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_requires_known_type_and_links_quote():
    created = _create()
    assert created["state"] == "pending"
    assert created["quoteGuid"] == "quote-123"
    assert created["history"] == ["pending"]

    bad = client.post("/transfers", json={"type": "wire", "quote_guid": "q"})
    assert bad.status_code == 422


def test_state_machine_allows_valid_path_and_rejects_illegal_jump():
    created = _create()
    guid = created["guid"]

    # pending -> completed is not a legal jump; must pass through in_progress.
    illegal = client.post(f"/transfers/{guid}/advance", json={"to_state": "completed"})
    assert illegal.status_code == 409

    ok = client.post(f"/transfers/{guid}/advance", json={"to_state": "in_progress"})
    assert ok.status_code == 200
    assert ok.json()["state"] == "in_progress"

    done = client.post(f"/transfers/{guid}/advance", json={"to_state": "completed"})
    assert done.json()["state"] == "completed"
    assert done.json()["history"] == ["pending", "in_progress", "completed"]

    # Terminal states cannot move again.
    stuck = client.post(f"/transfers/{guid}/advance", json={"to_state": "reversed"})
    assert stuck.status_code == 409


def test_reversed_branch_from_in_progress():
    created = _create()
    guid = created["guid"]
    client.post(f"/transfers/{guid}/advance", json={"to_state": "in_progress"})
    response = client.post(f"/transfers/{guid}/advance", json={"to_state": "reversed"})
    assert response.status_code == 200
    assert response.json()["state"] == "reversed"


def test_scenarios_land_in_expected_states():
    response = client.post("/scenarios/run")
    assert response.status_code == 200
    by_name = {r["scenario"]: r for r in response.json()}
    assert by_name["clean"]["transfer"]["state"] == "completed"
    assert by_name["failed"]["transfer"]["state"] == "failed"
    assert by_name["failed"]["transfer"]["failure_reason"] == "simulated provider rejection"
    assert by_name["manual_intervention"]["transfer"]["state"] == "manual_intervention"
    assert by_name["manual_intervention"]["next_action"] == "escalate, do not retry blindly"
    # Every scenario transfer keeps its quote link.
    for name, result in by_name.items():
        assert result["transfer"]["quoteGuid"] == f"demo-quote-{name}"


def test_alerts_flag_manual_intervention_but_not_terminal_transfers():
    client.post("/scenarios/run")
    alerts = client.get("/alerts").json()
    flagged = {a["scenario"] if "scenario" in a else a["state"] for a in alerts}
    states = [a["state"] for a in alerts]
    assert "manual_intervention" in states
    assert "completed" not in states
    assert "failed" not in states


def test_audit_line_uses_cybrid_record_vocabulary():
    created = _create(
        source="USD account",
        route="USD -> USDC -> local payout",
        destination="Recipient bank",
        recipient="Demo recipient",
        fees="0.20%",
        fx_rate="mid-market (demo value, not a live rate)",
    )
    response = client.get(f"/transfers/{created['guid']}/audit")
    assert response.status_code == 200
    line = response.json()["audit_line"]
    for field in ("source=", "route=", "destination=", "fees=", "fx_rate=",
                  "recipient=", "quoteGuid=quote-123"):
        assert field in line


def test_get_missing_transfer_returns_404():
    response = client.get("/transfers/does-not-exist")
    assert response.status_code == 404
