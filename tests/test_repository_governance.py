"""The governance policy is versioned, so it can be tested like anything else.

Three artefacts carry the rules a contributor has to follow: `CONTRIBUTING.md`,
`SECURITY.md` and the pull-request template. Prose that nobody checks drifts
away from the repository it describes, and a policy that has drifted is worse
than none — it tells a newcomer something false with the authority of a
committed file.

What these tests are for
------------------------
They assert *contracts*, not wording. Each one names a property the policy must
still express — the default branch is protected, direct pushes are refused, the
required checks are these two, a leaked key is rotated before anything else —
and looks for stable markers of it. Rewriting a paragraph must stay free;
deleting a rule must not.

Why they are deliberately loose about phrasing
----------------------------------------------
A test that pins a sentence gets deleted the first time someone improves the
sentence, and its rule leaves with it. So these look for the identifiers that
cannot be paraphrased — the branch name, the job names, `.env`, `.env.example`,
the word "rotate" near a key incident — and accept any prose around them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

CONTRIBUTING = REPO_ROOT / "CONTRIBUTING.md"
SECURITY = REPO_ROOT / "SECURITY.md"
PR_TEMPLATE = REPO_ROOT / ".github" / "pull_request_template.md"

#: The branch every rule here is about.
DEFAULT_BRANCH = "claude/prompt-markdown-file-wag9jw"

#: The two required checks, exactly as the workflow names its jobs.
REQUIRED_CHECKS = ("quality", "secrets")

GOVERNANCE_FILES = (CONTRIBUTING, SECURITY, PR_TEMPLATE)


def read(path: Path) -> str:
    """File text, or a clear failure naming the missing artefact."""
    if not path.is_file():
        pytest.fail(f"missing governance artefact: {path.relative_to(REPO_ROOT)}")
    return path.read_text(encoding="utf-8")


def lowered(path: Path) -> str:
    return read(path).lower()


def mentions_any(haystack: str, *needles: str) -> bool:
    return any(needle in haystack for needle in needles)


class TestTheGovernanceArtefactsExist:
    @pytest.mark.parametrize("path", GOVERNANCE_FILES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
    def test_the_file_is_present_and_not_a_stub(self, path: Path) -> None:
        text = read(path)
        assert len(text.strip()) > 400, "a governance file that says nothing governs nothing"
        assert text.lstrip().startswith("#"), "expected a Markdown document with a heading"


class TestTheProtectedBranchAndTheRefusalOfDirectPushes:
    """The rule that the whole tranche exists to make explicit."""

    def test_contributing_names_the_default_branch(self) -> None:
        assert DEFAULT_BRANCH in read(CONTRIBUTING)

    def test_contributing_says_the_default_branch_is_protected(self) -> None:
        text = lowered(CONTRIBUTING)
        assert mentions_any(text, "protected", "protégé", "protégée", "ruleset")

    def test_contributing_forbids_pushing_straight_to_the_default_branch(self) -> None:
        text = lowered(CONTRIBUTING)
        assert mentions_any(text, "direct push", "push direct", "never push", "pas de push")

    def test_contributing_requires_a_dedicated_work_branch(self) -> None:
        text = lowered(CONTRIBUTING)
        assert mentions_any(
            text, "work branch", "working branch", "branche de travail", "feature branch"
        )


class TestTheRequiredChecksAreNamed:
    """Named exactly, because the ruleset matches these strings case-sensitively."""

    @pytest.mark.parametrize("check", REQUIRED_CHECKS)
    def test_contributing_names_the_required_check(self, check: str) -> None:
        assert check in read(CONTRIBUTING)

    @pytest.mark.parametrize("check", REQUIRED_CHECKS)
    def test_the_pull_request_template_names_the_required_check(self, check: str) -> None:
        assert check in read(PR_TEMPLATE)

    def test_contributing_ties_them_to_merging(self) -> None:
        text = lowered(CONTRIBUTING)
        assert mentions_any(
            text, "before merging", "avant fusion", "avant de fusionner", "required"
        )


class TestTheSequenceFromBranchToMergeIsSpelledOut:
    """Opening a pull request is not the same act as merging it."""

    def test_contributing_describes_a_pull_request_step(self) -> None:
        text = lowered(CONTRIBUTING)
        assert mentions_any(text, "pull request", "pr ")

    def test_contributing_separates_the_checks_from_the_merge(self) -> None:
        text = lowered(CONTRIBUTING)
        assert mentions_any(text, "merge", "fusion", "fusionner")
        assert mentions_any(
            text,
            "explicit authorisation",
            "explicit authorization",
            "autorisation explicite",
            "owner's authorisation",
            "owner authorisation",
            "only after",
        ), "the merge must be gated on something the author cannot grant themselves"

    def test_contributing_mentions_up_to_date_and_resolved_conversations(self) -> None:
        text = lowered(CONTRIBUTING)
        assert mentions_any(text, "up to date", "à jour")
        assert mentions_any(text, "conversation", "discussion")

    def test_the_template_states_that_opening_a_pr_authorises_nothing(self) -> None:
        text = lowered(PR_TEMPLATE)
        assert mentions_any(text, "merge", "fusion")
        assert mentions_any(
            text,
            "does not authorise",
            "does not authorize",
            "not authorised",
            "not authorized",
            "n'autorise pas",
            "no merge",
            "pas de fusion",
        )


class TestTheSecretRules:
    """`.env` local, `.env.example` empty — the exact rule that was broken twice."""

    @pytest.mark.parametrize("path", (CONTRIBUTING, SECURITY), ids=("contributing", "security"))
    def test_the_policy_mentions_the_local_env_file(self, path: Path) -> None:
        assert ".env" in read(path)

    def test_contributing_requires_the_template_to_stay_empty(self) -> None:
        text = read(CONTRIBUTING)
        assert ".env.example" in text
        lower = text.lower()
        assert mentions_any(lower, "empty", "vide", "without value", "no value", "sans valeur")

    def test_contributing_forbids_committing_secrets_and_raw_payloads(self) -> None:
        text = lowered(CONTRIBUTING)
        assert mentions_any(
            text, "never commit", "do not commit", "ne jamais commit", "must not commit"
        )
        assert mentions_any(text, "payload", "receipt", "reçu")


class TestTheIncidentProcedureStartsWithRotation:
    """Emptying a file is not remediation. Rotation is."""

    def test_security_tells_the_reader_to_rotate_or_revoke_first(self) -> None:
        text = lowered(SECURITY)
        assert mentions_any(text, "rotate", "rotation", "revoke", "révoquer", "révocation")

    def test_security_says_rewriting_history_is_not_enough(self) -> None:
        text = lowered(SECURITY)
        assert mentions_any(text, "history", "historique")
        assert mentions_any(
            text, "not enough", "does not make", "ne suffit pas", "not remediation", "insufficient"
        )

    def test_security_forbids_echoing_the_value_or_any_derivative(self) -> None:
        text = lowered(SECURITY)
        assert mentions_any(
            text,
            "never print",
            "do not print",
            "never display",
            "do not display",
            "never paste",
            "without printing",
            "never echo",
            "ne pas afficher",
            "ne jamais afficher",
            "sans afficher",
            "ne pas publier",
        )
        assert mentions_any(text, "fragment", "prefix", "derivative", "hash", "length", "partial")

    def test_security_scopes_what_is_supported(self) -> None:
        text = lowered(SECURITY)
        assert mentions_any(text, "default branch", "branche par défaut", DEFAULT_BRANCH.lower())

    def test_security_separates_the_three_kinds_of_report(self) -> None:
        """A product bug, a leaked credential and bad sports data are not one thing."""
        text = lowered(SECURITY)
        assert mentions_any(text, "vulnerability", "vulnérabilité")
        assert mentions_any(text, "credential", "key", "clé")
        assert mentions_any(text, "data", "données", "odds", "cote")

    def test_security_does_not_send_a_secret_to_a_public_issue(self) -> None:
        text = lowered(SECURITY)
        assert mentions_any(text, "private", "privé", "privately")
        assert mentions_any(text, "issue", "public")


class TestThePullRequestTemplateForcesADeclaration:
    """Zero is a fine answer; silence is not."""

    def test_it_asks_for_provider_calls_endpoints_attempts_and_credits(self) -> None:
        text = lowered(PR_TEMPLATE)
        assert mentions_any(text, "provider", "fournisseur")
        assert mentions_any(text, "credit", "crédit")
        assert mentions_any(text, "endpoint")
        assert mentions_any(text, "attempt", "tentative", "call", "appel")

    def test_it_accepts_zero_or_not_applicable_without_a_false_tick(self) -> None:
        text = lowered(PR_TEMPLATE)
        assert mentions_any(text, "not applicable", "n/a", "sans objet", "zero", "0")

    def test_it_asks_about_migrations(self) -> None:
        assert mentions_any(lowered(PR_TEMPLATE), "migration", "schema", "schéma", "alembic")

    def test_it_asks_about_models_uncertainty_and_statuses(self) -> None:
        text = lowered(PR_TEMPLATE)
        assert mentions_any(text, "model", "modèle")
        assert mentions_any(text, "status", "statut")
        assert mentions_any(text, "uncertainty", "incertitude", "promotion")

    def test_it_asks_for_test_evidence_and_a_rollback_story(self) -> None:
        text = lowered(PR_TEMPLATE)
        assert mentions_any(text, "test")
        assert mentions_any(text, "rollback", "revert", "retour arrière", "risk", "risque")

    def test_it_has_real_markdown_checkboxes(self) -> None:
        boxes = re.findall(r"^\s*[-*]\s*\[[ xX]\]", read(PR_TEMPLATE), re.MULTILINE)
        assert len(boxes) >= 6, f"expected a checklist, found {len(boxes)} checkbox(es)"

    def test_its_checklist_covers_the_secret_rules(self) -> None:
        text = lowered(PR_TEMPLATE)
        assert ".env.example" in text
        assert mentions_any(text, "secret", "key", "clé")


class TestNoGovernanceFileLeaksAnything:
    """These documents describe an incident, so they are the likeliest place to slip."""

    #: A bare hexadecimal run is what this project's credentials look like. The
    #: guard in `betmaxxing.security.secret_hygiene` uses the same shape, so the
    #: policy files are held to the rule they document.
    CREDENTIAL_SHAPE = re.compile(r"\b[0-9a-fA-F]{16,}\b")

    #: Identifiers from the real activations must never appear. Matching is on
    #: *shape*, not on a stored copy of any real value.
    REAL_IDENTIFIER_HINTS = re.compile(r"\b(?:apiKey=[^\s&\"'`)]+|Bearer\s+\S+)", re.IGNORECASE)

    @pytest.mark.parametrize("path", GOVERNANCE_FILES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
    def test_it_contains_nothing_shaped_like_a_credential(self, path: Path) -> None:
        found = self.CREDENTIAL_SHAPE.findall(read(path))
        assert found == [], f"{path.name} carries {len(found)} credential-shaped token(s)"

    @pytest.mark.parametrize("path", GOVERNANCE_FILES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
    def test_it_carries_no_authenticated_url_or_header(self, path: Path) -> None:
        assert self.REAL_IDENTIFIER_HINTS.findall(read(path)) == []

    @pytest.mark.parametrize("path", GOVERNANCE_FILES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
    def test_it_invents_no_url_into_the_local_receipt_directory(self, path: Path) -> None:
        """Receipts are local files. A link to one is a fabricated reference."""
        pattern = re.compile(r"https?://[^\s)`\"']*\.activation-receipts", re.IGNORECASE)
        assert pattern.findall(read(path)) == []

    @pytest.mark.parametrize("path", GOVERNANCE_FILES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
    def test_the_shared_secret_guard_finds_nothing(self, path: Path) -> None:
        """One rule, applied to the documents that describe it."""
        from betmaxxing.security import secret_hygiene

        findings = secret_hygiene.scan_text(read(path), path=str(path.name))
        assert findings == [], "; ".join(str(finding) for finding in findings)


class TestThePolicyStaysConsistentWithTheWorkflow:
    """If the workflow renames a job, the policy must not keep the old name."""

    def test_the_named_checks_are_the_jobs_the_workflow_defines(self) -> None:
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        declared = set(re.findall(r"^  (\w[\w-]*):$", workflow, re.MULTILINE))
        for check in REQUIRED_CHECKS:
            assert check in declared, f"{check} is not a job in ci.yml (jobs: {sorted(declared)})"

    def test_the_workflow_still_runs_on_pull_request(self) -> None:
        """The required checks can only gate a PR if the workflow reacts to one."""
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        assert re.search(r"^\s*pull_request:\s*$", workflow, re.MULTILINE) is not None
