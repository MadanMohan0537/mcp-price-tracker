import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine import PriceTracker, amount, extract_offer
from core import invoke

class TrackerTests(unittest.TestCase):
    def setUp(self): self.app=PriceTracker(":memory:")
    def record(self,price="100.00",date="2026-01-01T00:00:00Z",currency="USD",url="https://example.com/a"):
        return invoke(self.app,"record_product",{"url":url,"observation":{"price":price,"currency":currency,"availability":"InStock","captured_at":date}})["product"]["id"]
    def test_exact_money(self):
        self.assertEqual(amount("0.29","USD"),29)
        self.assertEqual(amount("200","JPY"),200)
        for v in ["NaN","Infinity","-1","1.001","1,000"]:
            with self.assertRaises(ValueError):amount(v,"USD")
        with self.assertRaises(ValueError):amount("1.1","JPY")
    def test_change(self):
        key=self.record();self.record("80.00","2026-01-02T00:00:00Z")
        result=self.app.call("explain_change",{"product_id":key})
        self.assertEqual(result["percent_change"],-20)
        self.assertEqual(len(self.app.call("get_price_history",{"product_id":key})["observations"]),2)
    def test_idempotency_and_conflict(self):
        key=self.record();self.record()
        with self.assertRaises(ValueError):self.record("90.00")
        self.assertEqual(len(self.app.call("get_price_history",{"product_id":key})["observations"]),1)
    def test_invalid_observation_not_persisted(self):
        with self.assertRaises(ValueError):self.record("oops")
        self.assertEqual(self.app.call("list_products",{})["products"],[])
    def test_mixed_currency(self):
        key=self.record();self.record("80.00","2026-01-02T00:00:00Z","EUR")
        self.assertEqual(self.app.call("explain_change",{"product_id":key})["status"],"incomparable_currencies")
    def test_zero_baseline(self):
        key=self.record("0");self.record("1","2026-01-02T00:00:00Z")
        self.assertIsNone(self.app.call("explain_change",{"product_id":key})["percent_change"])
    def test_sparse_missing_stale(self):
        key=self.record();self.assertTrue(self.app.call("get_current_price",{"product_id":key})["observation"]["stale"])
        self.assertEqual(self.app.call("explain_change",{"product_id":key})["status"],"insufficient_evidence")
        with self.assertRaises(ValueError):self.app.call("get_current_price",{"product_id":"missing"})
    def test_threshold_evidence(self):
        r=invoke(self.app,"record_product",{"url":"https://example.com/live","observation":{"price":"90","currency":"USD","availability":"InStock"}})
        key=r["product"]["id"]
        self.app.call("set_price_alert",{"product_id":key,"threshold":"99","currency":"USD"})
        self.assertTrue(self.app.call("check_alerts",{})["alerts"][0]["triggered"])
        self.app.call("set_price_alert",{"product_id":key,"threshold":"99","currency":"EUR"})
        self.assertFalse(self.app.call("check_alerts",{})["alerts"][1]["triggered"])
    def test_stale_and_unavailable_alerts(self):
        key=self.record();self.app.call("set_price_alert",{"product_id":key,"threshold":"999","currency":"USD"})
        self.assertFalse(self.app.call("check_alerts",{})["alerts"][0]["triggered"])
        invoke(self.app,"record_product",{"url":"https://example.com/a","observation":{"price":"80","currency":"USD","availability":"OutOfStock"}})
        self.assertFalse(self.app.call("check_alerts",{})["alerts"][0]["triggered"])
    def test_variants_and_comparison(self):
        a=self.record();b=self.record(currency="EUR",url="https://example.com/b")
        groups=self.app.call("compare_products",{"product_ids":[a,b]})["currency_groups"]
        self.assertEqual(set(groups),{"USD","EUR"})
        c=invoke(self.app,"record_product",{"url":"https://example.com/a","variant":"large"})["product"]["id"]
        self.assertNotEqual(a,c)
    def test_snapshot(self):
        html='<script type="application/ld+json">'+json.dumps({"@type":"Product","name":"Headphones","offers":{"price":"49.99","priceCurrency":"USD","availability":"https://schema.org/InStock"}})+'</script>'
        self.assertEqual(extract_offer(html)["price"],"49.99")
        with self.assertRaises(ValueError):extract_offer(html+html)
        with self.assertRaises(ValueError):extract_offer("<html>Sold out</html>")
    def test_schema_and_time(self):
        with self.assertRaises(ValueError):invoke(self.app,"list_products",{"limit":True})
        with self.assertRaises(ValueError):invoke(self.app,"record_product",{"url":"https://example.com/a","extra":1})
        with self.assertRaises(ValueError):self.record(date="2026-01-01T00:00:00")
        with self.assertRaises(ValueError):self.record(date="2099-01-01T00:00:00Z")
    def test_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=os.path.join(tmp,"prices.db");app=PriceTracker(path)
            key=app.call("record_product",{"url":"https://example.com/a"})["product"]["id"];app.db.close()
            self.assertEqual(PriceTracker(path).current(key)["product"]["url"],"https://example.com/a")
    def test_collection_allowlist(self):
        from source import fetch_page
        for url in ["http://example.com","https://user:pass@example.com","https://127.0.0.1","https://example.com:444"]:
            with self.assertRaises(ValueError):fetch_page(url,["example.com"])
    def test_protocol_client(self):
        requests=[{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"integration-client","version":"1"}}},
                  {"jsonrpc":"2.0","method":"notifications/initialized"},
                  {"jsonrpc":"2.0","id":2,"method":"tools/list"},
                  {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"record_product","arguments":{"url":"https://example.com/client"}}},
                  {"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"get_current_price","arguments":{"product_id":"absent"}}},
                  {"jsonrpc":"2.0","id":5,"method":"does-not-exist"}]
        result=subprocess.run([sys.executable,"server.py","--db",":memory:"],cwd=Path(__file__).resolve().parents[1],input="\n".join(json.dumps(r) for r in requests)+"\n",capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr);responses=[json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(responses),5);self.assertEqual(responses[0]["result"]["protocolVersion"],"2025-11-25")
        self.assertEqual(len(responses[1]["result"]["tools"]),9);self.assertFalse(responses[2]["result"]["isError"])
        self.assertTrue(responses[3]["result"]["isError"]);self.assertEqual(responses[4]["error"]["code"],-32601)

if __name__=="__main__":unittest.main()
