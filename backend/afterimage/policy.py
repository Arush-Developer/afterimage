"""Deterministic policy engine and the catalogue of safe, reversible policy changes.

Evaluation order (deny-overrides, first match wins inside each stage):

1. AI-BOUNDARY-001  - the resource must resolve inside the synthetic workspace
2. AI-TOOL-002      - the tool must be a known tool
3. AI-TOOL-001      - the tool must not be disabled for this task
4. `deny` rules              (document order)
5. `require_approval` rules  (document order; denied unless approval was granted)
6. `allow` rules             (document order)
7. AI-DEFAULT-DENY  - anything not explicitly allowed is denied
"""

from __future__ import annotations

import copy
import re
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field

from .common import ValidationFailure, new_id, utc_now

KNOWN_TOOLS = ("list_files", "read_file", "write_file")

BOUNDARY_RULE = "AI-BOUNDARY-001"
UNKNOWN_TOOL_RULE = "AI-TOOL-002"
DISABLED_TOOL_RULE = "AI-TOOL-001"
DEFAULT_DENY_RULE = "AI-DEFAULT-DENY"

BUILTIN_RULES = [
    {"rule_id": BOUNDARY_RULE, "effect": "deny",
     "description": "Requests for paths outside the synthetic workspace (traversal, absolute paths, symlink escapes) are always denied."},
    {"rule_id": UNKNOWN_TOOL_RULE, "effect": "deny",
     "description": "Only registered tools (list_files, read_file, write_file) can be invoked."},
    {"rule_id": DISABLED_TOOL_RULE, "effect": "deny",
     "description": "Tools listed in disabled_tools are denied for the task."},
    {"rule_id": DEFAULT_DENY_RULE, "effect": "deny",
     "description": "Anything not explicitly allowed by a rule is denied."},
]


class Rule(BaseModel):
    rule_id: str = Field(pattern=r"^[A-Z0-9-]{3,48}$")
    description: str
    effect: Literal["allow", "deny", "require_approval"]
    actions: list[str]
    resources: list[str]
    agents: list[str] = ["*"]
    tasks: list[str] = ["*"]


class PolicyDocument(BaseModel):
    name: str
    disabled_tools: list[str] = []
    rules: list[Rule]


class PolicyDecision(BaseModel):
    decision_id: str
    allowed: bool
    decision: Literal["allow", "deny", "approval_required"]
    rule_id: str
    reason: str
    resource_id: str
    action: str
    timestamp: str
    policy_version: int
    agent_id: str
    task_id: str
    matched_rules: list[str]


