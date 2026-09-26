> 归档于 2026-09-25；保留既有接口和实施历史，不代表当前主线或重新验收。当前入口见 [README](../../README.zh-CN.md) 与 [操作指南](../OPERATIONS.md)。

# Decision evidence and host evidence

Value Lab owns paired host execution, computational outcome checks, costs, human review and scoped gain estimates. Research planning and team adoption records are consumers of evaluation evidence, not alternative definitions of value. Plugin Management retains discovery/connection/account-management responsibilities.

An offline decision benchmark can evaluate scenarios, held-out scoring and action selection. This is a generic evidence category, defined without relying on any named external project. Synthetic decisions must not become host sessions or measured biological outcomes.

For a reviewable reference between the layers:

```sh
python scripts/value_lab.py link-decision-evidence study-directory decision-results.json --reference offline-study:study-identifier --evidence-type synthetic --output evidence-link.json
```

The link records the opaque source file's SHA-256, a user-supplied provenance reference and evidence type, and the host protocol and run ledger hashes. It checks the host lock, preserves each evidence layer, and produces no merged value verdict. It neither executes the external artifact nor trusts instructions inside it. This is an implemented generic interchange boundary.

## Future outlook: Epistemic Plugin Arena

Epistemic Plugin Arena is a proposed future direction, not an established external project or a present architectural dependency. A future implementation could supply offline decision scenarios. Integration would first require an inspectable repository, versioned public schema, independently reviewed scenario validity and an executed adapter acceptance study. Until then, no Arena compatibility, partnership, score interchange or validation is claimed. Value Lab's current evidence boundary stands on its own.
