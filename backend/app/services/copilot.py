"""AI Copilot: the LLM never touches the database directly. It can only call the small set of validated,
read-only analytics tools below (tool calling). Without an API key a keyword router answers instead.
"""

import json

from .. import config
from ..models import Supplier, SupplierMatch
from . import analytics

TOOLS = {
    "top_suppliers": {
        "desc": "Top suppliers by spend, optionally for one category.",
        "params": {"n": "integer, default 5", "category": "string, optional"},
    },
    "spend_by_category": {"desc": "Total spend per category.", "params": {}},
    "anomalies": {
        "desc": "Unusual / suspicious transactions with reasons.",
        "params": {"limit": "integer, default 5"},
    },
    "duplicate_suppliers": {
        "desc": "Suspected duplicate supplier records waiting for review.",
        "params": {},
    },
    "savings_opportunities": {
        "desc": "Price variance: items bought at different prices from several suppliers.",
        "params": {},
    },
    "tail_spend": {
        "desc": "Long-tail suppliers and consolidation candidates.",
        "params": {},
    },
    "monthly_trend": {
        "desc": "Monthly spend history and a simple 3-month projection.",
        "params": {},
    },
}


def run_tool(name, args, db, tenant_id, df):
    if name == "top_suppliers":
        return analytics.top_suppliers(df, int(args.get("n", 5)), args.get("category"))
    if name == "spend_by_category":
        return analytics.spend_by_category(df)
    if name == "anomalies":
        return analytics.anomalies(df, int(args.get("limit", 5)))["items"]
    if name == "duplicate_suppliers":
        ms = (
            db.query(SupplierMatch)
            .filter_by(tenant_id=tenant_id, status="pending")
            .limit(10)
            .all()
        )
        out = []
        for m in ms:
            a, b = db.get(Supplier, m.supplier_id), db.get(Supplier, m.candidate_id)
            if a and b:
                out.append(
                    {"supplier_a": a.name, "supplier_b": b.name, "similarity": m.score}
                )
        return out
    if name == "savings_opportunities":
        return analytics.price_variance(df, top=5)
    if name == "tail_spend":
        return analytics.tail_spend(df)
    if name == "monthly_trend":
        return analytics.monthly_trend(df)
    return {"error": f"unknown tool {name}"}


def _route(question):
    q = question.lower()
    if any(w in q for w in ("duplicate", "same supplier", "merge")):
        return "duplicate_suppliers", {}
    if any(
        w in q for w in ("unusual", "anomal", "suspicious", "outlier", "overpriced")
    ):
        return "anomalies", {"limit": 5}
    if any(w in q for w in ("save", "saving", "cheaper", "negotiat", "price variance")):
        return "savings_opportunities", {}
    if "tail" in q or "consolidat" in q:
        return "tail_spend", {}
    if any(w in q for w in ("trend", "month", "forecast", "increase", "growth")):
        return "monthly_trend", {}
    if "categor" in q:
        return "spend_by_category", {}
    return "top_suppliers", {"n": 5}


def _inr(x):
    return f"Rs {float(x):,.0f}"


