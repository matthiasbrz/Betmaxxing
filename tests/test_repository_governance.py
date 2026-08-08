"""The governance policy is versioned, so parts of it can be tested mechanically.

Three artefacts carry the rules a contributor has to follow: `CONTRIBUTING.md`,
`SECURITY.md` and the pull-request template. A policy that no longer matches the
repository is worse than none — it tells a newcomer something false with the
authority of a committed file.

What this suite actually checks
------------------------------
1. The three artefacts exist and are not stubs.
2. Named sections and topics are present: the protected branch, the required
   checks, the work-branch-then-pull-request sequence, the `.env` /
   `.env.example` rule, the rotation-first incident procedure, the provider-cost
   declaration.
3. Selected structural constraints: the template really has Markdown checkboxes,
   the merge is gated on something the author cannot grant themselves, the
   reporting section offers a route a reporter can actually take.
4. Secret hygiene on the documents themselves, through the same
   `betmaxxing.security.secret_hygiene` implementation the hook and CI use.
5. Consistency of a few strings with the real repository — the job names
   `quality` and `secrets` are cross-checked against `.github/workflows/ci.yml`,
   so a renamed job cannot leave a stale name in the policy.

What it does not check
----------------------
It does not prove the documents are *correct*. It matches markers, so it cannot
tell a rule from its inverse: a review demonstrated that a `CONTRIBUTING.md`
rewritten to assert the opposite of every rule still passed almost the whole
suite, because the markers it looks for were all still there. Contradictions
between two paragraphs, a qualifier silently dropped, an obligation turned into
a suggestion — none of that is detected here.

The guarantee is therefore narrow, and it is about *objects in the text*, not
about rules. Four things fail this suite, each demonstrated by a mutation
experiment rather than assumed:

* a governance file that is absent;
* a required section that is absent;
* a selected marker gone from the scope a test actually inspects — the whole
  file for some, one `section()` for others;
* a name cross-checked against the real repository, such as a `ci.yml` job name,
  that no longer matches.

What does *not* fail it is a rule losing its normative force while its
vocabulary stays inside the inspected section. Measured, not supposed: a review
deleted the prohibition on direct pushes, and separately the requirement for
explicit merge authorisation, each time leaving the same words in the same
section as a non-binding remark — **74 of 74 tests passed both times**. Move the
same words further away and a test does fail, which shows what is really being
watched: the marker's presence in a scope, not the obligation.

So a green run here means the shapes are still in place. Whether they still
oblige anyone — their meaning — is a question for the human review of the diff,
and no result from this file substitutes for it.

Why the searches stay loose about phrasing
------------------------------------------
A test that pins a sentence gets deleted the first time someone improves the
sentence, and its rule leaves with it. So these look for identifiers and short
propositions rather than sentences, and everything goes through `normalise` so a
line wrap or a pair of asterisks cannot decide the outcome. The negative guards
below are a handful of named regressions, chosen because a review found them —
not an attempt to enumerate every way a document could lie.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

CONTRIBUTING = REPO_ROOT / "CONTRIBUTING.md"
SECURITY = REPO_ROOT / "SECURITY.md"
PR_TEMPLATE = REPO_ROOT / ".github" / "pull_request_template.md"
DECISIONS = REPO_ROOT / "docs" / "decisions.md"

#: The branch every rule here is about.
DEFAULT_BRANCH = "claude/prompt-markdown-file-wag9jw"

#: The two required checks, exactly as the workflow names its jobs.
REQUIRED_CHECKS = ("quality", "secrets")

GOVERNANCE_FILES = (CONTRIBUTING, SECURITY, PR_TEMPLATE)


#: Markdown emphasis and code markers, which carry no meaning for these searches.
_MARKUP = re.compile(r"[*`]+")

#: An underscore used as emphasis — at a word edge, not inside an identifier.
#: `_ready_` loses both; `pull_request` keeps its own.
_EDGE_UNDERSCORE = re.compile(r"(?<!\w)_(?=\w)|(?<=\w)_(?!\w)")

_WHITESPACE = re.compile(r"\s+")


def read(path: Path) -> str:
    """File text, or a clear failure naming the missing artefact."""
    if not path.is_file():
        pytest.fail(f"missing governance artefact: {path.relative_to(REPO_ROOT)}")
    return path.read_text(encoding="utf-8")


def normalise(text: str) -> str:
    """Lowercase, drop simple Markdown emphasis, collapse every run of whitespace.

    Every phrase search in this module goes through here, so a line wrap or a
    pair of asterisks can never on its own decide whether a rule is present.
    That failure mode is not hypothetical: a review found that a document
    asserting the opposite of every rule still passed, because the one marker
    that caught it happened to straddle a line break.
    """
    return _WHITESPACE.sub(" ", _EDGE_UNDERSCORE.sub("", _MARKUP.sub("", text.lower()))).strip()


def flat(path: Path) -> str:
    """A whole file, normalised for phrase searching."""
    return normalise(read(path))


def section(path: Path, heading: str) -> str:
    """One Markdown section, normalised — the body under the heading that starts with `heading`.

    Searching a section instead of the whole file is what makes a claim
    testable: "attested" somewhere in a long document says nothing about the
    paragraph that lists the merge requirements.
    """
    text = read(path)
    opening = re.compile(
        r"^(#{1,6})[ \t]+" + re.escape(heading), re.IGNORECASE | re.MULTILINE
    ).search(text)
    if opening is None:
        pytest.fail(f"{path.name} has no heading starting with {heading!r}")
    level = len(opening.group(1))
    rest = text[opening.end() :]
    closing = re.search(rf"^#{{1,{level}}}[ \t]+\S", rest, re.MULTILINE)
    return normalise(rest[: closing.start()] if closing else rest)


def mentions_any(haystack: str, *needles: str) -> bool:
    return any(needle in haystack for needle in needles)


#: Crude sentence split on normalised text. `:` counts as a boundary because the
#: claim this guards against was written as "… stating plainly: <claim>".
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.;:!?])\s+")

_RULE_WORD = re.compile(r"\brules?\b|\brègles?\b")
_VISIBILITY_CLAIM = re.compile(
    r"becomes? visible|devien\w* visible|stops? being invisible|cesse\w* d'être invisible"
    r"|cannot drift|cannot quietly drift|prevents? (?:the )?(?:rules?|drift)"
)


def sentences_claiming_a_rule_becomes_visible(text: str) -> list[str]:
    """Sentences that promise rule-level detection — a formulation guard, not semantics.

    The suite matches markers. Saying so is fine; saying that *a rule* becomes
    visible is not, because a review removed two normative rules while leaving
    their vocabulary in the inspected section and the whole suite stayed green.
    Sentence-scoped on purpose: a sentence may name a rule, and a sentence may
    talk about visibility, but one sentence claiming both is the overclaim.

    This is a string check on one paragraph. It cannot tell whether a document is
    honest — only whether it repeats the one phrasing a review rejected.
    """
    return [
        sentence
        for sentence in _SENTENCE_BOUNDARY.split(normalise(text))
        if _RULE_WORD.search(sentence) and _VISIBILITY_CLAIM.search(sentence)
    ]


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
        text = flat(CONTRIBUTING)
        assert mentions_any(text, "protected", "protégé", "protégée", "ruleset")

    def test_contributing_forbids_pushing_straight_to_the_default_branch(self) -> None:
        text = flat(CONTRIBUTING)
        assert mentions_any(text, "direct push", "push direct", "never push", "pas de push")

    def test_contributing_requires_a_dedicated_work_branch(self) -> None:
        text = flat(CONTRIBUTING)
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
        text = flat(CONTRIBUTING)
        assert mentions_any(
            text, "before merging", "avant fusion", "avant de fusionner", "required"
        )


class TestTheSequenceFromBranchToMergeIsSpelledOut:
    """Opening a pull request is not the same act as merging it."""

    def test_contributing_describes_a_pull_request_step(self) -> None:
        text = flat(CONTRIBUTING)
        assert mentions_any(text, "pull request", "pr ")

    def test_contributing_separates_the_checks_from_the_merge(self) -> None:
        text = flat(CONTRIBUTING)
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
        text = flat(CONTRIBUTING)
        assert mentions_any(text, "up to date", "à jour")
        assert mentions_any(text, "conversation", "discussion")

    def test_the_template_states_that_opening_a_pr_authorises_nothing(self) -> None:
        text = flat(PR_TEMPLATE)
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
        text = flat(CONTRIBUTING)
        assert mentions_any(
            text, "never commit", "do not commit", "ne jamais commit", "must not commit"
        )
        assert mentions_any(text, "payload", "receipt", "reçu")


class TestTheIncidentProcedureStartsWithRotation:
    """Emptying a file is not remediation. Rotation is."""

    def test_security_tells_the_reader_to_rotate_or_revoke_first(self) -> None:
        text = flat(SECURITY)
        assert mentions_any(text, "rotate", "rotation", "revoke", "révoquer", "révocation")

    def test_security_says_rewriting_history_is_not_enough(self) -> None:
        text = flat(SECURITY)
        assert mentions_any(text, "history", "historique")
        assert mentions_any(
            text, "not enough", "does not make", "ne suffit pas", "not remediation", "insufficient"
        )

    def test_security_forbids_echoing_the_value_or_any_derivative(self) -> None:
        text = flat(SECURITY)
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
        text = flat(SECURITY)
        assert mentions_any(text, "default branch", "branche par défaut", DEFAULT_BRANCH.lower())

    def test_security_separates_the_three_kinds_of_report(self) -> None:
        """A product bug, a leaked credential and bad sports data are not one thing."""
        text = flat(SECURITY)
        assert mentions_any(text, "vulnerability", "vulnérabilité")
        assert mentions_any(text, "credential", "key", "clé")
        assert mentions_any(text, "data", "données", "odds", "cote")

    def test_security_does_not_send_a_secret_to_a_public_issue(self) -> None:
        text = flat(SECURITY)
        assert mentions_any(text, "private", "privé", "privately")
        assert mentions_any(text, "issue", "public")


class TestThePullRequestTemplateForcesADeclaration:
    """Zero is a fine answer; silence is not."""

    def test_it_asks_for_provider_calls_endpoints_attempts_and_credits(self) -> None:
        text = flat(PR_TEMPLATE)
        assert mentions_any(text, "provider", "fournisseur")
        assert mentions_any(text, "credit", "crédit")
        assert mentions_any(text, "endpoint")
        assert mentions_any(text, "attempt", "tentative", "call", "appel")

    def test_it_accepts_zero_or_not_applicable_without_a_false_tick(self) -> None:
        text = flat(PR_TEMPLATE)
        assert mentions_any(text, "not applicable", "n/a", "sans objet", "zero", "0")

    def test_it_asks_about_migrations(self) -> None:
        assert mentions_any(flat(PR_TEMPLATE), "migration", "schema", "schéma", "alembic")

    def test_it_asks_about_models_uncertainty_and_statuses(self) -> None:
        text = flat(PR_TEMPLATE)
        assert mentions_any(text, "model", "modèle")
        assert mentions_any(text, "status", "statut")
        assert mentions_any(text, "uncertainty", "incertitude", "promotion")

    def test_it_asks_for_test_evidence_and_a_rollback_story(self) -> None:
        text = flat(PR_TEMPLATE)
        assert mentions_any(text, "test")
        assert mentions_any(text, "rollback", "revert", "retour arrière", "risk", "risque")

    def test_it_has_real_markdown_checkboxes(self) -> None:
        boxes = re.findall(r"^\s*[-*]\s*\[[ xX]\]", read(PR_TEMPLATE), re.MULTILINE)
        assert len(boxes) >= 6, f"expected a checklist, found {len(boxes)} checkbox(es)"

    def test_its_checklist_covers_the_secret_rules(self) -> None:
        text = flat(PR_TEMPLATE)
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


class TestTheNormalisationDoesNotDecideTheOutcome:
    """Unit tests for `normalise`, on synthetic strings only.

    These do not read the repository. They exist because the searches above are
    only as good as this function: a review found the suite passing a document
    that inverted every rule, and the single marker that caught it did so by the
    accident of a line break.
    """

    @pytest.mark.parametrize(
        ("raw", "phrase"),
        (
            ("autorisation\nexplicite", "autorisation explicite"),
            ("l'**autorisation** explicite", "autorisation explicite"),
            ("les checks `quality` et `secrets`", "quality et secrets"),
            ("passage en _ready for review_", "ready for review"),
            ("*ready*\n  *for*\treview", "ready for review"),
            ("GitHub EXIGE", "github exige"),
        ),
    )
    def test_a_wrap_or_an_emphasis_does_not_hide_a_phrase(self, raw: str, phrase: str) -> None:
        assert phrase in normalise(raw)

    def test_an_underscore_inside_an_identifier_survives(self) -> None:
        """Otherwise `pull_request` and `staking_enabled` stop being searchable."""
        assert "pull_request" in normalise("on:\n  pull_request:")

    def test_it_does_not_invent_a_phrase_that_is_absent(self) -> None:
        """Collapsing whitespace must not make unrelated words adjacent in a false way."""
        assert "autorisation explicite" not in normalise("autorisation implicite")
        assert "ready for review" not in normalise("ready to merge")

    def test_the_phrase_the_audit_missed_is_now_matched_in_the_real_file(self) -> None:
        assert "autorisation explicite du propriétaire" in flat(CONTRIBUTING)


class TestTheRuleVisibilityGuardIsItselfTested:
    """Synthetic strings only — the formulation guard must not be taken on trust."""

    @pytest.mark.parametrize(
        "claim",
        (
            "The guarantee: a rule deleted outright becomes visible.",
            "Ainsi, une règle supprimée devient visible.",
            "Static tests over them, so a rule that is removed stops being invisible.",
            "These tests prevent the rules from drifting.",
        ),
    )
    def test_it_catches_a_sentence_promising_rule_level_detection(self, claim: str) -> None:
        assert sentences_claiming_a_rule_becomes_visible(claim) != []

    @pytest.mark.parametrize(
        "honest",
        (
            "A missing section becomes visible; a rule losing its normative force does not.",
            "It matches markers, so it cannot tell a rule from its inverse.",
            "Removing a rule while its vocabulary stays in the inspected section leaves 74 green.",
            "An absent artefact becomes visible.",
        ),
    )
    def test_it_does_not_fire_on_an_honest_limit_statement(self, honest: str) -> None:
        assert sentences_claiming_a_rule_becomes_visible(honest) == []

    def test_it_is_sentence_scoped_not_document_scoped(self) -> None:
        """Naming a rule in one sentence and visibility in another is not a claim."""
        text = "A deleted section becomes visible. A rule may still be weakened silently."
        assert sentences_claiming_a_rule_becomes_visible(text) == []


class TestTheSuiteStatesWhatItDoesNotProve:
    """A test suite that oversells itself is a governance defect of its own."""

    #: The claim a review rejected: these tests do not stop a rule being inverted.
    OVERCLAIMS = (
        "cannot quietly drift",
        "cannot drift",
        "prevents the rules from drifting",
        "ne peuvent pas dériver",
        "empêche les règles de dériver",
        "deleting a rule must not",
        "a rule deleted outright",
        "une règle supprimée",
    )

    def test_the_module_docstring_names_its_own_limits(self) -> None:
        doc = normalise(__doc__ or "")
        assert mentions_any(doc, "semantic", "meaning"), "must say the semantics are not validated"
        assert mentions_any(doc, "human review", "human reader", "review of the diff"), (
            "must say these tests do not replace reading the diff"
        )
        assert mentions_any(doc, "inversion", "inverted", "contradiction", "reversed"), (
            "must say an inverted rule can still pass"
        )

    def test_no_sentence_of_the_docstring_promises_rule_level_detection(self) -> None:
        """A formulation guard on this file's own claim. Not a semantic validator."""
        offenders = sentences_claiming_a_rule_becomes_visible(__doc__ or "")
        assert offenders == [], (
            "the suite detects files, sections, markers and cross-checked names — "
            f"not rules; offending sentence(s): {offenders}"
        )

    def test_the_docstring_names_the_objects_it_can_actually_detect(self) -> None:
        """The four things the mutation experiments showed do fail the suite."""
        doc = normalise(__doc__ or "")
        assert mentions_any(doc, "file", "artefact", "artifact"), "an absent artefact"
        assert mentions_any(doc, "section", "heading", "rubric"), "an absent required section"
        assert mentions_any(doc, "marker"), "a marker gone from the scope actually inspected"
        assert mentions_any(doc, "cross-check", "cross check", "job name", "name it cross"), (
            "a name checked against the real repository, such as a CI job"
        )

    def test_the_docstring_admits_a_rule_can_lose_its_force_silently(self) -> None:
        """The measured limit: c3b and c3c removed a rule and nothing failed."""
        doc = normalise(__doc__ or "")
        assert mentions_any(doc, "normative", "force"), (
            "must say a rule can lose its normative force undetected"
        )
        assert mentions_any(doc, "vocabulary", "wording stays", "words stay", "keywords"), (
            "must say the vocabulary staying in the inspected section is what hides it"
        )
        assert mentions_any(doc, "74"), "must state the measured count, not a vague caveat"

    def test_the_d070_entry_states_the_limited_guarantee(self) -> None:
        text = section(DECISIONS, "D-070")
        assert mentions_any(text, "human review", "human reader", "review of the diff")
        assert mentions_any(text, "inversion", "inverted", "contradiction", "reversed")
        assert mentions_any(text, "deletion", "deleted", "removal", "removed"), (
            "the real guarantee is that a deleted rule becomes visible"
        )

    @pytest.mark.parametrize(
        "where",
        ("module docstring", "D-070"),
    )
    def test_no_overclaim_survives(self, where: str) -> None:
        text = (
            normalise(__doc__ or "") if where == "module docstring" else section(DECISIONS, "D-070")
        )
        present = [claim for claim in self.OVERCLAIMS if claim in text]
        assert present == [], f"{where} still claims: {present}"

    def test_d070_keeps_the_observed_versus_attested_distinction(self) -> None:
        """Weakening the overclaim must not blur what was actually read back."""
        text = section(DECISIONS, "D-070")
        assert mentions_any(text, "observed", "read back")
        assert mentions_any(text, "attested", "attestation")
        assert "403" in text


