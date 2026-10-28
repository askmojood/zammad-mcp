"""Zammad MCP server (Mojood Connect demo): ask about the support desk in plain words, and add notes or update
tickets with a confirmation step.

Run:  uv run --env-file .env zammad-mcp          → http://127.0.0.1:8003/mcp (Streamable HTTP)
      uv run --env-file .env zammad-mcp --stdio  → for Claude Desktop's config file

Settings (environment, written to .env by scripts/up.sh):
  ZAMMAD_URL      the Zammad instance (default http://127.0.0.1:8090)
  ZAMMAD_TOKEN    a Zammad API token; the server acts as that token's user
  ZAMMAD_SAMPLE   "1" (default) says in every session that the data is SAMPLE
  ZAMMAD_MCP_PORT default 8003
"""

import logging
import os
import sys
from typing import Annotated, Literal

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field

from zammad_mcp import tools
from zammad_mcp.client import Zammad

SAMPLE = os.environ.get("ZAMMAD_SAMPLE", "1") != "0"
_api: Zammad | None = None


def api() -> Zammad:
    global _api
    if _api is None:
        _api = Zammad()
    return _api


INSTRUCTIONS = f"""\
Zammad helpdesk: tickets, their messages, customers and their companies, and what needs attention on the desk.
{"This is a demo with SAMPLE data for a made-up company, Harbor Trading. " if SAMPLE else ""}\
Answer only from these tools; never guess a ticket number, a customer or what someone wrote. Ticket numbers are
digits, e.g. 65002. add_internal_note and update_ticket change real tickets. Call one without `confirmation` first:
it changes nothing and returns what it would do plus a code. Show the user that summary and ask them to confirm.
Only after they say yes, call again with the same arguments and the code. Never confirm on the user's behalf. If a
tool returns `problem`, nothing changed: tell the user why. Never send anything to a customer: there is no tool
for it."""

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
CHANGE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)

server = MCPServer(
    name="zammad-mcp",
    title="Zammad",
    description="Helpdesk tickets in Zammad: find and read tickets, customers, what needs attention, notes and updates.",
    instructions=INSTRUCTIONS,
    website_url="https://mojood.app/connect",
    version="0.1.0",
)


@server.tool(title="Find tickets", annotations=READ)
def find_tickets(
    query: Annotated[str | None, Field(description='words from the title or messages, e.g. "invoice" or "helmets"')] = None,
    state: Annotated[Literal["open", "closed", "all"], Field(description="open includes new and pending")] = "open",
) -> tools.Tickets:
    """Find tickets by words, or list them all. Each comes with its state, priority, owner, customer, company and
    whether it's waiting on us or on the customer."""
    return tools.find_tickets(api(), query, state)


@server.tool(title="Read a ticket", annotations=READ)
def get_ticket(number: Annotated[str, Field(description='the ticket number, e.g. "65002"')]) -> tools.TicketDetail:
    """One ticket with every message in order: who wrote it, when, and whether it was an internal note."""
    return tools.get_ticket(api(), number)


@server.tool(title="A customer's tickets", annotations=READ)
def customer_overview(
    name: Annotated[str, Field(description='a company ("Al Noor Hotels") or a person ("Mona Farouk")')],
) -> tools.Customer:
    """A customer company or person: its people, its open tickets and how many are closed. If the name matches
    several, returns them as candidates: ask which."""
    return tools.customer_overview(api(), name)


@server.tool(title="What needs attention", annotations=READ)
def needs_attention() -> tools.Attention:
    """Open tickets no one owns, tickets waiting on us (oldest first), pending reminders that are overdue, and high
    priority tickets."""
    return tools.needs_attention(api())


@server.tool(title="Add an internal note", annotations=CHANGE)
def add_internal_note(
    ticket_number: Annotated[str, Field(description='e.g. "65002"')],
    text: Annotated[str, Field(description="the note, for agents only; the customer never sees it")],
    confirmation: Annotated[str | None, Field(description="leave empty first; pass the code only after the user confirms")] = None,
) -> tools.Change:
    """Add an internal note to a ticket. The first call changes nothing and returns a summary and a confirmation
    code; the note is added only on a second call with the code, after the user has said yes."""
    return tools.add_internal_note(api(), ticket_number, text, confirmation)


@server.tool(title="Update a ticket", annotations=CHANGE)
def update_ticket(
    ticket_number: Annotated[str, Field(description='e.g. "65002"')],
    owner: Annotated[str | None, Field(description="an agent's name, to assign it")] = None,
    state: Annotated[Literal["open", "pending close", "closed"] | None, Field(description="new state")] = None,
    priority: Annotated[Literal["low", "normal", "high"] | None, Field(description="new priority")] = None,
    confirmation: Annotated[str | None, Field(description="leave empty first; pass the code only after the user confirms")] = None,
) -> tools.Change:
    """Assign a ticket, change its state or its priority. The first call changes nothing and returns a summary and a
    confirmation code; the change happens only on a second call with the code, after the user has said yes."""
    return tools.update_ticket(api(), ticket_number, owner, state, priority, confirmation)


def app():
    security = TransportSecuritySettings(
        allowed_hosts=["127.0.0.1:*", "localhost:*"],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*"],
    )
    # Stateful sessions: a confirmation code must reach the same server process that issued it.
    return server.streamable_http_app(json_response=True, transport_security=security)


def main() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per Zammad call is noise in a client's log
    if "--stdio" in sys.argv:
        server.run("stdio")
        return
    uvicorn.run(app(), host="127.0.0.1", port=int(os.environ.get("ZAMMAD_MCP_PORT", "8003")), log_level="info",
                timeout_graceful_shutdown=5)