def _summarize(tool, data):
    """Readable answer from tool output (used when no LLM key is set)."""
    try:
        if tool == "savings_opportunities":
            lines = [
                f"Estimated savings potential: {_inr(data['total_potential_savings'])}. Biggest opportunities:"
            ]
            for r in data["items"][:5]:
                lines.append(
                    f"- {r['item']}: {r['suppliers']} suppliers, price gap {r['spread_pct']}% "
                    f"({r['best_supplier']} {_inr(r['best_price'])} vs {r['highest_supplier']} "
                    f"{_inr(r['highest_price'])}), potential {_inr(r['potential_savings'])}"
                )
            return "\n".join(lines) + "\n(" + data["note"] + ")"
        if tool == "top_suppliers":
            return "Top suppliers by spend:\n" + "\n".join(
                f"- {r['supplier']}: {_inr(r['spend'])} over {r['txns']} transactions"
                for r in data[:5]
            )
        if tool == "spend_by_category":
            return "Spend by category:\n" + "\n".join(
                f"- {r['category']}: {_inr(r['spend'])}" for r in data[:8]
            )
        if tool == "anomalies":
            return (
                "Most unusual transactions:\n"
                + "\n".join(
                    f"- {r['description']} ({r['supplier']}): {r['anomaly_reason']}"
                    for r in data[:5]
                )
                if data
                else "No anomalies found."
            )
        if tool == "duplicate_suppliers":
            return (
                (
                    "Suspected duplicate suppliers:\n"
                    + "\n".join(
                        f"- {r['supplier_a']} ~ {r['supplier_b']} (similarity {r['similarity']})"
                        for r in data
                    )
                )
                if data
                else "No pending duplicate suppliers."
            )
        if tool == "tail_spend":
            return (
                f"{data['tail_suppliers']} of {data['suppliers_total']} suppliers "
                f"({data['tail_supplier_share_pct']}%) account for only {data['tail_spend_share_pct']}% of spend. "
                "Consolidation candidates: "
                + ", ".join(
                    f"{r['category']} ({r['tail_suppliers']})"
                    for r in data["consolidation_candidates"][:4]
                )
            )
        if tool == "monthly_trend":
            h, f = data["history"], data["forecast"]
            return (
                (
                    f"Latest month ({h[-1]['month']}): {_inr(h[-1]['spend'])}. Projection: "
                    + ", ".join(f"{x['month']} {_inr(x['spend'])}" for x in f)
                    + f". {data['note']}"
                )
                if h
                else "No data."
            )
    except Exception:  # noqa
        pass
    return json.dumps(data, default=str)[:1500]


def _fallback(question, db, tenant_id, df):
    tool, args = _route(question)
    data = run_tool(tool, args, db, tenant_id, df)
    return {
        "answer": _summarize(tool, data)
        + "\n\n(Rule-based mode. Set LLM_API_KEY for natural-language answers.)",
        "tools_used": [tool],
        "data": data,
        "mode": "rule-based",
    }


def ask(question, db, tenant_id):
    df = analytics.load_df(db, tenant_id)
    if not config.LLM_API_KEY:
        return _fallback(question, db, tenant_id, df)
    from openai import OpenAI

    client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)
    tools = [
        {
            "type": "function",
            "function": {
                "name": n,
                "description": t["desc"],
                "parameters": {
                    "type": "object",
                    "properties": {k: {"type": "string"} for k in t["params"]},
                },
            },
        }
        for n, t in TOOLS.items()
    ]
    msgs = [
        {
            "role": "system",
            "content": (
                "You are a procurement analytics assistant. Answer ONLY using results from the provided tools. "
                "Never invent numbers. If the tools cannot answer, say so. Currency is INR. Be concise."
                "Do not make claims about proportions or totals unless the tool output states them. "
                "Quote numbers and percentages exactly as returned by the tool. "
                "Never add units, time periods or claims that are not in the tool output."
            ),
        },
        {"role": "user", "content": question},
    ]
    used, data = [], None
    try:
        for _ in range(3):
            resp = client.chat.completions.create(
                model=config.LLM_MODEL, messages=msgs, tools=tools
            )
            m = resp.choices[0].message
            if not m.tool_calls:
                return {
                    "answer": m.content,
                    "tools_used": used,
                    "data": data,
                    "mode": "llm",
                }
            msgs.append(m)
            for tc in m.tool_calls:
                args = json.loads(tc.function.arguments or "{}")
                data = run_tool(tc.function.name, args, db, tenant_id, df)
                used.append(tc.function.name)
                msgs.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(data, default=str)[:6000],
                    }
                )
        return {
            "answer": "Could not complete the analysis.",
            "tools_used": used,
            "data": data,
            "mode": "llm",
        }
    except Exception as e:  # noqa  (rate limit, bad key...) -> degrade gracefully
        out = _fallback(question, db, tenant_id, df)
        out["answer"] += f" [LLM error: {str(e)[:120]}]"
        return out
