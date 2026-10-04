# MCP Price Tracker

A design brief for an assistant-accessible service that records product prices and explains price changes with source evidence.

**Status: concept stage.** This repository currently contains only this README. It does not yet include an MCP server, scraper, database, package manifest, tests or a runnable client configuration.

## Intended workflow

A user supplies a product URL, the service collects a price observation from a supported source, and an assistant can retrieve current observations or compare a product's history. Every observation should include currency, availability, source URL and capture time so that stale or incomparable prices are visible.

## Proposed tools

These are proposed interfaces, not tools available to call today.

| Tool | Intended input | Intended result |
| --- | --- | --- |
| Record a product | Supported product URL | Product identifier and collection status |
| Get current price | Product identifier | Latest price, currency, availability and timestamp |
| Get price history | Product identifier and date range | Ordered, source-linked observations |
| Compare products | Product identifiers | Comparable prices with currency and variant caveats |
| Explain a change | Product identifier and period | Evidence-backed summary of observed movement |

A discount claim should be calculated against an explicit historical reference. Shipping, taxes, membership pricing and variants should be recorded separately rather than silently combined.

## Implementation plan

1. Implement one source adapter with fixtures for missing, changed and malformed prices.
2. Define a normalized observation schema and persistent storage.
3. Add an MCP transport and validated tool inputs.
4. Separate scheduled collection from assistant queries.
5. Add deduplication, retry limits, stale-data indicators and source-level failure reporting.
6. Test the protocol with a real MCP client before publishing configuration examples.

## Boundaries

Use permitted sources and respect their access rules. Never infer an unobserved price, present a missing product as zero cost, or treat a currency mismatch as a discount. Historical observations are evidence of captured pages, not a guarantee of checkout availability.

## Getting started

There is no executable quick start yet. The first working release should include a dependency manifest, documented transport, local startup command, example client configuration and a fixture-based test command.

## Contributions and license

A useful first contribution is a fixture-backed adapter or the observation schema. No license file is currently included; an explicit license is needed before releasing implementation code.