class TestContributingQualifiesTheRulesetRequirements:
    """The merge requirements were stated as fact; only two of them were observed."""

    MERGE_SECTION = "Le flux obligatoire"

    def test_the_requirements_are_attributed_to_the_ruleset_configuration(self) -> None:
        text = section(CONTRIBUTING, self.MERGE_SECTION)
        assert "ruleset" in text
        assert mentions_any(text, "configuré", "configurée", "configured"), (
            "an unqualified 'GitHub exige' presents an attestation as a read-back fact"
        )
        assert mentions_any(text, "attestation", "attesté", "attestés", "attested")

    def test_the_check_requirement_cites_an_observation_and_not_a_read_back(self) -> None:
        text = section(CONTRIBUTING, self.MERGE_SECTION)
        assert mentions_any(text, "observé", "observée", "observed")
        assert mentions_any(text, "comportement", "comportemental", "behavioural", "behavioral")
        for check in REQUIRED_CHECKS:
            assert check in text

    def test_the_strict_mode_and_conversation_resolution_stay_attested(self) -> None:
        text = section(CONTRIBUTING, self.MERGE_SECTION)
        assert mentions_any(text, "à jour", "up to date")
        assert mentions_any(text, "conversation", "discussion")
        assert "403" in text, "the reason these two are only attested must be stated"

    def test_the_gh013_observation_is_dated_and_scoped(self) -> None:
        """It happened on another ref, under a ruleset since retargeted."""
        text = section(CONTRIBUTING, self.MERGE_SECTION)
        assert "gh013" in text
        assert mentions_any(text, "branche de travail", "work branch"), (
            "the refusal was observed on a work-branch ref, not on the default branch"
        )
        assert mentions_any(text, "reciblage", "reciblé", "reciblée", "retarget"), (
            "the ruleset was retargeted after that refusal, so it is not current evidence"
        )

    def test_the_gh013_message_is_described_as_a_count_not_as_names(self) -> None:
        text = section(CONTRIBUTING, self.MERGE_SECTION)
        assert mentions_any(text, "compte", "nombre", "count"), (
            "the message said '2 of 2', which is a count"
        )
        assert mentions_any(text, "ne nomme", "sans nommer", "does not name", "pas les noms"), (
            "it never named quality or secrets"
        )

    def test_the_blocked_to_clean_sequence_is_offered_as_compatible_not_causal(self) -> None:
        text = section(CONTRIBUTING, self.MERGE_SECTION)
        assert "blocked" in text and "clean" in text
        assert mentions_any(text, "compatible"), "the sequence is compatible with the requirement"
        assert mentions_any(
            text, "ne prouve pas", "ne prouvent pas", "ne suffit pas", "does not prove"
        ), "other conditions can produce those states; it is not proof on its own"

    def test_the_two_check_names_remain_attested_for_the_current_ruleset(self) -> None:
        text = section(CONTRIBUTING, self.MERGE_SECTION)
        for check in REQUIRED_CHECKS:
            assert check in text
        assert mentions_any(text, "attesté", "attestés", "attestation", "attested")
        assert "403" in text

    def test_the_procedure_still_binds_the_contributor(self) -> None:
        """Qualifying the evidence must not soften a single obligation."""
        text = section(CONTRIBUTING, self.MERGE_SECTION)
        assert mentions_any(text, "push direct", "direct push")
        assert mentions_any(text, "interdit", "forbidden", "refusé")
        assert "autorisation explicite" in text
        assert mentions_any(text, "à jour", "up to date")
        assert mentions_any(text, "conversation", "discussion")
        for check in REQUIRED_CHECKS:
            assert check in text


