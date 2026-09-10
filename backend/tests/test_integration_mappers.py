from datetime import UTC, datetime

import pytest

from app.integrations.github import mapper as gh
from app.integrations.pagerduty import mapper as pd


class TestRollbackDetection:
    @pytest.mark.parametrize(
        "message",
        [
            'Revert "feat: add retry budget"',
            "revert: bad migration",
            "Rollback payments deploy",
            "  revert the thing",
        ],
    )
    def test_recognised_rollback_messages(self, message):
        assert gh.is_rollback(message) is True

    @pytest.mark.parametrize(
        "message",
        [
            "feat: add retry budget",
            "fix: reverted-to-baseline config naming",
            "docs: explain how to revert a deploy",
            "",
            None,
        ],
    )
    def test_messages_that_are_not_rollbacks(self, message):
        """'revert' has to lead the message — a deploy that merely mentions
        reverting in prose is not itself a rollback."""
        assert gh.is_rollback(message) is False

    def test_extracts_the_reverted_sha(self):
        message = 'Revert "feat: x"\n\nThis reverts commit 1a2b3c4d5e6f7890.'
        assert gh.reverted_sha(message) == "1a2b3c4d5e6f7890"

    def test_no_sha_when_absent(self):
        assert gh.reverted_sha('Revert "feat: x"') is None


class TestDeployMapping:
    def test_maps_a_deployment(self):
        payload = {
            "id": 42,
            "sha": "abc123",
            "ref": "main",
            "environment": "production",
            "created_at": "2026-09-09T10:00:00Z",
            "creator": {"id": 7, "login": "ada"},
        }
        deploy = gh.map_deployment(
            payload, "acme/api", state="success", commit_message="feat: ship", pr_number=11
        )

        assert deploy.external_id == "acme/api:42"
        assert deploy.repo_full_name == "acme/api"
        assert deploy.deployed_at == datetime(2026, 9, 9, 10, 0, tzinfo=UTC)
        assert deploy.status == "success"
        assert deploy.actor_external_id == "7"
        assert deploy.pr_number == 11
        assert deploy.is_rollback is False

    def test_non_success_states_are_failures(self):
        payload = {"id": 1, "created_at": "2026-09-09T10:00:00Z"}
        assert gh.map_deployment(payload, "acme/api", state="error").status == "failure"

    def test_active_counts_as_success(self):
        payload = {"id": 1, "created_at": "2026-09-09T10:00:00Z"}
        assert gh.map_deployment(payload, "acme/api", state="active").status == "success"


class TestIncidentMapping:
    def test_maps_core_fields(self):
        payload = {
            "id": "PINC1",
            "title": "Checkout 5xx",
            "status": "resolved",
            "urgency": "high",
            "created_at": "2026-09-09T10:00:00Z",
            "resolved_at": "2026-09-09T11:30:00Z",
            "service": {"id": "PSVC1", "summary": "Payments"},
            "priority": {"summary": "P1"},
            "acknowledgements": [{"at": "2026-09-09T10:05:00Z"}],
        }
        incident = pd.map_incident(payload)

        assert incident.external_id == "PINC1"
        assert incident.service_external_id == "PSVC1"
        assert incident.severity == "P1"
        assert incident.acknowledged_at == datetime(2026, 9, 9, 10, 5, tzinfo=UTC)
        assert incident.resolved_at == datetime(2026, 9, 9, 11, 30, tzinfo=UTC)

    def test_falls_back_to_last_status_change_when_resolved_at_is_absent(self):
        payload = {
            "id": "PINC2",
            "title": "x",
            "status": "resolved",
            "created_at": "2026-09-09T10:00:00Z",
            "last_status_change_at": "2026-09-09T12:00:00Z",
        }
        assert pd.map_incident(payload).resolved_at == datetime(2026, 9, 9, 12, 0, tzinfo=UTC)

    def test_open_incident_has_no_resolution(self):
        payload = {
            "id": "PINC3",
            "title": "x",
            "status": "triggered",
            "created_at": "2026-09-09T10:00:00Z",
            "last_status_change_at": "2026-09-09T10:01:00Z",
        }
        assert pd.map_incident(payload).resolved_at is None


class TestPageMapping:
    def test_notification_and_ack_entries_become_pages(self):
        entries = [
            {
                "id": "L1",
                "type": "notify_log_entry",
                "created_at": "2026-09-09T10:00:00Z",
                "user": {"id": "PU1"},
                "channel": {"type": "sms"},
            },
            {
                "id": "L2",
                "type": "acknowledge_log_entry",
                "created_at": "2026-09-09T10:05:00Z",
                "user": {"id": "PU1"},
            },
        ]
        pages = pd.map_pages("PINC1", entries)

        assert len(pages) == 2
        assert pages[0].external_user_id == "PU1"
        assert pages[0].channel == "sms"
        assert pages[0].is_ack is False
        assert pages[1].is_ack is True

    def test_unrelated_log_entries_are_skipped(self):
        entries = [{"id": "L3", "type": "trigger_log_entry", "created_at": "2026-09-09T10:00:00Z"}]
        assert pd.map_pages("PINC1", entries) == []


class TestOnCallMapping:
    def test_maps_a_bounded_shift(self):
        payload = {
            "start": "2026-09-07T09:00:00Z",
            "end": "2026-09-14T09:00:00Z",
            "user": {"id": "PU1", "summary": "Ada"},
            "schedule": {"id": "PSCH1", "summary": "Platform on-call"},
        }
        shift = pd.map_oncall(payload)

        assert shift is not None
        assert shift.external_user_id == "PU1"
        assert shift.schedule_external_id == "PSCH1"

    def test_permanent_escalation_membership_is_not_a_shift(self):
        """Entries with no start/end are policy membership, not time on call —
        counting them would show people as permanently on-call."""
        payload = {"start": None, "end": None, "user": {"id": "PU1"}, "schedule": None}
        assert pd.map_oncall(payload) is None
