"""
streamforge/vcs/git_backend.py — Local Git Backend
====================================================

Wraps subprocess git. Zero extra dependencies — if git is on PATH, this works.

Design decisions:
  - Every operation is wrapped in try/except and returns VCSResult. A broken
    git repo, detached HEAD, or missing remote never crashes StreamForge.
  - Author identity is set per-commit via --author flag, not via git config,
    so this doesn't pollute the user's global git config.
  - We only stage the specific schema/config files — never `git add .`.
    This prevents accidentally committing secrets or large binaries.
  - Commit message follows Conventional Commits:
      schema(events.payments): init v1.0.0
      schema(events.payments): accept drift v1.1.0 → v1.2.0 [tier 2]
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .base import SchemaCommitContext, VCSResult

logger = logging.getLogger(__name__)


class GitBackend:
    """
    Local git backend — commits and pushes schema files.

    Designed to be subclassed by GitHubBackend / GitLabBackend which
    override create_schema_pr() to add remote PR creation.
    """

    def __init__(
        self,
        repo_root: Path,
        remote: str = "origin",
        default_branch: str = "main",
        auto_push: bool = True,
        commit_author_name: str = "StreamForge Bot",
        commit_author_email: str = "streamforge-bot@noreply.local",
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.remote = remote
        self.default_branch = default_branch
        self.auto_push = auto_push
        self._author = f"{commit_author_name} <{commit_author_email}>"

    # ── VCSBackend protocol ────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """True if git is on PATH and we are inside a git repo."""
        try:
            result = self._git("rev-parse", "--is-inside-work-tree", check=False)
            return result.returncode == 0
        except FileNotFoundError:
            logger.warning("git not found on PATH — VCS integration disabled")
            return False

    def commit_schema(self, ctx: SchemaCommitContext) -> VCSResult:
        """Stage schema files and commit on the current branch."""
        try:
            # Stage only the specified files
            staged = self._stage_files(ctx.files)
            if not staged:
                return VCSResult(
                    success=True,
                    message="No schema changes to commit (files unchanged)",
                )

            message = self._build_commit_message(ctx)
            sha = self._commit(message)
            if sha is None:
                return VCSResult(success=False, message="Commit failed", error="git commit returned no SHA")

            push_result = VCSResult(success=True, message="")
            if self.auto_push:
                push_result = self._push(self.current_branch())

            return VCSResult(
                success=push_result.success,
                message=f"Committed {len(staged)} file(s): {message}",
                commit_sha=sha,
                branch=self.current_branch(),
                error=push_result.error,
            )
        except Exception as e:
            logger.exception("Unexpected error in commit_schema")
            return VCSResult(success=False, message="commit_schema failed", error=str(e))

    def create_schema_pr(
        self,
        ctx: SchemaCommitContext,
        base_branch: str,
        reviewers: list[str],
        labels: list[str],
    ) -> VCSResult:
        """
        GitBackend fallback: create branch + commit + push.
        Subclasses override this to add remote PR creation.
        """
        branch_name = self._branch_name(ctx)
        branch_result = self._create_and_checkout_branch(branch_name, base_branch)
        if not branch_result.success:
            return branch_result

        commit_result = self.commit_schema(ctx)
        if not commit_result.success:
            self._checkout(base_branch)   # restore on failure
            return commit_result

        # Return without a PR URL — subclasses will add it
        return VCSResult(
            success=True,
            message=f"Branch {branch_name!r} pushed — open a PR manually or use --backend github/gitlab",
            commit_sha=commit_result.commit_sha,
            branch=branch_name,
        )

    def current_branch(self) -> str:
        try:
            r = self._git("rev-parse", "--abbrev-ref", "HEAD", check=False)
            return r.stdout.strip() if r.returncode == 0 else "unknown"
        except Exception:
            return "unknown"

    def latest_commit_sha(self) -> str | None:
        try:
            r = self._git("rev-parse", "HEAD", check=False)
            return r.stdout.strip() if r.returncode == 0 else None
        except Exception:
            return None

    # ── Internal git helpers ───────────────────────────────────────────────────

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        cmd = ["git", "-C", str(self.repo_root), *args]
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check,
        )

    def _stage_files(self, files: list[Path]) -> list[Path]:
        """Stage files that exist and have changes. Returns list of staged files."""
        staged: list[Path] = []
        for f in files:
            if not f.exists():
                logger.debug("Skipping non-existent file: %s", f)
                continue
            # Check if file has changes vs HEAD (new or modified)
            status = self._git("status", "--porcelain", str(f), check=False)
            if status.stdout.strip():
                self._git("add", str(f))
                staged.append(f)
                logger.debug("Staged: %s", f)
        return staged

    def _commit(self, message: str) -> str | None:
        """Create a commit. Returns SHA on success, None on failure."""
        result = self._git(
            "commit",
            "--author", self._author,
            "-m", message,
            check=False,
        )
        if result.returncode != 0:
            # "nothing to commit" is not an error
            if "nothing to commit" in result.stdout or "nothing to commit" in result.stderr:
                logger.debug("Nothing to commit")
                return self.latest_commit_sha()
            logger.error("git commit failed: %s", result.stderr)
            return None
        return self.latest_commit_sha()

    def _push(self, branch: str) -> VCSResult:
        result = self._git(
            "push", self.remote, branch,
            "--set-upstream",
            check=False,
        )
        if result.returncode != 0:
            logger.warning("git push failed: %s", result.stderr.strip())
            return VCSResult(
                success=False,
                message="Push failed",
                error=result.stderr.strip(),
                branch=branch,
            )
        return VCSResult(success=True, message=f"Pushed {branch} → {self.remote}", branch=branch)

    def _create_and_checkout_branch(self, name: str, from_branch: str) -> VCSResult:
        # Ensure we start from the right base
        self._git("fetch", self.remote, check=False)
        result = self._git("checkout", "-b", name, f"{self.remote}/{from_branch}", check=False)
        if result.returncode != 0:
            # Branch may already exist (retry from accept) — check it out
            result2 = self._git("checkout", name, check=False)
            if result2.returncode != 0:
                return VCSResult(
                    success=False,
                    message=f"Could not create branch {name!r}",
                    error=result.stderr.strip(),
                )
        return VCSResult(success=True, message=f"Checked out branch {name!r}", branch=name)

    def _checkout(self, branch: str) -> None:
        self._git("checkout", branch, check=False)

    # ── Formatting helpers ─────────────────────────────────────────────────────

    def _build_commit_message(self, ctx: SchemaCommitContext) -> str:
        if ctx.action == "init":
            return f"schema({ctx.stream_name}): init {ctx.new_version}"
        if ctx.action == "accept":
            tier_tag = f" [tier {ctx.tier}]" if ctx.tier else ""
            return (
                f"schema({ctx.stream_name}): accept drift "
                f"{ctx.old_version} → {ctx.new_version}{tier_tag}"
            )
        if ctx.action == "scan":
            return f"schema({ctx.stream_name}): auto-discovered {ctx.new_version}"
        return f"schema({ctx.stream_name}): {ctx.action} {ctx.new_version}"

    def _branch_name(self, ctx: SchemaCommitContext) -> str:
        safe_stream = ctx.stream_name.replace(".", "-").replace("/", "-")
        return f"schema/{safe_stream}/{ctx.new_version}"
