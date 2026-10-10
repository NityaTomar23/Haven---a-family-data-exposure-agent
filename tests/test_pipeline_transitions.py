"""Human-in-the-loop status transitions.

The whole compliance story rests on this: nothing may reach 'sent' without an
explicit approval step, so every illegal edge of the state machine is asserted
to raise rather than silently advance.
"""

from __future__ import annotations

import pytest

from haven.models import RemovalAction
from haven.pipeline import approve_action, mark_confirmed, mark_sent

from conftest import make_action, make_exposure, make_procedure


@pytest.mark.parametrize("start", ["sent", "confirmed_removed", "rejected", "pending"])
def test_only_drafted_actions_can_be_approved(action: RemovalAction, start: str):
    action.status = start  # type: ignore[assignment]

    with pytest.raises(ValueError, match="Cannot approve"):
        approve_action(action)


def test_approve_moves_drafted_to_approved(action: RemovalAction):
    result = approve_action(action)

    assert result is action
    assert action.status == "approved"


def test_approving_twice_is_rejected(action: RemovalAction):
    approve_action(action)

    with pytest.raises(ValueError, match="Cannot approve action in status 'approved'"):
        approve_action(action)


@pytest.mark.parametrize("start", ["drafted", "confirmed_removed", "rejected", "pending"])
def test_only_approved_actions_can_be_marked_sent(action: RemovalAction, start: str):
    action.status = start  # type: ignore[assignment]

    with pytest.raises(ValueError, match="action must be 'approved'"):
        mark_sent(action)


def test_marking_sent_requires_prior_human_approval(action: RemovalAction):
    """The error must say what is missing, because a human reads it in the UI."""
    with pytest.raises(ValueError, match="Human approval is required"):
        mark_sent(action)


def test_mark_sent_moves_approved_to_sent(action: RemovalAction):
    approve_action(action)

    result = mark_sent(action)

    assert result is action
    assert action.status == "sent"


@pytest.mark.parametrize("start", ["drafted", "approved", "rejected", "pending"])
def test_only_sent_actions_can_be_confirmed(action: RemovalAction, start: str):
    action.status = start  # type: ignore[assignment]

    with pytest.raises(ValueError, match="action must be 'sent'"):
        mark_confirmed(action)


def test_mark_confirmed_moves_sent_to_confirmed_removed(action: RemovalAction):
    approve_action(action)
    mark_sent(action)

    result = mark_confirmed(action)

    assert result is action
    assert action.status == "confirmed_removed"


def test_full_lifecycle_in_order(action: RemovalAction):
    assert action.status == "drafted"
    approve_action(action)
    assert action.status == "approved"
    mark_sent(action)
    assert action.status == "sent"
    mark_confirmed(action)
    assert action.status == "confirmed_removed"


def test_transitions_never_touch_the_draft_text(action: RemovalAction):
    original = action.draft
    approve_action(action)
    mark_sent(action)
    mark_confirmed(action)

    assert action.draft == original


def test_transitions_stamp_updated_at(action: RemovalAction):
    original_updated = action.updated_at
    approve_action(action)

    assert action.updated_at >= original_updated


def test_a_freshly_built_action_satisfies_the_state_machine():
    """Guard against the builders drifting away from the real draft output."""
    exposure = make_exposure()
    action = make_action(exposure, make_procedure(exposure))

    assert approve_action(action).status == "approved"
    assert mark_sent(action).status == "sent"
    assert mark_confirmed(action).status == "confirmed_removed"
