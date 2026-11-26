"""Generate the synthetic seed data of the example warehouse (fictional B2B wholesaler).

All names, e-mail addresses, phone numbers and salaries are invented from word lists. The output is
committed under warehouse/seeds/; rerunning this script with the same seed rewrites the same files.
Only Random.random() is used, so the result does not depend on the Python version.
"""

from __future__ import annotations

import csv
import datetime as dt
import random
import sys
from pathlib import Path

R = random.Random(20261126)
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent.parent / "warehouse" / "seeds")


def pick(seq):
    return seq[int(R.random() * len(seq))]


def between(a: int, b: int) -> int:
    return a + int(R.random() * (b - a + 1))


FIRST = ["Anna", "Ben", "Clara", "David", "Elif", "Finn", "Greta", "Hannes", "Ines", "Jonas", "Katrin", "Lukas",
         "Mara", "Niklas", "Olga", "Pia", "Quentin", "Rosa", "Stefan", "Tara", "Ulrich", "Vera", "Wim", "Yara",
         "Zofia", "Lars", "Marek", "Sanne", "Julien", "Agata"]
LAST = ["Albers", "Brandt", "Cordes", "Dekker", "Eilers", "Fuchs", "Gerber", "Hofmann", "Janssen", "Kowalski",
        "Lambert", "Moreau", "Nowak", "Olsen", "Peeters", "Quast", "Richter", "Schulte", "Thiel", "Unger",
        "Visser", "Wagner", "Zielinski", "Bauer", "Dubois", "Haas", "Keller", "Lindner", "Martens", "Vogel"]
CO_A = ["Alder", "Birch", "Cedar", "Delta", "Elm", "Fjord", "Granite", "Harbor", "Iris", "Juniper", "Kite",
        "Linden", "Maple", "North", "Oak", "Pine", "Quarry", "River", "Stone", "Tide", "Upland", "Vale",
        "Willow", "Yew", "Zenith"]
CO_B = ["Logistics", "Dental", "Architects", "Bakery", "Clinic", "Consulting", "Engineering", "Foods",
        "Hotels", "Labs", "Media", "Motors", "Optics", "Print", "Robotics", "Schools", "Software", "Textiles"]
CO_C = {"DE": ["GmbH", "AG", "KG"], "AT": ["GmbH", "KG"], "CH": ["AG", "GmbH"], "NL": ["B.V."], "BE": ["BV", "SRL"],
        "FR": ["SAS", "SARL"], "PL": ["sp. z o.o.", "S.A."]}
COUNTRIES = [("DE", "DACH", 0.40), ("AT", "DACH", 0.10), ("CH", "DACH", 0.08), ("NL", "Benelux", 0.14),
             ("BE", "Benelux", 0.06), ("FR", "France", 0.12), ("PL", "Poland", 0.10)]
SEGMENTS = [("enterprise", 0.15), ("mid_market", 0.35), ("small_business", 0.50)]
CATEGORIES = {
    "paper": [("Copy paper A4 80g, 500 sheets", 4.9, 2.6), ("Copy paper A3 80g, 500 sheets", 9.8, 5.5),
              ("Recycled paper A4, 500 sheets", 5.4, 3.1), ("Notebook A5 ruled", 2.2, 0.9),
              ("Sticky notes 76x76, 12 pads", 6.5, 2.8), ("Envelopes C4, 250", 18.0, 9.2),
              ("Flipchart pad, 5 pack", 39.0, 21.0), ("Label sheets A4, 100", 24.0, 11.5)],
    "furniture": [("Office chair ergonomic", 289.0, 171.0), ("Standing desk 160x80", 549.0, 348.0),
                  ("Filing cabinet 3 drawers", 219.0, 131.0), ("Meeting table 240x100", 689.0, 455.0),
                  ("Monitor arm dual", 129.0, 58.0), ("Footrest adjustable", 39.0, 17.0),
                  ("Shelf unit 5 levels", 179.0, 102.0), ("Visitor chair stackable", 79.0, 41.0)],
    "electronics": [("Monitor 27 inch QHD", 319.0, 236.0), ("USB-C docking station", 189.0, 121.0),
                    ("Wireless keyboard and mouse", 59.0, 28.0), ("Headset with noise cancelling", 149.0, 86.0),
                    ("Webcam 1080p", 79.0, 38.0), ("Laser printer mono", 249.0, 168.0),
                    ("Toner cartridge black", 89.0, 44.0), ("Power strip 6 sockets", 24.0, 9.5)],
    "cleaning": [("Hand soap 5 l", 14.0, 5.9), ("Paper towels, 20 rolls", 32.0, 16.0),
                 ("Surface cleaner 1 l, 6 pack", 21.0, 8.4), ("Microfibre cloths, 50", 27.0, 11.0),
                 ("Bin liners 120 l, 250", 36.0, 17.5), ("Disinfectant spray, 12", 44.0, 22.0),
                 ("Toilet paper, 64 rolls", 41.0, 23.0), ("Floor mop set", 64.0, 29.0)],
    "safety": [("First aid kit DIN 13157", 49.0, 23.0), ("Safety gloves, 12 pairs", 29.0, 12.0),
               ("Safety glasses, 10", 45.0, 19.0), ("Fire extinguisher 6 kg", 79.0, 42.0),
               ("Hi-vis vest, 10", 35.0, 14.0), ("Ear plugs, 200 pairs", 39.0, 15.0),
               ("Safety shoes S3", 89.0, 51.0), ("Eye wash station", 99.0, 52.0)],
}


