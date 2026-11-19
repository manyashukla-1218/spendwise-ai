"""Synthetic procurement data generator (100% fake data, no real company data).

Creates:
  data/generated/train_labeled.csv        -> labelled history used to train the base classifier
  data/generated/tenant_<id>.csv          -> unlabelled uploads (has hidden `true_category` for benchmarking only)

Messiness we inject on purpose (so the AI has real work to do):
  - the same supplier written 4-6 different ways (Pvt Ltd / Private Limited / typos / caps)
  - ~40% of rows have no supplier email
  - vague descriptions ("annual renewal") and label noise
  - ~1% price anomalies, many one-off tail suppliers, seasonality + growth
"""
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "generated"

CATALOG = {
    "IT Hardware": [("Laptop 14 inch", 58000), ("Desktop workstation", 72000), ("24 inch monitor", 11500),
                    ("Wireless keyboard mouse combo", 1800), ("Network switch 24 port", 24000)],
    "Software & Cloud": [("Cloud hosting subscription", 45000), ("Antivirus licence per seat", 3200),
                         ("Project management software licence", 7800), ("Database hosting service", 60000),
                         ("Productivity suite annual plan", 9600)],
    "Office Supplies": [("A4 copier paper ream", 320), ("Ballpoint pen box", 240), ("Stapler heavy duty", 450),
                        ("Whiteboard marker pack", 380), ("Printer toner cartridge", 4200)],
    "Furniture": [("Ergonomic office chair", 8500), ("Executive desk", 16500), ("Filing cabinet 4 drawer", 9800),
                  ("Conference table", 42000), ("Visitor sofa", 21000)],
    "Facilities & Maintenance": [("AC annual maintenance", 18000), ("Housekeeping service monthly", 35000),
                                 ("Pest control quarterly", 6500), ("Electrical repair work", 5200),
                                 ("Fire extinguisher refill", 1800)],
    "Logistics & Freight": [("Road freight Delhi to Mumbai", 42000), ("Courier charges bulk", 6800),
                            ("Warehouse storage monthly", 52000), ("Customs clearance service", 14500),
                            ("Last mile delivery batch", 9500)],
    "Marketing & Advertising": [("Google ads campaign", 65000), ("Brand banner printing", 7500),
                                ("Event stall setup", 120000), ("Social media management monthly", 28000),
                                ("Promotional merchandise", 14500)],
    "Professional Services": [("Statutory audit fee", 150000), ("Legal consultation retainer", 60000),
                              ("IT consulting day rate", 22000), ("Recruitment agency fee", 85000),
                              ("Tax advisory service", 45000)],
    "Travel & Hospitality": [("Domestic flight ticket", 6800), ("Hotel stay per night", 5800),
                             ("Cab rental outstation", 9200), ("Conference registration", 12500),
                             ("Team lunch catering", 18000)],
    "Raw Materials": [("Mild steel sheet per ton", 68000), ("Copper wire spool", 54000),
                      ("Industrial packaging film", 14500), ("Aluminium extrusion", 23500),
                      ("Plastic granules per ton", 96000)],
    "Telecom": [("Broadband leased line monthly", 24000), ("Mobile postpaid bulk plan", 36000),
                ("SIP trunk charges", 12000), ("Video conferencing licence", 8400), ("Router rental", 3200)],
    "Utilities": [("Electricity bill", 180000), ("Water supply charges", 24000), ("Diesel genset fuel", 62000),
                  ("Solar plant maintenance", 18500), ("Waste disposal service", 9600)],
}
CATS = list(CATALOG)
BIG_TICKET = {"Raw Materials", "Utilities", "Professional Services", "Marketing & Advertising", "Logistics & Freight"}

FIRST = ["Alpha", "Nova", "Zen", "Apex", "Orion", "Vertex", "Prime", "Sigma", "Delta", "Omni", "Astra", "Kiran",
         "Shree", "Sai", "Global", "United", "Royal", "Metro", "Bharat", "Unity", "Zenith", "Lotus", "Quantum",
         "Pioneer", "Ganga", "Vega", "Titan", "Crown", "Elite", "Swift"]
SECOND = ["Technologies", "Systems", "Traders", "Enterprises", "Solutions", "Logistics", "Infra", "Services",
          "Industries", "Supplies"]

VAGUE = ["Misc purchase", "Invoice payment", "General expenses", "Service charges", "Payment as per PO",
         "Annual renewal", "Monthly charges", "Maintenance charges"]


def _typo(s, rng):
    if len(s) < 6 or rng.random() > 0.35:
        return s
    i = rng.randrange(1, len(s) - 1)
    return s[:i] + s[i + 1:]


