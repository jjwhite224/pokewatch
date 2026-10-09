---
name: pokewatch-ux-design
description: Improve PokéWatch dashboard information hierarchy, accessible interaction, responsive layouts, and trustworthy stock/price presentation without inventing inventory confirmations.
---

# Dashboard UX and visual design

## Read first
Read `AGENTS.md`, `README.md`, `static/index.html`, `static/style.css`, `static/app.js`, `static/nearby.js`, `static/community.js`, and frontend tests relevant to the task.

## Design principles
- Prioritize a collector's decisions: what product, which variant, which seller, current price, reference type, stock confidence, timestamp, and direct retailer link.
- Make `in stock`, `out of stock`, `unknown`, `stale`, and `partial source` distinct by **text and icon**, not color alone.
- Never present nearby retail locations as inventory confirmations. Differentiate hosted read-only features from local-only watches/desktop alerts.
- Create a deliberate visual hierarchy through typography, spacing, contrast, grid, and responsive behavior, not stock dashboard templates or gratuitous gradients.
- Respect mobile widths, keyboard-only navigation, accessible form labels, visible focus, semantic regions, readable tap targets, contrast, reduced motion, and screen-reader announcements.
- Preserve filters, searching, direct links, and explicit refresh semantics; a browser refresh never claims to trigger a store scan.
- Preserve location privacy and user-controlled permission flows.

## Workflow
1. Audit core tasks: find a specific product, compare offers, interpret source-health issues, find a nearby store, follow a product link.
2. Record existing affordances and confusing or inaccessible states. Propose a hierarchy before modifying markup.
3. Make targeted HTML/CSS/JS changes; avoid breaking local vs Pages mode.
4. Test empty, loading, stale, error, narrow viewport, long title, missing image, and keyboard flows.
5. Update/add frontend tests where feasible; report any manual visual or accessibility checks not performed.

## Definition of done
State affected screens, rationale, responsive behavior, accessibility implications, regression-test outcomes, and remaining visual review needs. Do not invent usability study results.