def weighted(items):
    x = R.random()
    acc = 0.0
    for item in items:
        acc += item[-1]
        if x < acc:
            return item
    return items[-1]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    regions = ["DACH", "Benelux", "France", "Poland"]

    reps = []
    rid = 1
    for region, n in zip(regions, [5, 3, 2, 2]):
        for _ in range(n):
            f, l = pick(FIRST), pick(LAST)
            reps.append({"employee_id": rid, "full_name": f"{f} {l}",
                         "email": f"{f.lower()}.{l.lower()}@kestrel-supply.example",
                         "region": region,
                         "hire_date": (dt.date(2015, 1, 1) + dt.timedelta(days=between(0, 3300))).isoformat(),
                         "annual_salary": between(48, 96) * 1000})
            rid += 1

    customers = []
    for cid in range(1, 401):
        country, region, _ = weighted(COUNTRIES)
        seg, _ = weighted(SEGMENTS)
        f, l = pick(FIRST), pick(LAST)
        name = f"{pick(CO_A)} {pick(CO_B)} {pick(CO_C[country])}"
        dom = name.split()[0].lower() + name.split()[1].lower()
        customers.append({"customer_id": cid, "company_name": name, "contact_name": f"{f} {l}",
                          "contact_email": f"{f[0].lower()}.{l.lower()}@{dom}.example",
                          "contact_phone": f"+00 {between(100, 999)} {between(1000000, 9999999)}",
                          "country": country, "segment": seg,
                          "created_at": (dt.date(2023, 1, 1) + dt.timedelta(days=between(0, 700))).isoformat(),
                          "_region": region})

    products = []
    pid = 1
    for cat, items in CATEGORIES.items():
        for name, price, cost in items:
            products.append({"product_id": pid, "sku": f"{cat[:3].upper()}-{pid:04d}", "name": name,
                             "category": cat, "unit_price": f"{price:.2f}", "unit_cost": f"{cost:.2f}",
                             "is_active": "false" if R.random() < 0.08 else "true"})
            pid += 1

    reps_by_region = {r: [x for x in reps if x["region"] == r] for r in regions}
    seg_weight = {"enterprise": 6.0, "mid_market": 2.5, "small_business": 1.0}
    orders, lines, payments = [], [], []
    oid = 1
    pay_id = 1
    start, end = dt.date(2024, 1, 1), dt.date(2025, 12, 31)
    for c in customers:
        created = max(dt.date.fromisoformat(c["created_at"]), start)
        n_orders = int(seg_weight[c["segment"]] * (2 + R.random() * 10))
        if R.random() < 0.06:
            n_orders = 0  # customers who never ordered
        rep = pick(reps_by_region[c["_region"]])
        for _ in range(n_orders):
            span = (end - created).days
            if span <= 0:
                break
            d = created + dt.timedelta(days=int(R.random() * span))
            # More orders in the second year and in autumn.
            if d.year == 2024 and R.random() < 0.18:
                continue
            x = R.random()
            status = ("completed" if x < 0.86 else "cancelled" if x < 0.93 else "returned" if x < 0.97 else "open")
            if d >= dt.date(2025, 12, 15) and R.random() < 0.6:
                status = "open"
            if status == "open" and d < dt.date(2025, 11, 1):
                status = "completed"
            n_lines = between(1, 5 if c["segment"] != "small_business" else 3)
            used = set()
            gross = 0.0
            for ln in range(1, n_lines + 1):
                p = pick(products)
                if p["product_id"] in used:
                    continue
                used.add(p["product_id"])
                qty = between(1, 40 if p["category"] in ("paper", "cleaning", "safety") else 8)
                disc = weighted([(0, 0.6), (5, 0.2), (10, 0.15), (15, 0.05)])[0]
                price = float(p["unit_price"])
                if d.year == 2025:
                    price = round(price * 1.04, 2)  # list price increase on 2025-01-01
                lines.append({"order_id": oid, "line_number": len(used), "product_id": p["product_id"],
                              "quantity": qty, "unit_price": f"{price:.2f}", "discount_pct": disc})
                gross += qty * price * (1 - disc / 100)
            fee = 0 if gross >= 250 else 9.9
            orders.append({"order_id": oid, "customer_id": c["customer_id"], "sales_rep_id": rep["employee_id"],
                           "order_date": d.isoformat(), "status": status, "shipping_fee": f"{fee:.2f}"})
            if status in ("completed", "returned"):
                method = weighted([("invoice", 0.55), ("sepa_debit", 0.3), ("card", 0.15)])[0]
                paid = d + dt.timedelta(days=between(0, 3) if method == "card" else between(5, 40))
                payments.append({"payment_id": pay_id, "order_id": oid, "paid_at": paid.isoformat(),
                                 "amount": f"{round(gross * 1.0 + fee, 2):.2f}", "method": method})
                pay_id += 1
            oid += 1

    # Orders are numbered in date order, as an ERP would number them.
    orders.sort(key=lambda o: (o["order_date"], o["order_id"]))
    renum = {o["order_id"]: i for i, o in enumerate(orders, 1)}
    for o in orders:
        o["order_id"] = renum[o["order_id"]]
    for x in lines + payments:
        x["order_id"] = renum[x["order_id"]]
    lines.sort(key=lambda x: (x["order_id"], x["line_number"]))
    payments.sort(key=lambda x: x["order_id"])
    for i, p in enumerate(payments, 1):
        p["payment_id"] = i

    for c in customers:
        del c["_region"]
    write("raw_customers", customers)
    write("raw_employees", reps)
    write("raw_products", products)
    write("raw_orders", orders)
    write("raw_order_lines", lines)
    write("raw_payments", payments)
    print(f"customers={len(customers)} reps={len(reps)} products={len(products)} orders={len(orders)} "
          f"lines={len(lines)} payments={len(payments)}")


def write(name: str, rows: list[dict]) -> None:
    with open(OUT / f"{name}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