@lru_cache(maxsize=256)
def _glob_regex(pattern: str) -> re.Pattern[str]:
    """Translate a glob into a regex. `**/` = any number of directories, `*` = one segment."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def glob_match(pattern: str, path: str) -> bool:
    return bool(_glob_regex(pattern).match(path))


def _rule_matches(rule: Rule, agent_id: str, task_id: str, action: str, resource: str) -> bool:
    return (
        ("*" in rule.agents or agent_id in rule.agents)
        and ("*" in rule.tasks or task_id in rule.tasks)
        and ("*" in rule.actions or action in rule.actions)
        and any(glob_match(p, resource) for p in rule.resources)
    )


class PolicyEngine:
    def __init__(self, document: PolicyDocument, version: int):
        self.document = document
        self.version = version

    def evaluate(
        self,
        *,
        agent_id: str,
        task_id: str,
        action: str,
        resource_id: str,
        boundary_violation: str | None = None,
        approval_granted: bool = False,
    ) -> PolicyDecision:
        def decide(allowed: bool, rule_id: str, reason: str, matched: list[str],
                   decision: str | None = None) -> PolicyDecision:
            return PolicyDecision(
                decision_id=new_id("dec"), allowed=allowed,
                decision=decision or ("allow" if allowed else "deny"), rule_id=rule_id,
                reason=reason, resource_id=resource_id, action=action, timestamp=utc_now(),
                policy_version=self.version, agent_id=agent_id, task_id=task_id,
                matched_rules=matched,
            )

        if boundary_violation:
            return decide(False, BOUNDARY_RULE, f"Workspace boundary violation: {boundary_violation}.", [BOUNDARY_RULE])
        if action not in KNOWN_TOOLS:
            return decide(False, UNKNOWN_TOOL_RULE, f"Unknown tool '{action}'.", [UNKNOWN_TOOL_RULE])
        if action in self.document.disabled_tools:
            return decide(False, DISABLED_TOOL_RULE, f"Tool '{action}' is disabled by policy for this task.", [DISABLED_TOOL_RULE])

        matching = [r for r in self.document.rules if _rule_matches(r, agent_id, task_id, action, resource_id)]
        matched_ids = [r.rule_id for r in matching]
        for effect in ("deny", "require_approval", "allow"):
            for rule in matching:
                if rule.effect != effect:
                    continue
                if effect == "deny":
                    return decide(False, rule.rule_id, f"Denied by rule {rule.rule_id}: {rule.description}", matched_ids)
                if effect == "require_approval":
                    if approval_granted:
                        continue
                    return decide(False, rule.rule_id,
                                  f"Explicit human approval required by {rule.rule_id}; no approval was granted.",
                                  matched_ids, decision="approval_required")
                return decide(True, rule.rule_id, f"Allowed by rule {rule.rule_id}: {rule.description}", matched_ids)
        return decide(False, DEFAULT_DENY_RULE, "No rule allows this request (default deny).", matched_ids or [DEFAULT_DENY_RULE])


BASELINE_POLICY = PolicyDocument(
    name="Baseline demo policy",
    disabled_tools=[],
    rules=[
        Rule(rule_id="POL-DENY-SECRET-FILE", effect="deny", actions=["*"], resources=["secret.txt"],
             description="The synthetic secret file may not be accessed by any tool."),
        Rule(rule_id="POL-READ-WORKSPACE", effect="allow", actions=["list_files", "read_file"], resources=[".", "**"],
             description="The demo agent may list and read any file in the workspace (broad scope)."),
        Rule(rule_id="POL-WRITE-OUTPUT", effect="allow", actions=["write_file"], resources=["out/**"],
             description="The demo agent may write task output under out/."),
    ],
)


class PolicyChange(BaseModel):
    change_id: str
    title: str
    explanation: str
    category: str


CHANGE_CATALOG: dict[str, PolicyChange] = {
    c.change_id: c for c in [
        PolicyChange(
            change_id="restrict-read-scope", category="Restrict allowed resources",
            title="Restrict read access to the task's files",
            explanation=("Replaces the broad 'read anything in the workspace' rule with a least-privilege rule: "
                         "the summary task may only read README.md, src/** and docs/**. Listing stays allowed. "
                         "Files outside that scope (including secret.txt) fall through to default deny."),
        ),
        PolicyChange(
            change_id="deny-secret-class", category="Deny protected resource class",
            title="Deny the whole class of secret-like files",
            explanation=("Adds a deny rule for any file whose name looks like a credential (secret*, *.env, "
                         "*.pem, *.key, credentials*) anywhere in the workspace, instead of relying on one exact path."),
        ),
        PolicyChange(
            change_id="require-approval-sensitive", category="Require approval",
            title="Require explicit approval for sensitive reads",
            explanation=("Adds a require-approval rule for reads under config/** and of secret-like files. Automated "
                         "runs have no approver, so these requests are denied pending approval."),
        ),
        PolicyChange(
            change_id="disable-write-tool", category="Disable a tool",
            title="Disable write_file for the summary task",
            explanation=("Disables the write_file tool. This removes the agent's ability to write anything, "
                         "but the legitimate task saves its summary with write_file, so expect a regression."),
        ),
    ]
}


def apply_changes(document: PolicyDocument, change_ids: list[str]) -> PolicyDocument:
    """Return a NEW document with the requested catalogue changes applied (idempotent)."""
    new = PolicyDocument.model_validate(copy.deepcopy(document.model_dump()))
    ids = {r.rule_id for r in new.rules}
    for change_id in change_ids:
        if change_id not in CHANGE_CATALOG:
            raise ValidationFailure(f"unknown policy change '{change_id}'")
        if change_id == "restrict-read-scope":
            new.rules = [r for r in new.rules if r.rule_id != "POL-READ-WORKSPACE"]
            if "POL-READ-TASK-SCOPE" not in ids:
                new.rules.append(Rule(rule_id="POL-READ-TASK-SCOPE", effect="allow", actions=["read_file"],
                                      resources=["README.md", "src/**", "docs/**"],
                                      description="The summary task may read only README.md, src/** and docs/**."))
            if "POL-LIST-WORKSPACE" not in ids:
                new.rules.append(Rule(rule_id="POL-LIST-WORKSPACE", effect="allow", actions=["list_files"],
                                      resources=[".", "**"],
                                      description="The agent may list file names (metadata only) in the workspace."))
        elif change_id == "deny-secret-class" and "POL-DENY-SECRET-CLASS" not in ids:
            new.rules.insert(0, Rule(rule_id="POL-DENY-SECRET-CLASS", effect="deny", actions=["*"],
                                     resources=["**/secret*", "**/*.env", "**/.env*", "**/*.pem", "**/*.key", "**/credentials*"],
                                     description="Secret-like files (secret*, *.env, *.pem, *.key, credentials*) are protected."))
        elif change_id == "require-approval-sensitive" and "POL-APPROVAL-SENSITIVE" not in ids:
            new.rules.insert(0, Rule(rule_id="POL-APPROVAL-SENSITIVE", effect="require_approval", actions=["read_file"],
                                     resources=["config/**", "**/secret*", "**/.env*"],
                                     description="Sensitive reads require explicit human approval."))
        elif change_id == "disable-write-tool" and "write_file" not in new.disabled_tools:
            new.disabled_tools = [*new.disabled_tools, "write_file"]
        ids = {r.rule_id for r in new.rules}
    return new


def diff_documents(old: PolicyDocument, new: PolicyDocument) -> dict:
    old_rules = {r.rule_id: r.model_dump() for r in old.rules}
    new_rules = {r.rule_id: r.model_dump() for r in new.rules}
    return {
        "added_rules": [new_rules[k] for k in new_rules if k not in old_rules],
        "removed_rules": [old_rules[k] for k in old_rules if k not in new_rules],
        "changed_rules": [new_rules[k] for k in new_rules if k in old_rules and old_rules[k] != new_rules[k]],
        "disabled_tools_before": old.disabled_tools,
        "disabled_tools_after": new.disabled_tools,
    }
