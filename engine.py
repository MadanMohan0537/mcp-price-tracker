import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse
from core import tool

S = {"type": "string", "minLength": 1, "maxLength": 2000}
ID = {"product_id": S}
CURRENCIES = {"USD", "EUR", "GBP", "INR", "CAD", "AUD", "JPY", "CHF", "NZD", "SGD"}


def stamp(value=None):
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("Timestamp must be an ISO 8601 string with timezone")
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Invalid timestamp") from None
    if date.tzinfo is None:
        raise ValueError("Timestamp must include a timezone")
    if date.timestamp() > datetime.now(timezone.utc).timestamp() + 60:
        raise ValueError("Future capture timestamps are not allowed")
    return date.astimezone(timezone.utc).isoformat()


def public_url(value):
    try:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError("Use a public HTTPS source URL without credentials") from None
    return value


def amount(value, currency):
    if currency not in CURRENCIES:
        raise ValueError("Unsupported currency; use " + ", ".join(sorted(CURRENCIES)))
    try:
        number = Decimal(str(value))
        scale = 1 if currency == "JPY" else 100
        scaled = number * scale
        if not number.is_finite() or number < 0 or number > 10**10 or scaled != scaled.to_integral_value():
            raise ValueError()
        return int(scaled)
    except (ValueError, InvalidOperation):
        raise ValueError("Price must be a nonnegative decimal in the currency's minor units") from None


def extract_offer(html, variant="default"):
    nodes = []
    def visit(value):
        if isinstance(value, list):
            for item in value: visit(item)
        elif isinstance(value, dict):
            types = value.get("@type", [])
            if types == "Product" or isinstance(types, list) and "Product" in types:
                if variant == "default" or str(value.get("sku", "")) == variant:
                    offers = value.get("offers", [])
                    for offer in offers if isinstance(offers, list) else [offers]:
                        if isinstance(offer, dict) and "price" in offer and "priceCurrency" in offer:
                            nodes.append((value, offer))
            for child in value.values():
                if isinstance(child, (dict, list)): visit(child)
    for match in re.finditer(r'<script\b[^>]*type\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script\s*>', html, re.I | re.S):
        try: visit(json.loads(match[1]))
        except json.JSONDecodeError: continue
    if len(nodes) != 1:
        raise ValueError("Expected one unambiguous Product offer; select a SKU or supply a normalized observation")
    product, offer = nodes[0]
    return {"title": product.get("name", "Product"), "price": str(offer["price"]), "currency": offer["priceCurrency"],
            "availability": offer.get("availability", "Unknown").split("/")[-1]}


