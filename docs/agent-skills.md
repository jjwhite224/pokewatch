# PokéWatch agent skills

These five skills document how a coding agent should work on PokéWatch. They are **not** background monitoring jobs, installed runtime Python modules, or guarantees that an agent autonomously invokes them.

| Skill | Use it when |
| --- | --- |
| `pokewatch-retailer-reliability` | Adding or repairing retailer data sources, matching, references, or stock claims |
| `pokewatch-ux-design` | Improving dashboard design, accessibility, responsive behavior, or error states |
| `pokewatch-price-intelligence` | Planning/implementing historical price storage or charts |
| `pokewatch-regression-testing` | Adding tests or evaluating a code change |
| `pokewatch-security-privacy` | Touching external URLs, secrets, published state, or browser location |

## Use
1. Open the repository in an agent-capable coding environment that supports project skills.
2. Read `AGENTS.md` for global project standards.
3. Invoke the applicable skill by its frontmatter name if supported, or prompt: **Follow `.agents/skills/pokewatch-retailer-reliability/SKILL.md` to audit the Walmart reader; report evidence and proposed tests before changing code.**
4. Inspect the diff, run the indicated test commands, and review results before merging.

## Suggested experiments
- **Data quality:** Compare a general-purpose audit prompt with the retailer-reliability skill on identical synthetic blocked-source/duplicate-variant fixtures. Record true findings, false positives, and missed problems.
- **Design:** Compare a generic dashboard redesign with the UX skill on the same interface and explicit usability tasks; manually evaluate hierarchy, keyboard access, and trust signals.
- **Analytics:** Prototype a price history graphic with synthetic records first. Do not publish illustrative price trends as live evidence.

## Current implementation status
This addition supplies instruction files and a usage guide only. It does not install agent software, add new retailer integrations, change price/stock runtime behavior, create a historical dataset, or reconfigure scheduled scans.
