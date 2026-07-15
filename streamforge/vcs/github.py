"""
streamforge/vcs/github.py — GitHub Backend
============================================

Extends GitBackend with GitHub Pulls API to open PRs on drift acceptance.

Auth: GITHUB_TOKEN env var (classic PAT or fine-grained with repo + pull_requests scope).
Repo: GITHUB_REPO env var in "owner/repo" format, or vcs.github_repo in config.

PR workflow:
  1. git checkout -b schema/<stream>/<new_version>
  2. git commit schema files
  3. git push origin schema/<stream>/<new_version>
  4. POST /repos/{owner}/{repo}/pulls  → PR URL returned in VCSResult.url
  5. PATCH reviewers + labels if configured

The PR body is the drift_summary from SchemaCommitContext (the markdown drift report).
This gives reviewers full context without leaving GitHub.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from .base import SchemaCommitContext, VCSResult
from .git_backend import GitBackend

logger = logging.getLogger(__name__)

_GH_API = "https://api.github.com"
_ACCEPT = "application/vnd.github+json"
_API_VERSION = "2022-11-28"


class GitHubBackend(GitBackend):
    """
    GitBackend + GitHub Pulls API.

    Falls back to GitBackend behaviour (branch + commit + push, no PR)
    if GITHUB_TOKEN is not set or the API call fails.
    """

    def __init__(
        self,
        repo_root: Path,
        github_repo: str,          # "owner/repo"
        github_token: str,
        remote: str = "origin",
        default_branch: str = "main",
        auto_push: bool = True,
        commit_author_name: str = "StreamForge Bot",
        commit_author_email: str = "streamforge-bot@noreply.github.com",
    ) -> None:
        super().__init__(
            repo_root=repo_root,
            remote=remote,
            default_branch=default_branch,
            auto_push=auto_push,
            commit_author_name=commit_author_name,
            commit_author_email=commit_author_email,
        )
        self.github_repo = github_repo
        self._token = github_token
        self._headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": _ACCEPT,
            "X-GitHub-Api-Version": _API_VERSION,
        }

    def is_available(self) -> bool:
        if not self._token:
            logger.warning("GITHUB_TOKEN not set — GitHub PR creation disabled")
            return False
        return super().is_available()

    def create_schema_pr(
        self,
        ctx: SchemaCommitContext,
        base_branch: str,
        reviewers: list[str],
        labels: list[str],
    ) -> VCSResult:
        """
        Branch → commit → push → open GitHub PR.
        Adds reviewers and labels if configured.
        """
        branch_name = self._branch_name(ctx)

        # Create branch and commit
        branch_result = self._create_and_checkout_branch(branch_name, base_branch)
        if not branch_result.success:
            return branch_result

        commit_result = self.commit_schema(ctx)
        if not commit_result.success:
            self._checkout(base_branch)
            return commit_result

        # Open PR via GitHub API
        pr_result = self._open_pull_request(
            ctx=ctx,
            head_branch=branch_name,
            base_branch=base_branch,
        )

        if pr_result.success and pr_result.url:
            # Add reviewers and labels in parallel requests
            pr_number = pr_result.url.rstrip("/").split("/")[-1]
            if reviewers:
                self._request_reviewers(pr_number, reviewers)
            if labels:
                self._add_labels(pr_number, labels)

        return VCSResult(
            success=pr_result.success,
            message=pr_result.message,
            url=pr_result.url,
            commit_sha=commit_result.commit_sha,
            branch=branch_name,
            error=pr_result.error,
        )

    # ── GitHub API calls ───────────────────────────────────────────────────────

    def _open_pull_request(
        self,
        ctx: SchemaCommitContext,
        head_branch: str,
        base_branch: str,
    ) -> VCSResult:
        title = self._pr_title(ctx)
        body = self._pr_body(ctx)

        try:
            resp = httpx.post(
                f"{_GH_API}/repos/{self.github_repo}/pulls",
                headers=self._headers,
                json={
                    "title": title,
                    "body": body,
                    "head": head_branch,
                    "base": base_branch,
                    "draft": False,
                },
                timeout=15,
            )

            if resp.status_code == 201:
                pr = resp.json()
                logger.info("GitHub PR created: %s", pr["html_url"])
                return VCSResult(
                    success=True,
                    message=f"PR #{pr['number']}: {title}",
                    url=pr["html_url"],
                )

            # Handle "PR already exists" gracefully
            if resp.status_code == 422:
                errors = resp.json().get("errors", [])
                for e in errors:
                    if "pull request already exists" in str(e.get("message", "")).lower():
                        # Find existing PR
                        existing = self._find_existing_pr(head_branch, base_branch)
                        if existing:
                            return VCSResult(
                                success=True,
                                message=f"PR already open: {existing}",
                                url=existing,
                            )

            error_msg = f"GitHub API {resp.status_code}: {resp.text[:200]}"
            logger.error("Failed to create PR: %s", error_msg)
            return VCSResult(success=False, message="PR creation failed", error=error_msg)

        except httpx.TimeoutException:
            return VCSResult(success=False, message="GitHub API timeout", error="Request timed out")
        except Exception as e:
            logger.exception("Unexpected error creating GitHub PR")
            return VCSResult(success=False, message="PR creation failed", error=str(e))

    def _request_reviewers(self, pr_number: str, reviewers: list[str]) -> None:
        try:
            httpx.post(
                f"{_GH_API}/repos/{self.github_repo}/pulls/{pr_number}/requested_reviewers",
                headers=self._headers,
                json={"reviewers": reviewers},
                timeout=10,
            )
        except Exception as e:
            logger.warning("Could not add reviewers: %s", e)

    def _add_labels(self, pr_number: str, labels: list[str]) -> None:
        try:
            # Ensure labels exist first
            for label in labels:
                httpx.post(
                    f"{_GH_API}/repos/{self.github_repo}/labels",
                    headers=self._headers,
                    json={"name": label, "color": "0075ca"},
                    timeout=10,
                )
            httpx.post(
                f"{_GH_API}/repos/{self.github_repo}/issues/{pr_number}/labels",
                headers=self._headers,
                json={"labels": labels},
                timeout=10,
            )
        except Exception as e:
            logger.warning("Could not add labels: %s", e)

    def _find_existing_pr(self, head: str, base: str) -> str | None:
        try:
            resp = httpx.get(
                f"{_GH_API}/repos/{self.github_repo}/pulls",
                headers=self._headers,
                params={"head": f"{self.github_repo.split('/')[0]}:{head}", "base": base, "state": "open"},
                timeout=10,
            )
            prs = resp.json()
            return prs[0]["html_url"] if prs else None
        except Exception:
            return None

    # ── PR content formatting ──────────────────────────────────────────────────

    def _pr_title(self, ctx: SchemaCommitContext) -> str:
        if ctx.action == "accept":
            tier_tag = f" [T{ctx.tier}]" if ctx.tier else ""
            return f"schema({ctx.stream_name}): accept drift {ctx.old_version} → {ctx.new_version}{tier_tag}"
        if ctx.action == "init":
            return f"schema({ctx.stream_name}): baseline schema {ctx.new_version}"
        return f"schema({ctx.stream_name}): {ctx.action} {ctx.new_version}"

    def _pr_body(self, ctx: SchemaCommitContext) -> str:
        parts = [
            f"## Schema Change — `{ctx.stream_name}`",
            "",
            "| Field | Value |",
            "|---|---|",
            f"| Stream | `{ctx.stream_name}` |",
            f"| Action | `{ctx.action}` |",
        ]
        if ctx.old_version:
            parts.append(f"| Version | `{ctx.old_version}` → `{ctx.new_version}` |")
        else:
            parts.append(f"| Version | `{ctx.new_version}` (initial) |")
        if ctx.tier:
            tier_labels = {1: "Tier 1 — Non-breaking", 2: "Tier 2 — Breaking", 3: "Tier 3 — Critical"}
            parts.append(f"| Highest Drift Tier | {tier_labels.get(ctx.tier, str(ctx.tier))} |")

        parts += [""]

        if ctx.drift_summary:
            parts += [
                "---",
                "",
                "## Drift Report",
                "",
                ctx.drift_summary,
                "",
            ]

        parts += [
            "---",
            "",
            "## Review checklist",
            "",
            "- [ ] Schema changes are accurate",
            "- [ ] PII fields are correctly tagged",
            "- [ ] Downstream consumers have been notified",
            "- [ ] Version bump is appropriate (major/minor/patch)",
            "",
            "_Generated by [StreamForge](https://github.com/sasi-nemani/streamforge)_",
        ]

        return "\n".join(parts)