class PriceTracker:
    name = "mcp-price-tracker"
    def __init__(self, path):
        if path != ":memory:": Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''PRAGMA journal_mode=WAL;
          CREATE TABLE IF NOT EXISTS products(id TEXT PRIMARY KEY,url TEXT NOT NULL,title TEXT NOT NULL,variant TEXT NOT NULL,UNIQUE(url,variant));
          CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY,product_id TEXT NOT NULL,price INTEGER NOT NULL,currency TEXT NOT NULL,availability TEXT NOT NULL,captured_at TEXT NOT NULL,source TEXT NOT NULL,shipping TEXT,tax TEXT,UNIQUE(product_id,captured_at));
          CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY,product_id TEXT NOT NULL,threshold INTEGER NOT NULL,currency TEXT NOT NULL);
        ''')
        observation = {"type": "object", "properties": {"price": S, "currency": S, "availability": {"type": "string", "enum": ["InStock", "OutOfStock", "PreOrder", "Unknown"]}, "captured_at": S, "shipping": S, "tax": S}, "required": ["price", "currency", "availability"], "additionalProperties": False}
        self.tools = [
          tool("record_product", "Register a URL and variant; optionally record an explicit price observation or one JSON-LD Product offer from a supplied page snapshot.", {"url": S,"title": S,"variant": S,"observation": observation,"html": {"type":"string","maxLength":800000}}, ["url"], True),
          tool("collect_price", "Collect one current price from an explicitly allowlisted HTTPS JSON-LD source. Redirects are rejected.", ID, ["product_id"], True),
          tool("list_products", "List registered products with latest observations.", {"offset":{"type":"integer","minimum":0},"limit":{"type":"integer","minimum":1,"maximum":100}}),
          tool("get_current_price", "Latest captured price, availability, evidence and stale-data warning.", ID, ["product_id"]),
          tool("get_price_history", "Ordered observations within optional inclusive ISO date bounds.", {**ID,"from":S,"to":S,"offset":{"type":"integer","minimum":0},"limit":{"type":"integer","minimum":1,"maximum":100}}, ["product_id"]),
          tool("compare_products", "Compare latest prices by currency without converting or silently combining variants.", {"product_ids":{"type":"array","items":S,"maxItems":20}}, ["product_ids"]),
          tool("explain_change", "Compute observed change against the first capture in a selected date window; never infer missing prices.", {**ID,"from":S,"to":S}, ["product_id"]),
          tool("set_price_alert", "Persist a price threshold in one currency. Check alerts explicitly or from an external scheduler.", {**ID,"threshold":S,"currency":S}, ["product_id","threshold","currency"], True),
          tool("check_alerts", "Return threshold matches with capture evidence; stale or out-of-stock observations cannot trigger.", {}),
        ]
    def product(self, key):
        row = self.db.execute("SELECT * FROM products WHERE id=?", (key,)).fetchone()
        if not row: raise ValueError("Product not found")
        return dict(row)
    def observation(self, row):
        if row is None: return None
        data = dict(row)
        data["price"] = str(Decimal(data["price"]) / (1 if data["currency"] == "JPY" else 100))
        data["age_hours"] = round((datetime.now(timezone.utc) - datetime.fromisoformat(data["captured_at"])).total_seconds()/3600, 2)
        data["stale"] = data["age_hours"] > 24
        return data
    def current(self, key):
        return {"product": self.product(key), "observation": self.observation(self.db.execute("SELECT * FROM observations WHERE product_id=? ORDER BY captured_at DESC LIMIT 1", (key,)).fetchone()), "caveat":"Captured item price only. Shipping and taxes are separate; no checkout guarantee."}
    def call(self, name, a):
        if name == "record_product":
            url = public_url(a["url"]); variant = a.get("variant", "default")
            key = hashlib.sha256((url + "|" + variant).encode()).hexdigest()[:20]
            if "html" in a and "observation" in a: raise ValueError("Supply html or observation, not both")
            obs = a.get("observation")
            title = a.get("title", urlparse(url).hostname)
            if "html" in a:
                obs = extract_offer(a["html"], variant)
                title = obs.pop("title")
                if obs["availability"] not in ("InStock", "OutOfStock", "PreOrder", "Unknown"): obs["availability"] = "Unknown"
            normalized = None
            if obs:
                normalized = (key, amount(obs["price"], obs["currency"]), obs["currency"], obs["availability"], stamp(obs.get("captured_at")), url, obs.get("shipping"), obs.get("tax"))
            with self.db:
                self.db.execute("INSERT INTO products VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title", (key, url, title, variant))
                if normalized:
                    old = self.db.execute("SELECT price,currency,availability FROM observations WHERE product_id=? AND captured_at=?", (key, normalized[4])).fetchone()
                    if old and tuple(old) != normalized[1:4]: raise ValueError("Conflicting observation at the same timestamp")
                    self.db.execute("INSERT OR IGNORE INTO observations(product_id,price,currency,availability,captured_at,source,shipping,tax) VALUES(?,?,?,?,?,?,?,?)", normalized)
            return self.current(key)
        if name == "collect_price":
            from source import fetch_page
            product = self.product(a["product_id"])
            try:
                html = fetch_page(product["url"], os.environ.get("PRICE_ALLOWED_HOSTS", "").split(","))
            except (OSError, UnicodeError) as exc:
                raise ValueError(f"Source collection failed ({type(exc).__name__}); prior evidence is preserved") from None
            return self.call("record_product", {"url":product["url"],"variant":product["variant"],"html":html})
        if name == "list_products":
            rows = self.db.execute("SELECT id FROM products ORDER BY id LIMIT ? OFFSET ?", (a.get("limit",100),a.get("offset",0)))
            return {"products":[self.current(r[0]) for r in rows]}
        if name == "get_current_price": return self.current(a["product_id"])
        if name in ("get_price_history", "explain_change"):
            self.product(a["product_id"])
            query = "SELECT * FROM observations WHERE product_id=?"; values = [a["product_id"]]
            for field, op in [("from",">="),("to","<=")]:
                if field in a: query += f" AND captured_at{op}?"; values.append(stamp(a[field]))
            if "from" in a and "to" in a and stamp(a["from"]) > stamp(a["to"]): raise ValueError("from must precede to")
            query += " ORDER BY captured_at"
            if name == "get_price_history": query += " LIMIT ? OFFSET ?"; values += [a.get("limit",100),a.get("offset",0)]
            rows = [self.observation(r) for r in self.db.execute(query,values)]
            if name == "get_price_history": return {"observations":rows}
            if len(rows) < 2: return {"status":"insufficient_evidence","observations":rows}
            first, last = rows[0],rows[-1]
            if len({r["currency"] for r in rows}) != 1: return {"status":"incomparable_currencies","observations":rows}
            change = Decimal(last["price"])-Decimal(first["price"])
            return {"status":"observed_change","baseline":first,"latest":last,"absolute_change":str(change),"percent_change":float(change/Decimal(first["price"])*100) if Decimal(first["price"]) else None,"caveat":"Observed movement, not a claimed discount or explanation of seller intent."}
        if name == "compare_products":
            if not a["product_ids"]: raise ValueError("Select at least one product")
            rows = [self.current(key) for key in dict.fromkeys(a["product_ids"])]
            groups = {}
            for row in rows:
                currency = row["observation"]["currency"] if row["observation"] else "unobserved"
                groups.setdefault(currency,[]).append(row)
            return {"currency_groups":groups,"caveat":"Compare equivalent variants; taxes, shipping and membership prices may differ."}
        if name == "set_price_alert":
            self.product(a["product_id"])
            with self.db:
                cur = self.db.execute("INSERT INTO alerts(product_id,threshold,currency) VALUES(?,?,?)", (a["product_id"],amount(a["threshold"],a["currency"]),a["currency"]))
            return {"alert_id":cur.lastrowid,"status":"saved"}
        if name == "check_alerts":
            results = []
            for alert in self.db.execute("SELECT * FROM alerts"):
                row = self.current(alert["product_id"]); obs = row["observation"]
                triggered = bool(obs and obs["currency"] == alert["currency"] and not obs["stale"] and obs["availability"] == "InStock" and amount(obs["price"],obs["currency"]) <= alert["threshold"])
                results.append({"alert_id":alert["id"],"triggered":triggered,"evidence":row})
            return {"alerts":results}
        raise ValueError("Unknown tool")
    def collect(self):
        results=[]
        for row in self.db.execute("SELECT id FROM products"):
            try: results.append({"product_id":row[0],"result":self.call("collect_price",{"product_id":row[0]})})
            except (ValueError,OSError) as exc: results.append({"product_id":row[0],"error":str(exc)})
        return {"collections":results,"alerts":self.call("check_alerts",{})["alerts"]}
    def demo(self):
        for day,price in [("2026-01-01T12:00:00Z","129.00"),("2026-01-02T12:00:00Z","109.00")]:
            self.call("record_product",{"url":"https://example.com/demo-headphones","title":"Synthetic headphones example","observation":{"price":price,"currency":"USD","availability":"InStock","captured_at":day}})
