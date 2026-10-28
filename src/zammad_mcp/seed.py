"""Fill an empty local Zammad with the support desk of Harbor Trading, a made-up Gulf supplier (SAMPLE data).

Agents, groups, customer companies and tickets go in through Zammad's own API; customers' messages are logged by
the desk as from the customer (sender Customer, origin_by), the way phoned-in or forwarded requests are. Zammad's API can't set past times, so the seeder also writes
docker/backdate.json (hours ago for each ticket's messages and reminder), which scripts/reset.sh applies inside
the container: the desk then has tickets waiting on us, overdue reminders and an unassigned urgent one, whatever
day it is seeded. Run on an empty Zammad only (scripts/reset.sh).
"""

import json
from pathlib import Path

from zammad_mcp.client import Zammad

GROUPS = ["Orders", "Deliveries", "Billing"]
# first, last, groups
AGENTS = [
    ("Aisha", "Rahman", ["Orders"]),
    ("Karim", "Nasser", ["Deliveries", "Orders"]),
    ("Lina", "Farah", ["Billing"]),
    ("Omar", "Siddiqui", ["Orders", "Deliveries"]),
]
# company, people (first, last, job)
CUSTOMERS = [
    ("Al Noor Hotels", [("Mona", "Farouk", "Procurement manager"), ("Sami", "Haddad", "Accounts payable")]),
    ("Gulf Build Contracting", [("Rashid", "Al-Mutairi", "Site manager")]),
    ("Coastal Marine Services", [("James", "Whitfield", "Workshop lead")]),
    ("Desert Rose Catering", [("Fatima", "Zaidi", "Operations")]),
    ("Najd Facilities Management", [("Abdullah", "Al-Rashid", "Contracts")]),
    ("Red Sea Fit-Out", [("Elena", "Petrova", "Project buyer")]),
]

# title, customer, group, priority, state, owner, reminder (hours from now; negative = overdue), messages
# Each message: (who, hours ago, text) with who = "c" customer, "a" owner's public reply, "n" owner's internal note.
TICKETS = [
    ("Wrong size on 40 room safes, order HT-SO-5521", "Mona Farouk", "Deliveries", "3 high", "open", None, None, [
        ("c", 26, "Hello, the 40 room safes on order HT-SO-5521 arrived today, but they are the 30 litre model. We ordered 20 litre ones to fit the wardrobes. The new wing opens on 9 November. Can you exchange them before then? Mona"),
    ]),
    ("Invoice HT-INV-2290 shows the old unit price", "Sami Haddad", "Billing", "2 normal", "open", "Lina Farah", None, [
        ("c", 50, "Invoice HT-INV-2290 charges the bath towels at the old unit price. Our September agreement has the new price. Please send a corrected invoice."),
        ("a", 30, "Thank you, Sami. I'm checking the September price list with our sales team and will come back to you."),
        ("c", 6, "Any news? Our payment run closes on Thursday and I can't approve this invoice as it is."),
    ]),
    ("Quote for 120 housekeeping trolleys", "Mona Farouk", "Orders", "2 normal", "pending reminder", "Aisha Rahman", -20, [
        ("c", 120, "Could you quote 120 housekeeping trolleys, the same model as last year, delivered to Dammam?"),
        ("a", 96, "We'll have the supplier's price on Monday and will send the quote then."),
    ]),
    ("Urgent: 500 safety helmets for site handover Sunday", "Rashid Al-Mutairi", "Orders", "3 high", "new", None, None, [
        ("c", 3, "We need 500 white safety helmets with chin straps at the Khobar site by Sunday morning for the handover. Can you confirm stock and a delivery time today?"),
    ]),
    ("Return of 12 damaged scaffolding clamps", "Rashid Al-Mutairi", "Deliveries", "2 normal", "open", "Karim Nasser", None, [
        ("c", 70, "12 of the swivel clamps from last week's delivery are cracked. Photos attached in our portal. We'd like a return and replacements."),
        ("a", 44, "Sorry about that, Rashid. Our driver will collect them on his next run. Could you confirm the site contact?"),
    ]),
    ("Marine-grade A4 bolts: stock check", "James Whitfield", "Orders", "1 low", "open", "Omar Siddiqui", None, [
        ("c", 30, "Do you have 200 A4 stainless M16×80 hex bolts in stock? We need them for a hull job next week."),
    ]),
    ("Credit note for short delivery", "James Whitfield", "Billing", "2 normal", "pending reminder", "Lina Farah", 48, [
        ("c", 75, "Order HT-SO-5410 arrived 40 gaskets short. Please issue a credit note."),
        ("a", 52, "Confirmed against the packing list. The credit note will go out once the warehouse closes the count."),
    ]),
    ("Commercial dishwasher not working after install", "Fatima Zaidi", "Deliveries", "3 high", "open", "Karim Nasser", None, [
        ("c", 8, "The conveyor dishwasher you installed on Monday stops after two minutes with error E14. We have a 600-cover event on Friday."),
        ("n", 5, "E14 is the rinse pump sensor. Manufacturer's technician can come Thursday morning; waiting for their confirmation."),
    ]),
    ("Monthly cleaning chemicals order not arrived", "Abdullah Al-Rashid", "Deliveries", "3 high", "open", None, None, [
        ("c", 30, "Our monthly order of cleaning chemicals for the Riyadh towers was due yesterday and hasn't arrived. Which day can we expect it?"),
    ]),
    ("Request: account statement for Q3", "Abdullah Al-Rashid", "Billing", "1 low", "new", None, None, [
        ("c", 5, "Please send our account statement for July to September."),
    ]),
    ("Lead time for 300 m² of acoustic panels", "Elena Petrova", "Orders", "2 normal", "open", "Aisha Rahman", None, [
        ("c", 60, "What is the lead time for 300 m² of the grey felt acoustic panels? The fit-out starts on 20 November."),
        ("a", 20, "The factory quotes four weeks from order. I can hold a production slot for you until Friday."),
    ]),
    ("Paint batch colour mismatch", "Elena Petrova", "Deliveries", "2 normal", "pending reminder", "Omar Siddiqui", -4, [
        ("c", 90, "Two of the 20 paint tins are a different shade. Batch numbers are on the lids. Can you replace them?"),
        ("a", 70, "Replacements from the same batch are on order. I'll confirm the delivery date when they land."),
    ]),
    ("Delivery note missing from last shipment", "Mona Farouk", "Deliveries", "2 normal", "closed", "Karim Nasser", None, [
        ("c", 300, "The shipment on Sunday came without a delivery note. Could you email it?"),
        ("a", 290, "Attached to this reply. Sorry for the trouble."),
    ]),
    ("Change delivery address for weekly order", "Fatima Zaidi", "Orders", "2 normal", "closed", "Aisha Rahman", None, [
        ("c", 400, "From next week please deliver the weekly order to our new kitchen in Al Khobar."),
        ("a", 395, "Done: the address is updated on your account from next Monday."),
    ]),
    ("Price list for 2027", "Abdullah Al-Rashid", "Orders", "1 low", "closed", "Omar Siddiqui", None, [
        ("c", 500, "When will the 2027 price list be ready?"),
        ("a", 480, "We'll send it in the first week of December."),
    ]),
]


