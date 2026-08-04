"""API surface.

Includes the safety check that matters most for an HTTP interface: no route
places a bet or touches a bookmaker account.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from betmaxxing.config import Settings


@pytest.fixture
def client(env_settings: Settings) -> Iterator[TestClient]:
    from betmaxxing.api.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


class TestHealth:
    def test_root_reports_mode_and_disclaimer(self, client: TestClient) -> None:
        payload = client.get("/").json()
        assert payload["mode"] == "demo"
        assert "Aucune garantie de gain" in payload["disclaimer"]

    def test_health_endpoint(self, client: TestClient) -> None:
        payload = client.get("/health").json()
        assert payload["status"] == "ok"
        assert payload["config_fingerprint"]

    def test_providers_endpoint_lists_demo_providers(self, client: TestClient) -> None:
        payload = client.get("/providers").json()
        assert payload["available"] is True
        assert any(p["name"] == "demo" for p in payload["providers"])

    def test_models_endpoint_exposes_validation_status(self, client: TestClient) -> None:
        payload = client.get("/models").json()
        assert payload["models"]
        assert all(m["validation_status"] == "BACKTEST_ONLY" for m in payload["models"])


class TestScans:
    def test_creating_a_scan_returns_a_full_result(self, client: TestClient) -> None:
        payload = client.post("/scans").json()
        assert payload["status"] in {"CANDIDATES_FOUND", "NO_BET", "DATA_UNAVAILABLE"}
        assert "candidates" in payload
        assert "rejections_summary" in payload
        assert "disclaimer" in payload

    def test_scan_is_retrievable_afterwards(self, client: TestClient) -> None:
        scan_id = client.post("/scans").json()["scan_id"]
        payload = client.get(f"/scans/{scan_id}").json()
        assert payload["scan_id"] == scan_id

    def test_listing_scans(self, client: TestClient) -> None:
        client.post("/scans")
        rows = client.get("/scans").json()
        assert len(rows) >= 1
        assert "config_fingerprint" in rows[0]

    def test_rejections_endpoint_exposes_codes(self, client: TestClient) -> None:
        scan_id = client.post("/scans").json()["scan_id"]
        rejections = client.get(f"/scans/{scan_id}/rejections").json()
        assert rejections
        assert all(r["code"] and r["detail"] for r in rejections)

    def test_csv_export_contains_the_audit_columns(self, client: TestClient) -> None:
        scan_id = client.post("/scans").json()["scan_id"]
        response = client.get(f"/scans/{scan_id}/export.csv")
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        header = response.text.splitlines()[0]
        for column in ("ev", "ev_conservative", "model_id", "validation_status"):
            assert column in header

    def test_unknown_scan_is_a_404(self, client: TestClient) -> None:
        assert client.get("/scans/nope").status_code == 404


class TestSettingsEndpoints:
    def test_thresholds_are_marked_provisional(self, client: TestClient) -> None:
        payload = client.get("/settings/thresholds").json()
        assert payload["status"] == "PROVISIONAL"
        assert payload["thresholds"]["min_ev"] == 0.03

    def test_settings_endpoint_masks_secrets(self, client: TestClient) -> None:
        payload = client.get("/settings").json()
        body = str(payload)
        for field in ("odds_api_key", "telegram_bot_token", "smtp_password"):
            assert field in payload["settings"]
        assert "SUPER" not in body

    def test_responsible_gambling_endpoint_states_the_principles(self, client: TestClient) -> None:
        payload = client.get("/responsible-gambling").json()
        joined = " ".join(payload["principles"])
        assert "martingale" in joined
        assert "ne place aucun pari" in joined


class TestChallengeEndpoints:
    def _create(self, client: TestClient) -> str:
        response = client.post(
            "/challenges",
            json={"initial_bank": 100.0, "target_bank": 400.0, "max_odds": 3.0},
        )
        assert response.status_code == 200
        return response.json()["challenge_id"]

    def test_create_and_read(self, client: TestClient) -> None:
        challenge_id = self._create(client)
        payload = client.get(f"/challenges/{challenge_id}").json()
        assert payload["state"] == "DRAFT"
        assert payload["bank"] == 100.0

    def test_invalid_configuration_is_rejected(self, client: TestClient) -> None:
        response = client.post("/challenges", json={"initial_bank": 100.0, "target_bank": 50.0})
        assert response.status_code == 422

    def test_activation_moves_to_waiting(self, client: TestClient) -> None:
        challenge_id = self._create(client)
        payload = client.post(f"/challenges/{challenge_id}/activate").json()
        assert payload["state"] == "WAITING_FOR_CANDIDATE"

    def test_propose_requires_manual_confirmation(self, client: TestClient) -> None:
        challenge_id = self._create(client)
        client.post(f"/challenges/{challenge_id}/activate")
        payload = client.post(f"/challenges/{challenge_id}/propose").json()
        if payload["decision"] == "PROPOSED":
            assert payload["requires_manual_confirmation"] is True
            assert payload["challenge"]["state"] == "AWAITING_USER_CONFIRMATION"
        else:
            assert payload["decision"] == "WAIT"
            assert "Aucun seuil n'est abaissé" in payload["reason"]

    def test_stop_is_always_available(self, client: TestClient) -> None:
        challenge_id = self._create(client)
        payload = client.post(f"/challenges/{challenge_id}/stop").json()
        assert payload["state"] == "STOPPED"

    def test_confirm_without_a_proposal_is_a_conflict(self, client: TestClient) -> None:
        challenge_id = self._create(client)
        response = client.post(f"/challenges/{challenge_id}/confirm", json={"accepted_odds": 2.0})
        assert response.status_code == 409

    def test_unknown_challenge_is_a_404(self, client: TestClient) -> None:
        assert client.get("/challenges/nope").status_code == 404

    def test_view_carries_the_responsible_gambling_note(self, client: TestClient) -> None:
        challenge_id = self._create(client)
        payload = client.get(f"/challenges/{challenge_id}").json()
        assert "Aucune garantie" in payload["note"]
        assert "récupération" in payload["note"]


class TestNoBettingEndpoints:
    def test_no_route_can_place_a_bet(self, client: TestClient) -> None:
        """Structural guarantee, asserted against the generated OpenAPI schema."""
        schema = client.get("/openapi.json").json()
        forbidden = ("bet", "wager", "placer", "bookmaker", "deposit", "withdraw")
        for path in schema["paths"]:
            # `/challenges/...` records a *simulated* bet the user placed
            # themselves; nothing here transmits an order anywhere.
            assert not any(word in path.lower() for word in forbidden)

    def test_openapi_documents_the_no_bet_guarantee(self, client: TestClient) -> None:
        schema = client.get("/openapi.json").json()
        assert "ne place aucun pari" in schema["info"]["description"]

    def test_only_read_and_local_write_methods_are_exposed(self, client: TestClient) -> None:
        schema = client.get("/openapi.json").json()
        methods = {m for path in schema["paths"].values() for m in path}
        assert methods <= {"get", "post"}
