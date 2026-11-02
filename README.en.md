# Making "Honesty" an `exit 1` CI Gate

> This document distills a set of honesty-enforcement patterns extracted from a
> multi-agent reinforcement learning + blockchain consensus source code research
> project ([marl-ecdsa](https://github.com/TrueFurina/marl-ecdsa)). The project
> itself is closed-source, but the **methodology** for enforcing research integrity
> through CI automation is shared here as a reusable reference.

---

## The Problem

Research codebases accumulate numeric claims that drift from source-of-truth
over time. Numbers appear in READMEs, papers, and dashboards—but the
"source of truth" for those numbers often lives in a JSON ledger that nobody
enforces. The result: a README says `42.3%` while the registry says `44.1%`,
and nobody notices for months.

## The Four Patterns

### 1. Don't Try to Understand — Block Known Regressions

Abandon semantic understanding of the content. Instead, maintain an explicit
deny-list (`FORBIDDEN_PHRASES`) of known bad patterns:

- "approximately", "roughly", "estimated"
- "comparable to X" (without a footnote source)
- Placeholder values like `TODO`, `XX%`, `??`

The scanner exits with code 1 if any phrase matches. This is a **blocklist**,
not a quality detector—by design.

### 2. Mention ≠ Use (Strip Quoted Context First)

A common false positive: documentation *explaining* a bad pattern by quoting
it in backticks. Use `_QUOTE_RE` to strip inline code, fenced blocks, and
blockquote markers **before** keyword matching. This keeps explanatory prose
clean while still catching bare violations.

### 3. Overturn, Don't Delete — Mark It Void

When a number needs to be retracted, don't remove it. Mark it with an
exemption marker (`EXEMPT_MARKERS`, 30+ patterns):

- `[SUPERSEDED:2026-10-15]`
- `<!-- retired: wrong baseline -->`
- `[VOIDED:regression-bug#441]`

The marker survives in Git history and serves as an audit trail. Deleting
evidence teaches future contributors to hide their mistakes.

### 4. Numbers Go to the Registry *First*

The `number_registry.json` is a **write-ahead ledger** (189+ entries). Every
number that will appear in any published artifact must be registered there
first—with its source, recalculation formula, and date.

```text
Pipeline:  experiment → registry.json → figure/README/dashboard
              ^^^^^^^^^^
              this is the commit boundary
```

If a number isn't in the registry, the CI gate fails before it reaches a
figure caption.

---

## Why This Matters

| Scenario | Without honesty enforcement | With honesty enforcement |
|---|---|---|
| Copy-paste number drift | Silent for months | Caught in PR CI |
| "Approximate" language in a claim | Accepted casually | Explicit block, forces precision |
| Wrong number retracted | Deleted, history rewritten | Marked void, preserved for audit |
| New figure from unaudited number | Shipped with plausible-looking error | Blocked at commit |

---

## Implementation Sketch

The gate is a single Python script that:

1. Walks `.md`, `.html`, and `.ipynb` files in the target directory
2. Strips quoted/fenced content (`_QUOTE_RE`)
3. Matches against `FORBIDDEN_PHRASES` and `EXEMPT_MARKERS`
4. Cross-references numeric tokens against `number_registry.json`
5. Exits `1` on any unmatched violation

Integrate as a GitHub Actions step or pre-commit hook. **No LLM required**—the
blocklist is static and deterministic.

---

## License

MIT. See [LICENSE](LICENSE).

## Related

- [TrueFurina/marl-ecdsa](https://github.com/TrueFurina/marl-ecdsa) — the source project this methodology was extracted from
- [TrueFurina/SecAutoMind](https://github.com/TrueFurina/SecAutoMind) — related security validation platform that carries the honesty narrative