class TestTheTemplateSeparatesReadyForReview:
    """Opening, going green, being reviewed and merging are four decisions."""

    def test_it_names_ready_for_review(self) -> None:
        assert "ready for review" in flat(PR_TEMPLATE)

    def test_it_says_those_decisions_are_distinct(self) -> None:
        text = flat(PR_TEMPLATE)
        assert mentions_any(
            text, "décisions distinctes", "actions distinctes", "distinct decisions"
        )
        assert mentions_any(text, "ready for review")
        assert mentions_any(text, "fusion", "merge")

    def test_it_still_requires_explicit_authorisation_to_merge(self) -> None:
        assert "autorisation explicite" in flat(PR_TEMPLATE)

    def test_a_ticked_box_is_not_offered_as_sufficient_proof(self) -> None:
        text = flat(PR_TEMPLATE)
        assert mentions_any(text, "cochée à tort", "case cochée", "ticked", "tick"), (
            "the template must say what a tick is not worth"
        )


class TestSecurityGivesAnExternalReporterAPracticablePath:
    """A reporting policy with no reachable channel routes nothing anywhere."""

    REPORTING_SECTION = "Signaler un problème"

    def test_private_vulnerability_reporting_stays_the_preferred_route(self) -> None:
        text = section(SECURITY, self.REPORTING_SECTION)
        assert "private vulnerability reporting" in text
        assert mentions_any(
            text, "s'il est", "si disponible", "if available", "if it is enabled"
        ), "the preferred route is conditional: it may not be switched on"

    def test_there_is_a_fallback_when_no_private_channel_exists(self) -> None:
        text = section(SECURITY, self.REPORTING_SECTION)
        assert mentions_any(text, "issue publique minimale", "minimal public issue")
        assert mentions_any(text, "moyen de contact", "canal privé", "private contact"), (
            "the fallback must ask for a channel, not describe the problem"
        )

    def test_the_fallback_forbids_any_technical_detail_or_sensitive_value(self) -> None:
        text = section(SECURITY, self.REPORTING_SECTION)
        assert mentions_any(text, "sans détail technique", "aucun détail technique")
        assert mentions_any(text, "valeur sensible", "sensitive value", "aucune valeur")

    def test_the_reporting_section_puts_rotation_first_for_a_key(self) -> None:
        text = section(SECURITY, self.REPORTING_SECTION)
        assert mentions_any(text, "rotation", "révocation", "révoquer"), (
            "a reporter who found an exposed key must read 'rotate' here, not three sections down"
        )

    def test_it_still_forbids_publishing_a_secret_in_the_open(self) -> None:
        text = section(SECURITY, self.REPORTING_SECTION)
        assert mentions_any(text, "jamais", "never")
        assert mentions_any(text, "secret", "clé")
        assert mentions_any(text, "issue publique", "public issue")
