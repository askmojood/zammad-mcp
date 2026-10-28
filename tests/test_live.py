"""Against the local Zammad with the SAMPLE desk (scripts/reset.sh). Skipped when it isn't running.

Run: uv run --env-file .env pytest tests/test_live.py
"""

import os

import httpx
import pytest

from zammad_mcp import tools
from zammad_mcp.client import Zammad


def _up() -> bool:
    try:
        return bool(os.environ.get("ZAMMAD_TOKEN")) and httpx.get(
            os.environ.get("ZAMMAD_URL", "http://127.0.0.1:8090") + "/", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not _up(), reason="local Zammad not running (scripts/up.sh)")


@pytest.fixture(scope="module")
def api():
    return Zammad()


def test_al_noor_has_three_open_tickets(api):
    c = tools.customer_overview(api, "Al Noor")
    assert c.company == "Al Noor Hotels" and len(c.open_tickets) == 3 and c.closed_tickets == 1


def test_the_seeded_desk_needs_attention(api):
    n = tools.needs_attention(api)
    assert n.unassigned and n.waiting_on_us and len(n.reminders_overdue) == 2 and n.high_priority


def test_note_on_a_closed_ticket_lands_in_its_history(api):
    t = tools.find_tickets(api, "2027", state="closed").tickets[0]
    p = tools.add_internal_note(api, t.number, "Live test note.")
    assert tools.add_internal_note(api, t.number, "Live test note.", confirmation=p.confirmation).done
    last = tools.get_ticket(api, t.number).messages[-1]
    assert last.internal and last.text.startswith("Live test note.") and tools.NOTE in last.text
