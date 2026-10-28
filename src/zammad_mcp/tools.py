"""The six tools, as plain functions over a Zammad client (the MCP wiring is in server.py).

Four only read. The two that change something (add an internal note, update a ticket) never act on the first
call: they return a preview and a one-time confirmation code, and act only when called again with that code and
the same request. Changes go through Zammad's own API as the token's user, so they show in the ticket's history.
"""

import secrets
import time
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from zammad_mcp.client import Zammad, ZammadError

NOTE = "via Claude (Mojood Connect demo)"
CONFIRM_TTL_S = 10 * 60
OPEN_STATES = {"new", "open", "pending reminder", "pending close"}
STATES = ("open", "pending close", "closed")
PRIORITIES = {"low": "1 low", "normal": "2 normal", "high": "3 high"}


class Ticket(BaseModel):
    number: str
    title: str
    state: str
    priority: str
    group: str | None = None
    owner: str | None = Field(None, description="the agent it's assigned to; empty when unassigned")
    customer: str | None = None
    company: str | None = None
    opened: str | None = None
    waiting: str | None = Field(None, description='"on us" when the customer wrote last, "on the customer" when we did')
    since: str | None = Field(None, description="when the last message in that direction was sent")
    reminder: str | None = Field(None, description="for pending tickets: when the reminder is due")
    link: str | None = None


def _people(api: Zammad) -> dict[str, str]:
    """login → "First Last" for everyone, so tickets show names rather than logins."""
    out, page = {}, 1
    while rows := api.get("users", per_page=200, page=page):
        out |= {u["login"]: f"{u['firstname']} {u['lastname']}".strip() for u in rows}
        page += 1
    return out


def _day(v: str | None) -> str | None:
    return v[:16].replace("T", " ") if v else None


def ticket_of(t: dict, names: dict[str, str], base: str) -> Ticket:
    owner = names.get(t.get("owner")) if t.get("owner") not in (None, "-") else None
    cust, agent = t.get("last_contact_customer_at"), t.get("last_contact_agent_at")
    on_us = bool(cust and (not agent or cust > agent))
    return Ticket(
        number=t["number"], title=t["title"], state=t["state"], priority=t["priority"].split(" ", 1)[-1],
        group=t.get("group"), owner=owner, customer=names.get(t.get("customer"), t.get("customer")),
        company=t.get("organization"), opened=_day(t.get("created_at")),
        waiting=None if t["state"] not in OPEN_STATES else "on us" if on_us else "on the customer",
        since=_day(cust if on_us else agent) if t["state"] in OPEN_STATES else None,
        reminder=_day(t.get("pending_time")) if t["state"].startswith("pending") else None,
        link=f"{base}/#ticket/zoom/{t['id']}",
    )


def _all(api: Zammad) -> list[dict]:
    out, page = [], 1
    while rows := api.get("tickets", per_page=100, page=page, expand="true"):
        out += rows
        page += 1
    return out


def _by_number(api: Zammad, number: str) -> dict | None:
    n = number.strip().lstrip("#")
    # Without Elasticsearch, Zammad's search takes plain words only; fall back to scanning the desk.
    hits = [t for t in api.get("tickets/search", query=n, expand="true") if t["number"] == n]
    return hits[0] if hits else next((t for t in _all(api) if t["number"] == n), None)


# ---------- read ----------

class Tickets(BaseModel):
    tickets: list[Ticket]
    total: int


def find_tickets(api: Zammad, query: str | None = None, state: str = "open") -> Tickets:
    rows = api.get("tickets/search", query=query, limit=50, expand="true") if query else _all(api)
    keep = {"open": lambda s: s in OPEN_STATES, "closed": lambda s: s in ("closed", "merged"), "all": lambda s: True}
    rows = [t for t in rows if keep.get(state, keep["open"])(t["state"])]
    names = _people(api)
    return Tickets(tickets=[ticket_of(t, names, api.url) for t in rows[:20]], total=len(rows))


class Message(BaseModel):
    who: str
    when: str | None
    internal: bool = Field(description="an internal note, never shown to the customer")
    text: str


class TicketDetail(BaseModel):
    ticket: Ticket | None = None
    messages: list[Message] = Field(default_factory=list)
    problem: str | None = None


