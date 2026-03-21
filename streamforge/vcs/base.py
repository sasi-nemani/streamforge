"""
streamforge/vcs/base.py — VCS Backend Protocol
================================================

Every VCS backend (Git, GitHub, GitLab) satisfies this interface.

Design decisions:
  - Never raises: all methods return VCSResult. Callers decide whether to abort
    or continue. A VCS failure must never crash a watch or init cycle.
  - Stateless operations: no persistent connection. Each call is self-contained.
  - Schema files only: the VCS module only touches schema files, drift reports,
    and config. It has no knowledge of Kafka, inference, or drift detection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class VCSResult:
    """Return value for every VCS operation."""
    success: bool
    message: str
    url: str | None = None           # PR / MR URL when created
    commit_sha: str | None = None    # SHA of the new commit
    branch: str | None = None        # branch created or operated on
    error: str | None = None         # raw error string for logging

    def __bool__(self) -> bool:
        return self.success

    def __str__(self) -> str:
        if self.success:
            parts = [self.message]
            if self.url:
                parts.append(f"→ {self.url}")
            return "  ".join(parts)
        return f"[VCS ERROR] {self.error or self.message}"


@dataclass
class SchemaCommitContext:
    """
    Describes a schema change to be committed.
    Passed to commit_schema() and create_schema_pr().
    """
    stream_name: str
    old_version: str | None     # None on first init
    new_version: str
    action: str                 # "init" | "accept" | "scan"
    drift_summary: str | None = None    # markdown drift summary for PR body
    tier: int | None = None             # highest drift tier (for PR labels)
    files: list[Path] = field(default_factory=list)  # files changed


@runtime_checkable
class VCSBackend(Protocol):
    """
    Contract every VCS backend must satisfy.

    Implementations:
      GitBackend    — local git repo (subprocess, no extra deps)
      GitHubBackend — GitBackend + GitHub Pulls API (httpx)
      GitLabBackend — GitBackend + GitLab MR API (httpx)
    """

    def is_available(self) -> bool:
        """
        True if the backend is usable (git installed, token present, etc).
        Called once at startup; if False, VCS operations are silently skipped.
        """
        ...

    def commit_schema(
        self,
        ctx: SchemaCommitContext,
    ) -> VCSResult:
        """
        Stage ctx.files and create a commit on the current branch.
        Used by: init, scan (no PR — just commit + push).
        """
        ...

    def create_schema_pr(
        self,
        ctx: SchemaCommitContext,
        base_branch: str,
        reviewers: list[str],
        labels: list[str],
    ) -> VCSResult:
        """
        Create a new branch, commit ctx.files, push, and open a PR/MR.
        Used by: accept (drift acknowledged → schema version bump → PR).

        Returns VCSResult with url = the PR/MR URL.
        """
        ...

    def current_branch(self) -> str:
        """Return the current git branch name (for informational display)."""
        ...

    def latest_commit_sha(self) -> str | None:
        """Return the SHA of HEAD, or None if repo has no commits."""
        ...
