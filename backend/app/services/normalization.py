"""Supplier entity resolution: fuzzy name match + email domain + human review for borderline cases."""

import re

from rapidfuzz import fuzz, process
from sqlalchemy import select

from .. import config
from ..models import Supplier, SupplierMatch

SUFFIXES = {
    "ltd",
    "limited",
    "pvt",
    "private",
    "inc",
    "llp",
    "co",
    "corp",
    "corporation",
    "company",
    "llc",
}


def normalize_name(name: str) -> str:
    s = str(name).lower().replace("&", " and ")
    s = re.sub(r"(?<=\b[a-z])\.(?=[a-z]\b)", "", s)  # A.B.C -> ABC
    s = s.replace(".", "")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    toks = [t for t in s.split() if t not in SUFFIXES]
    return " ".join(toks)


def domain_of(email: str) -> str:
    return email.split("@")[-1].strip().lower() if email and "@" in email else ""


def resolve_suppliers(db, tenant_id: str, pairs):
    """pairs: iterable of (raw_name, email). Returns ({raw_name: supplier_id}, stats)."""
    existing = (
        db.execute(select(Supplier).where(Supplier.tenant_id == tenant_id))
        .scalars()
        .all()
    )
    keys = [s.norm_key for s in existing]
    ids = [s.id for s in existing]
    dom_map = {s.email_domain: s.id for s in existing if s.email_domain}
    key_map = {s.norm_key: s.id for s in existing}

    # most frequent raw names first -> they become the canonical display name
    freq = {}
    for raw, email in pairs:
        freq.setdefault((raw, domain_of(email)), 0)
        freq[(raw, domain_of(email))] += 1
    ordered = sorted(freq.items(), key=lambda kv: -kv[1])

    mapping, stats = {}, {"auto_merged": 0, "sent_to_review": 0, "created": 0}
    for (raw, dom), _ in ordered:
        if raw in mapping:
            continue
        key = normalize_name(raw)
        best_score, best_idx = 0, None
        sid = key_map.get(key)
        if sid is None and dom and dom in dom_map:
            sid = dom_map[dom]
            stats["auto_merged"] += 1
        elif sid is not None:
            stats["auto_merged"] += 1
        if sid is None and keys:
            best = process.extractOne(key, keys, scorer=fuzz.token_sort_ratio)
            if best and best[1] >= config.SUPPLIER_AUTO_MERGE:
                sid = ids[best[2]]
                stats["auto_merged"] += 1
            else:
                best_score, best_idx = (best[1], best[2]) if best else (0, None)
        if sid is None:
            sup = Supplier(
                tenant_id=tenant_id,
                name=raw.title() if raw.isupper() else raw,
                norm_key=key,
                email_domain=dom or None,
            )
            db.add(sup)
            db.flush()
            stats["created"] += 1
            if keys and best_idx is not None and best_score >= config.SUPPLIER_REVIEW:
                db.add(
                    SupplierMatch(
                        tenant_id=tenant_id,
                        supplier_id=sup.id,
                        candidate_id=ids[best_idx],
                        raw_name=raw,
                        score=round(float(best_score), 1),
                    )
                )
                stats["sent_to_review"] += 1
            sid = sup.id
            keys.append(key)
            ids.append(sid)
            key_map[key] = sid
            if dom:
                dom_map.setdefault(dom, sid)
        mapping[raw] = sid
    return mapping, stats