def get_ticket(api: Zammad, number: str) -> TicketDetail:
    t = _by_number(api, number)
    if not t:
        return TicketDetail(problem=f"No ticket has the number {number}.")
    names = _people(api)
    msgs = []
    for a in api.get(f"ticket_articles/by_ticket/{t['id']}"):
        who = names.get(a.get("created_by")) if a["sender"] == "Agent" else (a.get("from") or "").split(" <")[0]
        msgs.append(Message(who=who or a["sender"], when=_day(a["created_at"]), internal=a["internal"],
                            text=(a.get("body") or "")[:800]))
    return TicketDetail(ticket=ticket_of(t, names, api.url), messages=msgs)


class Customer(BaseModel):
    company: str | None = None
    people: list[str] = Field(default_factory=list)
    open_tickets: list[Ticket] = Field(default_factory=list)
    closed_tickets: int = 0
    candidates: list[str] = Field(default_factory=list, description="when the name matched several: ask which")
    problem: str | None = None


def customer_overview(api: Zammad, name: str) -> Customer:
    q = name.strip().lower()
    orgs = [o for o in api.get("organizations", per_page=200) if q in o["name"].lower()]
    users = [u for u in api.get("users/search", query=name, limit=20) if u.get("organization_id") or u.get("role_ids") == [3]]
    if len(orgs) > 1:
        return Customer(candidates=[o["name"] for o in orgs])
    if orgs:
        org = orgs[0]
        test = lambda t: t.get("organization") == org["name"]
        people = [f"{u['firstname']} {u['lastname']}" for u in api.get("users", per_page=200) if u.get("organization_id") == org["id"]]
        company = org["name"]
    elif len(users) == 1:
        login = users[0]["login"]
        test = lambda t: t.get("customer") == login
        people, company = [f"{users[0]['firstname']} {users[0]['lastname']}"], None
    elif users:
        return Customer(candidates=[f"{u['firstname']} {u['lastname']}" for u in users])
    else:
        return Customer(problem=f'No customer or company matches "{name}".')
    rows = [t for t in _all(api) if test(t)]
    names = _people(api)
    open_rows = [t for t in rows if t["state"] in OPEN_STATES]
    return Customer(company=company or (open_rows[0].get("organization") if open_rows else None), people=people,
                    open_tickets=[ticket_of(t, names, api.url) for t in open_rows],
                    closed_tickets=len(rows) - len(open_rows))


class Attention(BaseModel):
    unassigned: list[Ticket] = Field(description="open tickets no agent owns")
    waiting_on_us: list[Ticket] = Field(description="the customer wrote last; oldest first")
    reminders_overdue: list[Ticket] = Field(description="pending tickets whose reminder time has passed")
    high_priority: list[Ticket]


def needs_attention(api: Zammad) -> Attention:
    now = datetime.now(UTC).isoformat()
    names = _people(api)
    rows = [t for t in _all(api) if t["state"] in OPEN_STATES]
    tk = [ticket_of(t, names, api.url) for t in rows]
    by_num = {t["number"]: t for t in rows}
    return Attention(
        unassigned=[t for t in tk if not t.owner],
        waiting_on_us=sorted([t for t in tk if t.waiting == "on us"], key=lambda t: t.since or ""),
        reminders_overdue=[t for t in tk if t.state == "pending reminder" and (by_num[t.number].get("pending_time") or "9") < now],
        high_priority=[t for t in tk if t.priority == "high"],
    )


# ---------- change (preview, then confirm) ----------

class Change(BaseModel):
    done: bool = Field(description="false: nothing has changed yet; true: Zammad has made the change")
    summary: str
    confirmation: str | None = Field(None, description="when done is false: the code to pass back, only after the user says yes")
    expires_in_minutes: int | None = None
    ticket: Ticket | None = None
    problem: str | None = Field(None, description="why it can't be done; nothing was changed")


_pending: dict[str, tuple[float, tuple]] = {}


