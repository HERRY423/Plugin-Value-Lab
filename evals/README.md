# Native self-evaluation cases

These cases test Plugin Value Lab's decision behavior inside Claude Code. They allow only Skill, Read, Glob, and Grep so the plugin's guidance can be loaded and inspected; prompts prohibit network access, unrelated file reads, writes, and shell commands. They require no private data. Each uses outcome graders shared by both arms. The cases are deliberately understandable without the plugin, so a strong baseline may pass every case; that is not evidence of incremental plugin gain.

Cases cover equal perfect scores, a missing baseline, synthetic apparent benefit, and process activation without useful output. An inline assessment is enough: the plugin must not invent a run ledger, launch commands, or claim to have audited raw evidence. A tool allowlist alone is not a filesystem sandbox; run with non-sensitive material and inspect the actual trace when verifying compliance.

The nested `workflows/` group adds four task-routing cases: sufficient native capability, a pending connection, unequal data access, and a score that provides no authority for account changes. Each asks for minimal decision JSON and has both a mechanical decision check and a semantic grader for both arms. The local tests check positive and negative regex behavior; they do not simulate model judging or establish the quality of real conversations.

The files follow the case.yaml format described in the [official plugin eval documentation](https://code.claude.com/docs/en/plugin-evals). JSON is used as the YAML-compatible serialization. Actual native execution may invoke paid model and grader calls; these files and their local syntax validation do not establish host acceptance or a completed evaluation. Run only under the user's authorized model and budget.

After a real run, inspect both arms, grader rationales, refusals, and cost coverage. Passing these guardrails demonstrates those observed behaviors under the recorded conditions. It does not certify this plugin's general utility, independent scientific validity, or production readiness.

The nested `research/` group adds four unexecuted semantic evaluation cases: confounded study design, measurement versus product mechanism, scope revision versus scientific progress, and unknown budget/novelty. They score task-specific alternatives and discriminating next decisions, not a required checklist phrase. These are authored test specifications only; no model or judge run has been performed.