def seed(api: Zammad, backdate_file: Path) -> dict:
    if api.get("tickets", per_page=1):
        raise SystemExit("Zammad already has tickets: seed an empty one (scripts/reset.sh)")
    group_ids = {g: api.post("groups", {"name": g, "active": True})["id"] for g in GROUPS}
    # The token's own user (the demo admin) works every group, so it can log tickets and changes in them.
    me = api.get("users/me")["id"]
    api.put(f"users/{me}", {"group_ids": {str(i): ["full"] for i in [1, *group_ids.values()]}})
    agents: dict[str, int] = {}
    for first, last, groups in AGENTS:
        email = f"{first}.{last}@harbor-trading.example".lower()
        agents[f"{first} {last}"] = api.post("users", {
            "firstname": first, "lastname": last, "email": email, "login": email, "roles": ["Agent"],
            "group_ids": {str(group_ids[g]): ["full"] for g in groups},
        })["id"]
    people: dict[str, tuple[int, str]] = {}
    for company, persons in CUSTOMERS:
        api.post("organizations", {"name": company})
        domain = company.lower().replace(" ", "-").replace("'", "") + ".example"
        for first, last, job in persons:
            email = f"{first}.{last}@{domain}".lower()
            uid = api.post("users", {"firstname": first, "lastname": last, "email": email, "login": email,
                                     "organization": company, "roles": ["Customer"], "note": job})["id"]
            people[f"{first} {last}"] = (uid, f"{first} {last} <{email}>")

    backdate = []
    for title, who, group, priority, state, owner, reminder, messages in TICKETS:
        uid, sender = people[who]
        from_customer = {"sender": "Customer", "type": "web", "internal": False, "from": sender, "origin_by_id": uid}
        t = api.post("tickets", {
            "title": title, "group": group, "customer_id": uid, "priority": priority,
            "article": {"subject": title, "body": messages[0][2], "content_type": "text/plain", **from_customer},
        })
        for kind, _h, text in messages[1:]:
            article = {"ticket_id": t["id"], "body": text, "content_type": "text/plain"}
            if kind == "c":
                article |= from_customer
            else:
                article |= {"sender": "Agent", "type": "note", "internal": kind == "n", "from": owner}
            api.post("ticket_articles", article)
        update = {"state": state, "owner_id": agents[owner] if owner else 1}
        if state == "pending reminder":
            update["pending_time"] = "2099-01-01T00:00:00Z"  # set to the real time by backdate.rb
        api.put(f"tickets/{t['id']}", update)
        backdate.append({"id": t["id"], "hours": [h for _k, h, _t in messages], "reminder": reminder,
                         "agent": agents[owner] if owner else None})
    backdate_file.write_text(json.dumps(backdate))
    return {"agents": len(agents), "companies": len(CUSTOMERS), "customers": len(people), "tickets": len(TICKETS)}


def main() -> None:
    print(seed(Zammad(), Path(__file__).resolve().parents[2] / "docker" / "backdate.json"))