def _ask(request: tuple, summary: str, ticket: Ticket) -> Change:
    now = time.monotonic()
    for k in [k for k, (t, _) in _pending.items() if now - t > CONFIRM_TTL_S]:
        del _pending[k]
    code = secrets.token_hex(3)
    _pending[code] = (now, request)
    return Change(done=False, summary=summary + " Nothing has changed yet: ask the user to confirm.",
                  confirmation=code, expires_in_minutes=CONFIRM_TTL_S // 60, ticket=ticket)


def _confirmed(code: str, request: tuple) -> bool:
    held = _pending.get(code.strip())
    if not held or time.monotonic() - held[0] > CONFIRM_TTL_S or held[1] != request:
        return False
    del _pending[code.strip()]
    return True


def _expired(summary: str, ticket: Ticket) -> Change:
    return Change(done=False, summary=summary, ticket=ticket,
                  problem="That confirmation code doesn't match this request or has expired. Ask again.")


def add_internal_note(api: Zammad, ticket_number: str, text: str, confirmation: str | None = None) -> Change:
    t = _by_number(api, ticket_number)
    if not t:
        return Change(done=False, summary="", problem=f"No ticket has the number {ticket_number}.")
    if not text.strip():
        return Change(done=False, summary="", problem="The note is empty.")
    names = _people(api)
    tk = ticket_of(t, names, api.url)
    request = ("note", t["id"], text.strip())
    summary = f'Add an internal note to #{tk.number} ("{tk.title}"), which the customer won\'t see: "{text.strip()}"'
    if not confirmation:
        return _ask(request, summary, tk)
    if not _confirmed(confirmation, request):
        return _expired(summary, tk)
    api.post("ticket_articles", {"ticket_id": t["id"], "body": f"{text.strip()}\n\n({NOTE})", "type": "note",
                                 "internal": True, "content_type": "text/plain"})
    return Change(done=True, summary=f"Done: the note is on #{tk.number}.", ticket=tk)


def _agent(api: Zammad, name: str) -> tuple[dict | None, list[str]]:
    agents = [u for u in api.get("users/search", query=name, limit=20) if 2 in (u.get("role_ids") or [])
              and not u["login"].startswith("admin@")]
    exact = [u for u in agents if f"{u['firstname']} {u['lastname']}".lower() == name.strip().lower()]
    if len(exact) == 1 or len(agents) == 1:
        return (exact or agents)[0], []
    return None, [f"{u['firstname']} {u['lastname']}" for u in agents]


def update_ticket(api: Zammad, ticket_number: str, owner: str | None = None, state: str | None = None,
                  priority: str | None = None, confirmation: str | None = None) -> Change:
    t = _by_number(api, ticket_number)
    if not t:
        return Change(done=False, summary="", problem=f"No ticket has the number {ticket_number}.")
    names = _people(api)
    tk = ticket_of(t, names, api.url)
    changes, parts = {}, []
    if owner:
        agent, many = _agent(api, owner)
        if not agent:
            return Change(done=False, summary="", ticket=tk, problem=f'"{owner}" matches {", ".join(many) or "no agent"}. Ask which agent.')
        changes["owner_id"] = agent["id"]
        parts.append(f"assign it to {agent['firstname']} {agent['lastname']}")
        if t["state"] == "new" and not state:
            changes["state"] = "open"
    if state:
        if state not in STATES:
            return Change(done=False, summary="", ticket=tk, problem=f"State must be one of: {', '.join(STATES)}.")
        changes["state"] = state
        parts.append(f"set it to {state}")
    if priority:
        if priority not in PRIORITIES:
            return Change(done=False, summary="", ticket=tk, problem=f"Priority must be one of: {', '.join(PRIORITIES)}.")
        changes["priority"] = PRIORITIES[priority]
        parts.append(f"make it {priority} priority")
    if not parts:
        return Change(done=False, summary="", ticket=tk, problem="Nothing to change: give an owner, a state or a priority.")
    request = ("update", t["id"], tuple(sorted(changes.items())))
    summary = f'On #{tk.number} ("{tk.title}"): ' + ", ".join(parts) + "."
    if not confirmation:
        return _ask(request, summary, tk)
    if not _confirmed(confirmation, request):
        return _expired(summary, tk)
    api.put(f"tickets/{t['id']}", changes)
    fresh = api.get(f"tickets/{t['id']}", expand="true")
    return Change(done=True, summary=f"Done: #{tk.number} updated.", ticket=ticket_of(fresh, names, api.url))


__all__ = [
    "ZammadError",
    "add_internal_note",
    "customer_overview",
    "find_tickets",
    "get_ticket",
    "needs_attention",
    "update_ticket",
]