def _describe(item, rng):
    t = rng.choice([
        "{i}", "Purchase of {l}", "PO {n} - {i}", "INV-{n} {i}", "{u}", "{i} (as per quotation)",
        "Payment for {l}", "{i} - {m}",
    ])
    d = t.format(i=item, l=item.lower(), u=item.upper(), n=rng.randint(1000, 9999), m=rng.choice(["Q1", "Q2", "Q3", "Q4"]))
    return _typo(d, rng)


def _supplier_variants(name, rng):
    v = [name, f"{name} Pvt Ltd", f"{name} Private Limited", f"{name.upper()}", f"{name} Pvt. Ltd.",
         f"{name.split()[0]} {_typo(name.split()[1], rng)} Ltd"]
    if rng.random() < 0.5:
        v.append(f"{name.split()[0]} {name.split()[1][:4]}")
    return v


def build_suppliers(rng, per_cat=6):
    used, sup = set(), {}
    for cat in CATS:
        lst = []
        while len(lst) < per_cat:
            nm = f"{rng.choice(FIRST)} {rng.choice(SECOND)}"
            if nm in used:
                continue
            used.add(nm)
            lst.append({"name": nm, "mult": rng.uniform(0.9, 1.22),
                        "domain": (nm.split()[0] + nm.split()[1][:4]).lower() + ".in",
                        "variants": _supplier_variants(nm, rng)})
        sup[cat] = lst
    tail = []
    while len(tail) < 40:
        nm = f"{rng.choice(FIRST)} {rng.choice(SECOND)}"
        if nm in used:
            continue
        used.add(nm)
        tail.append({"name": nm, "mult": rng.uniform(0.95, 1.3), "domain": (nm.split()[0] + nm.split()[1][:4]).lower() + ".in",
                     "variants": [nm, f"{nm} Pvt Ltd"]})
    return sup, tail


def generate(n=10000, seed=1, labeled=False, focus=None):
    rng = random.Random(seed)
    nprng = np.random.default_rng(seed)
    sup, tail = build_suppliers(rng)
    weights = [3 if (focus and c in focus) else 1 for c in CATS]
    end = date(2026, 10, 31)
    start = date(2024, 11, 1)
    span = (end - start).days
    rows = []
    for _ in range(n):
        # growth: later dates slightly more likely; seasonality: March & Oct bumps
        d = start + timedelta(days=int(span * (rng.random() ** 0.8)))
        if d.month in (3, 10) and rng.random() < 0.3:
            d = d.replace(day=min(d.day, 28))
        cat = rng.choices(CATS, weights)[0]
        item, base = rng.choice(CATALOG[cat])
        is_tail = rng.random() < 0.08
        s = rng.choice(tail) if is_tail else rng.choice(sup[cat])
        qty = rng.randint(1, 4) if cat in BIG_TICKET else rng.choice([1, 1, 2, 3, 5, 10, 20, 50])
        price = base * s["mult"] * float(nprng.lognormal(0, 0.05))
        if rng.random() < 0.01:
            price *= rng.uniform(2.6, 4.0)           # injected anomaly
        desc = rng.choice(VAGUE) if rng.random() < 0.07 else _describe(item, rng)
        label = cat if desc not in VAGUE else rng.choice(CATS)   # label noise on vague text
        row = {
            "txn_date": d.isoformat(),
            "supplier_name": rng.choice(s["variants"]),
            "supplier_email": f"accounts@{s['domain']}" if rng.random() < 0.6 else "",
            "description": desc,
            "item": item if rng.random() < 0.9 else "",
            "quantity": qty,
            "unit_price": round(price, 2),
            "amount": round(price * qty, 2),
        }
        row["category" if labeled else "true_category"] = label
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    n_train = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    generate(n_train, seed=101, labeled=True).to_csv(OUT / "train_labeled.csv", index=False)
    specs = {"acme": (10000, 11, ["Raw Materials", "Utilities", "Facilities & Maintenance"]),
             "nova": (8000, 22, ["Marketing & Advertising", "Logistics & Freight", "Office Supplies"]),
             "orbit": (9000, 33, ["Logistics & Freight", "Telecom", "Travel & Hospitality"])}
    for tid, (n, seed, focus) in specs.items():
        generate(n, seed=seed, labeled=False, focus=focus).to_csv(OUT / f"tenant_{tid}.csv", index=False)
    print("Generated files in", OUT)
    for p in sorted(OUT.glob("*.csv")):
        print(" ", p.name, sum(1 for _ in open(p)) - 1, "rows")


if __name__ == "__main__":
    main()
