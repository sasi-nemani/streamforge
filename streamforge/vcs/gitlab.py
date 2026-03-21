"""
streamforge/vcs/gitlab.py — GitLab Backend
============================================

Extends GitBackend with GitLab Merge Requests API.

Auth: GITLAB_TOKEN env var (personal access token, api scope).
Repo: GITLAB_REPO env var in "group/project" format, or vcs.gitlab_repo in config.
URL:  GITLAB_URL env var for self-hosted instances (default: https://gitlab.com).

Workflow is identical to GitHubBackend:
  branch → commit → push → open MR (with drift report as description).
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote

import httpx

from .base import SchemaCommitContext, VCSResult
from .git_backend import GitBackend

logger = logging.getLogger(__name__)


class GitLabBackend(GitBackend):
    """
    GitBackend + GitLab Merge Requests API.

    Falls back to GitBackend behaviour if token is not set or API call fails.
    """

    def __init__(
        self,
        repo_root: Path,
        gitlab_repo: str,          # "group/project"
        gitlab_token: str,
        gitlab_url: str = "https://gitlab.com",
        remote: str = "origin",
        default_branch: str = "main",
        auto_push: bool = True,
        commit_author_name: str = "StreamForge Bot",
        commit_author_email: str = "streamforge-bot@noreply.local",
    ) -> None:
        super().__init__(
            repo_root=repo_root,
            remote=remote,
            default_branch=default_branch,
            auto_push=auto_push,
            commit_author_name=commit_author_name,
            commit_author_email=commit_author_email,
        )
        self.gitlab_repo = gitlab_repo
        self.gitlab_url = gitlab_url.rstrip("/")
        self._token = gitlab_token
        # URL-encode the "group/project" path for use in API endpoints
        self._project_path = quote(gitlab_repo, safe="")
        self._api_base = f"{self.gitlab_url}/api/v4/projects/{self._project_path}"
        self._headers = {
            "PRIVATE-TOKEN": gitlab_token,
            "Content-Type": "application/json",
        }

    def is_available(self) -> bool:
        if not self._token:
            logger.warning("GITLAB_TOKEN not set — GitLab MR creation disabled")
            return False
        return super().is_available()

    def create_schema_pr(
        self,
        ctx: SchemaCommitContext,
        base_branch: str,
        reviewers: list[str],
        labels: list[str],
    ) -> VCSResult:
        """Branch → commit → push → open GitLab MR."""
        branch_name = self._branch_name(ctx)

        branch_result = self._create_and_checkout_branch(branch_name, base_branch)
        if not branch_result.success:
            return branch_result

        commit_result = self.commit_schema(ctx)
        if not commit_result.success:
            self._checkout(base_branch)
            return commit_result

        mr_result = self._open_merge_request(
            ctx=ctx,
            source_branch=branch_name,
            target_branch=base_branch,
            labels=labels,
        )

        if mr_result.success and mr_result.url and reviewers:
            mr_iid = mr_result.url.rstrip("/").split("/")[-1]
            self._assign_reviewers(mr_iid, reviewers)

        return VCSResult(
            success=mr_result.success,
            message=mr_result.message,
            url=mr_result.url,
            commit_sha=commit_result.commit_sha,
            branch=branch_name,
            error=mr_result.error,
        )

    # ── GitLab API calls ───────────────────────────────────────────────────────

    def _open_merge_request(
        self,
        ctx: SchemaCommitContext,
        source_branch: str,
        target_branch: str,
        labels: list[str],
    ) -> VCSResult:
        title = self._mr_title(ctx)
        description = self._mr_description(ctx)

        try:
            resp = httpx.post(
                f"{self._api_base}/merge_requests",
                headers=self._headers,
                json={
                    "source_branch": source_branch,
                    "target_branch": target_branch,
                    "title": title,
                    "description": description,
                    "labels": ",".join(labels),
                    "remove_source_branch": True,   # clean up after merge
                    "squash": False,
                },
                timeout=15,
            )

            if resp.status_code in (200, 201):
                mr = resp.json()
                url = mr.get("web_url", "")
                logger.info("GitLab MR created: %s", url)
                return VCSResult(
                    success=True,
                    message=f"MR !{mr['iid']}: {title}",
                    url=url,
                )

            # Already exists
            if resp.status_code == 409:
                existing = self._find_existing_mr(source_branch, target_branch)
                if existing:
                    return VCSResult(success=True, message=f"MR already open: {existing}", url=existing)

            error_msg = f"GitLab API {resp.status_code}: {resp.text[:200]}"
            logger.error("Failed to create MR: %s", error_msg)
            return VCSResult(success=False, message="MR creation failed", error=error_msg)

        except httpx.TimeoutException:
            return VCSResult(success=False, message="GitLab API timeout", error="Request timed out")
        except Exception as e:
            logger.exception("Unexpected error creating GitLab MR")
            return VCSResult(success=False, message="MR creation failed", error=str(e))

    def _assign_reviewers(self, mr_iid: str, reviewers: list[str]) -> None:
        """Assign reviewers by username (requires looking up user IDs first)."""
        try:
            user_ids = []
            for username in reviewers:
                resp = httpx.get(
                    f"{self.gitlab_url}/api/v4/users",
                    headers=self._headers,
                    params={"username": username},
                    timeout=10,
                )
                users = resp.json()
                if users:
                    user_ids.append(users[0]["id"])

            if user_ids:
                httpx.put(
                    f"{self._api_base}/merge_requests/{mr_iid}",
                    headers=self._headers,
                    json={"reviewer_ids": user_ids},
                    timeout=10,
                )
        except Exception as e:
            logger.warning("Could not assign MR reviewers: %s", e)

    def _find_existing_mr(self, source: str, target: str) -> str | None:
        try:
            resp = httpx.get(
                f"{self._api_base}/merge_requests",
                headers=self._headers,
                params={"source_branch": source, "target_branch": target, "state": "opened"},
                timeout=10,
            )
            mrs = resp.json()
            return mrs[0].get("web_url") if mrs else None
        except Exception:
            return None

    # ── MR content formatting ──────────────────────────────────────────────────

    def _mr_title(self, ctx: SchemaCommitContext) -> str:
        if ctx.action == "accept":
            tier_tag = f" [T{ctx.tier}]" if ctx.tier else ""
            return f"schema({ctx.stream_name}): accept drift {ctx.old_version} → {ctx.new_version}{tier_tag}"
        if ctx.action == "init":
            return f"schema({ctx.stream_name}): baseline schema {ctx.new_version}"
        return f"schema({ctx.stream_name}): {ctx.action} {ctx.new_version}"

    def _mr_description(self, ctx: SchemaCommitContext) -> str:
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

        if ctx.drift_summary:
            parts += ["", "---", "", "## Drift Report", "", ctx.drift_summary, ""]

        parts += [
            "---",
            "",
            "## Review checklist",
            "",
            "- [ ] Schema changes are accurate",
            "- [ ] PII fields are correctly tagged",
            "- [ ] Downstream consumers notified",
            "- [ ] Version bump is appropriate",
            "",
            "/assign_reviewer @" + " @".join(["schema-team"]) if True else "",
            "",
            "_Generated by StreamForge_",
        ]

        return "\n".join(parts)
