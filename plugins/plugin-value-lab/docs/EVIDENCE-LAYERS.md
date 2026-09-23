# Decision evidence and host evidence

Value Lab owns paired host execution, computational outcome checks, costs, human review and scoped gain estimates. Research planning and team adoption records are consumers of evaluation evidence, not alternative definitions of value. Plugin Management retains discovery/connection/account-management responsibilities.

An offline decision benchmark, including Epistemic Plugin Arena, can own scenarios, held-out scoring and action-selection criteria. Its synthetic decisions must not become host sessions or measured biological outcomes. No Arena repository is required to use Value Lab, and no compatibility with an uninspected Arena schema is claimed.

For a reviewable reference between the layers:

```sh
python scripts/value_lab.py link-decision-evidence study-directory decision-results.json --reference arena:study-identifier --evidence-type synthetic --output evidence-link.json
```

The link records the opaque source file's SHA-256, a user-supplied provenance reference and evidence type, and the host protocol and run ledger hashes. It checks the host lock, preserves each evidence layer, and produces no merged value verdict. It neither executes the external artifact nor trusts instructions inside it. This is an implemented generic interchange boundary, not a verified integration with a particular Arena version.
