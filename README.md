# MCP Price Tracker

A runnable, local-first price-evidence product: MCP tools, persistent SQLite history, a browser workspace, an allowlisted JSON-LD collector, currency-aware comparisons, and price threshold checks.

## Run the product

Python 3.11 or later; no third-party packages or API keys required.

```bash
python server.py --web --demo
```

Open **http://127.0.0.1:8765**. Record a source URL, SKU, item price, currency and availability. Inspect history and observed change, compare selected products, save thresholds and check them. The demo observations are synthetic, old and intentionally marked stale.

To run the MCP server instead:

```bash
python server.py --db data/prices.sqlite
```

It reads newline-delimited JSON-RPC from stdin and reserves stdout for MCP responses. Supports the **2025-11-25** protocol via stdio, including initialization, ping, tool discovery and tool calls. No HTTP MCP transport is advertised. The browser companion uses a separate localhost API.

## MCP client configuration

Replace both paths with the absolute checkout and database paths on your machine. Use your Python 3.11+ executable if `python` points elsewhere.

```json
{
  "mcpServers": {
    "price-tracker": {
      "command": "python",
      "args": ["/absolute/path/mcp-price-tracker/server.py", "--db", "/absolute/path/mcp-price-tracker/data/prices.sqlite"]
    }
  }
}
```

| Tool | Behavior |
|---|---|
| `record_product` | Register URL/SKU and optionally ingest an explicit observation or supplied JSON-LD HTML snapshot |
| `collect_price` | Fetch an explicitly allowlisted public HTTPS source and extract one unambiguous Product offer |
| `list_products` | Paginated inventory and latest evidence |
| `get_current_price` | Latest price, currency, availability, capture time, source and stale status |
| `get_price_history` | Paginated ordered observations with optional inclusive ISO datetime bounds |
| `compare_products` | Latest observations grouped by currency; no fabricated exchange conversion |
| `explain_change` | Absolute and percentage movement against the first capture in the selected window |
| `set_price_alert` | Save a currency-specific threshold |
| `check_alerts` | Evaluate thresholds; stale/out-of-stock observations do not trigger |

Example `record_product` arguments:

```json
{"url":"https://example.com/product","title":"Headphones","variant":"black","observation":{"price":"109.00","currency":"USD","availability":"InStock"}}
```

An omitted capture timestamp means now. Missing prices remain missing, not zero. Price values are decimal strings with valid currency precision. Supported currencies: USD, EUR, GBP, INR, CAD, AUD, JPY, CHF, NZD, SGD. Availability: InStock, OutOfStock, PreOrder, Unknown. Shipping and tax may be recorded as separate notes.

## Optional live collection

Configure exact source hostnames that you are permitted to fetch:

```bash
PRICE_ALLOWED_HOSTS=shop.example.com python server.py --db data/prices.sqlite --collect
```

Only public HTTPS addresses are allowed. TLS uses a pinned validated DNS address; redirects, credentials, alternate ports and oversized/non-HTML responses are rejected. Sources must expose one JSON-LD Product offer; select a SKU when multiple product variants exist. Missing or ambiguous prices return errors, preserving prior evidence. No JavaScript rendering or arbitrary CSS scraping is claimed.

`--collect` performs one sweep and prints collection outcomes and alert matches. An external scheduler can invoke it periodically. It does not install a recurring job or send notifications. Per-source failures appear in the result; network requests have a 10-second timeout and an 800-KB body cap.

## Tests and architecture

```bash
python -m unittest discover -s tests -v
```

Tests cover decimal precision, invalid prices, atomic recording, idempotency, conflict detection, variants, persistence, date validation, stale and unavailable alerts, currency mismatches, JSON-LD ambiguity, allowlist rejection, and subprocess MCP client initialization/discovery/calls. Web integration tests verify actual HTTP endpoints, request limits and host/origin protection.

- `engine.py`: tool contracts, SQLite transactions, history and comparison rules.
- `source.py`: constrained source collection.
- `core.py`: dependency-free MCP transport and localhost UI server.
- `web/`: browser workspace; no remote analytics or CDNs.

The browser server binds to 127.0.0.1 and rejects foreign Host/Origin headers. It is a local companion, not a public multi-user deployment. Staleness threshold is 24 hours. Prices are captured observations, not a checkout guarantee or an explanation of seller intent. The integration client is included in tests; no claim of certification by every MCP host is made.

Protocol reference: https://modelcontextprotocol.io/specification/2025-11-25/basic/transports

MIT licensed. Example data is synthetic.
