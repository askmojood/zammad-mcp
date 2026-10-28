"""Unit tests over a fake Zammad API (httpx.MockTransport): no Docker needed."""

import json

import httpx
import pytest

from zammad_mcp import tools
from zammad_mcp.client import Zammad, ZammadError

USERS = [
    {"id": 1, "login": "admin@harbor-trading.example", "firstname": "Claude", "lastname": "Connector", "role_ids": [1, 2]},
    {"id": 3, "login": "karim.nasser@harbor-trading.example", "firstname": "Karim", "lastname": "Nasser", "role_ids": [2]},
    {"id": 9, "login": "mona.farouk@al-noor.example", "firstname": "Mona", "lastname": "Farouk", "role_ids": [3], "organization_id": 2},
]
TICKET = {"id": 2, "number": "65002", "title": "Wrong size on 40 room safes", "state": "open", "priority": "3 high",
          "group": "Deliveries", "owner": "-", "customer": "mona.farouk@al-noor.example", "organization": "Al Noor Hotels",
          "created_at": "2026-10-27T09:43:00Z", "last_contact_customer_at": "2026-10-27T09:43:00Z",
          "last_contact_agent_at": None, "pending_time": None}


class Fake:
    def __init__(self):
        self.ticket = dict(TICKET)
        self.writes: list[tuple[str, str, dict]] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path.removeprefix("/api/v1/")
        if req.method in ("POST", "PUT"):
            body = json.loads(req.content)
            self.writes.append((req.method, path, body))
            if req.method == "PUT" and "owner_id" in body:
                self.ticket["owner"] = next(u["login"] for u in USERS if u["id"] == body["owner_id"])
            return httpx.Response(200, json={"id": 1})
        if path == "users":
            return httpx.Response(200, json=USERS if req.url.params.get("page") == "1" else [])
        if path == "users/search":
            q = req.url.params["query"].lower()
            return httpx.Response(200, json=[u for u in USERS if q in f"{u['firstname']} {u['lastname']}".lower()])
        if path == "tickets":
            return httpx.Response(200, json=[self.ticket] if req.url.params.get("page") == "1" else [])
        if path == "tickets/search":
            return httpx.Response(200, json=[])
        if path == "tickets/2":
            return httpx.Response(200, json=self.ticket)
        if path == "ticket_articles/by_ticket/2":
            return httpx.Response(200, json=[{"sender": "Customer", "from": "Mona Farouk <mona.farouk@al-noor.example>",
                                              "created_at": "2026-10-27T09:43:00Z", "internal": False, "body": "Exchange them, please."}])
        if path == "nope":
            return httpx.Response(401, json={"error": "Not authorized"})
        return httpx.Response(404)


@pytest.fixture
def fake():
    return Fake()


def api(fake: Fake) -> Zammad:
    return Zammad("http://zammad.test", "token", transport=httpx.MockTransport(fake))


def test_needs_a_token(monkeypatch):
    monkeypatch.delenv("ZAMMAD_TOKEN", raising=False)
    with pytest.raises(ZammadError):
        Zammad("http://zammad.test", "")


def test_errors_carry_zammads_message(fake):
    with pytest.raises(ZammadError, match="Not authorized"):
        api(fake).get("nope")


def test_ticket_reads_names_and_who_it_waits_on(fake):
    t = tools.ticket_of(TICKET, {u["login"]: f"{u['firstname']} {u['lastname']}" for u in USERS}, "http://zammad.test")
    assert (t.priority, t.owner, t.customer, t.waiting) == ("high", None, "Mona Farouk", "on us")
    answered = dict(TICKET, last_contact_agent_at="2026-10-27T10:00:00Z")
    assert tools.ticket_of(answered, {}, "x").waiting == "on the customer"
    assert tools.ticket_of(dict(TICKET, state="closed"), {}, "x").waiting is None


def test_get_ticket_by_number_falls_back_to_the_desk(fake):
    d = tools.get_ticket(api(fake), "#65002")
    assert d.ticket.number == "65002" and d.messages[0].who == "Mona Farouk"
    assert tools.get_ticket(api(fake), "1").problem


def test_needs_attention_lists_unassigned_and_waiting(fake):
    n = tools.needs_attention(api(fake))
    assert [t.number for t in n.unassigned] == [t.number for t in n.waiting_on_us] == ["65002"]
    assert [t.number for t in n.high_priority] == ["65002"]


def test_note_changes_nothing_without_a_code(fake):
    c = tools.add_internal_note(api(fake), "65002", "Ships Thursday.")
    assert not c.done and c.confirmation and "won't see" in c.summary
    assert fake.writes == []


def test_note_with_the_code_is_internal_and_marked(fake):
    a = api(fake)
    code = tools.add_internal_note(a, "65002", "Ships Thursday.").confirmation
    assert tools.add_internal_note(a, "65002", "Ships Thursday.", confirmation=code).done
    (method, path, body), = fake.writes
    assert (method, path, body["internal"], body["type"]) == ("POST", "ticket_articles", True, "note")
    assert tools.NOTE in body["body"]
    assert not tools.add_internal_note(a, "65002", "Ships Thursday.", confirmation=code).done  # used once


def test_a_code_only_fits_its_own_request(fake):
    a = api(fake)
    code = tools.add_internal_note(a, "65002", "Ships Thursday.").confirmation
    assert not tools.add_internal_note(a, "65002", "Ships Friday.", confirmation=code).done
    assert not tools.update_ticket(a, "65002", owner="Karim", confirmation=code).done
    assert fake.writes == []


def test_assign_previews_then_assigns(fake):
    a = api(fake)
    p = tools.update_ticket(a, "65002", owner="Karim")
    assert not p.done and "Karim Nasser" in p.summary and fake.writes == []
    d = tools.update_ticket(a, "65002", owner="Karim", confirmation=p.confirmation)
    assert d.done and d.ticket.owner == "Karim Nasser"
    assert fake.writes == [("PUT", "tickets/2", {"owner_id": 3})]


def test_the_token_user_is_never_an_assignee(fake):
    assert "no agent" in tools.update_ticket(api(fake), "65002", owner="Claude").problem


def test_an_expired_code_is_refused(fake, monkeypatch):
    a = api(fake)
    code = tools.update_ticket(a, "65002", priority="normal").confirmation
    monkeypatch.setattr(tools, "CONFIRM_TTL_S", -1)
    assert not tools.update_ticket(a, "65002", priority="normal", confirmation=code).done
    assert fake.writes == []


def test_bad_state_and_empty_changes(fake):
    assert "State must be" in tools.update_ticket(api(fake), "65002", state="deleted").problem
    assert "Nothing to change" in tools.update_ticket(api(fake), "65002").problem
