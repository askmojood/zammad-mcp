# Zammad MCP server

Ask Claude about your support desk in plain words: what's open for a customer, what needs attention, what a
ticket says. Assign tickets and add internal notes from the same chat, with a confirmation step before anything
changes. There is no tool that writes to a customer.

Built by [Mojood Connect](https://mojood.app/connect) as a working demo for [Zammad](https://zammad.com). It runs
against any Zammad through its REST API. This repository includes a local Zammad with **SAMPLE data** for the
support desk of a made-up company, Harbor Trading, so you can try it without touching a real instance.

## Tools

| Tool | What it does | Changes anything? |
| --- | --- | --- |
| `find_tickets` | Find tickets by words, or list them: state, priority, owner, customer, company, and whether each is waiting on us or on the customer | No |
| `get_ticket` | One ticket with every message in order, internal notes marked | No |
| `customer_overview` | A company or person: its people, open tickets and how many are closed; asks which when a name matches several | No |
| `needs_attention` | Tickets with no owner, tickets waiting on us (oldest first), overdue pending reminders, high priority | No |
| `add_internal_note` | An internal note on a ticket, never shown to the customer | Yes, after confirmation |
| `update_ticket` | Assign a ticket, or change its state or priority | Yes, after confirmation |

**How changes are made safe.** A call to `add_internal_note` or `update_ticket` without a `confirmation` changes
nothing: it returns a plain summary ("On #43002 ("Wrong size on 40 room safes, order HT-SO-5521"): assign it to
Karim Nasser.") and a one-time code. The change happens only when the same request comes back with that code,
within 10 minutes. A code works once, and only for the request it was issued for. The server's instructions tell
the model to show the summary and wait for the user's yes. Notes carry "via Claude (Mojood Connect demo)" and every
change shows in the ticket's history under the token's user.

The server acts as the user who owns the API token, with that user's Zammad permissions.

## Try it locally

Needs Docker (with Compose), [uv](https://docs.astral.sh/uv/) and Python 3.13. Zammad wants about 4 GB of memory.

```
scripts/reset.sh                         # local Zammad on http://localhost:8090, filled with the SAMPLE desk
uv run --env-file .env zammad-mcp        # MCP server on http://127.0.0.1:8003/mcp (Streamable HTTP)
```

`docker/compose.yml` is Zammad's own compose file (zammad-docker-compose v17.5.4) unchanged;
`docker/compose.override.yml` keeps the port on 127.0.0.1, drops the backup container and Elasticsearch (Zammad
then searches its own database). `scripts/reset.sh` generates every password and the API token itself and keeps
them in the git-ignored files `docker/.env` and `.env`; nothing is printed. `scripts/up.sh` starts it again after a
restart without touching the data.

**Claude Desktop:** add this to `claude_desktop_config.json` (Settings › Developer), with the path to this folder:

```json
{
  "mcpServers": {
    "zammad": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/zammad-mcp", "--env-file", "/path/to/zammad-mcp/.env", "zammad-mcp", "--stdio"]
    }
  }
}
```

Then ask: "What's open for Al Noor Hotels?", "What needs attention on the desk?", "Give the room safes ticket to
Karim, and note that the 20 litre safes ship Thursday."

**Your own Zammad:** set `ZAMMAD_URL`, `ZAMMAD_TOKEN` (a token from your profile's Token Access) and
`ZAMMAD_SAMPLE=0`.

## The SAMPLE desk

Harbor Trading's support desk: three groups (Orders, Deliveries, Billing), four agents, six customer companies,
seven customer contacts and 15 tickets. Message times are set relative to the day it is seeded, so there are
always tickets with no owner, customers waiting on us for hours, two overdue reminders and a few closed tickets.
Everyone and everything in it is made up.

## Tests

```
uv run --env-file .env pytest            # unit tests (a fake Zammad API), plus live tests when the local Zammad runs
```

## What a production version adds

This demo signs in with one API token. A production server for Zammad customers would add sign-in with each
agent's own Zammad account, so Claude sees exactly the groups they may see; hosting with an audit log of every
tool call; and more of the API (tags, links, time accounting, knowledge base, reply drafts for an agent to send).
That is what [Mojood Connect](https://mojood.app/connect) builds.

## License

Apache 2.0. Zammad is a trademark of Zammad GmbH; this project is not made or endorsed by Zammad GmbH.
