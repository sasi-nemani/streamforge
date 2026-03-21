"""
streamforge/vcs — Version Control System Integration
=====================================================

Factory module. Usage:

    from streamforge.vcs import get_vcs_backend, VCSConfig

    cfg = VCSConfig(
        enabled=True,
        backend="github",
        github_repo="my-org/streamforge-schemas",
        auto_pr=True,
    )
    backend = get_vcs_backend(cfg, repo_root=Path("."))
    if backend and backend.is_available():
        result = backend.commit_schema(ctx)
        print(result)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from .base import SchemaCommitContext, VCSBackend, VCSResult

logger = logging.getLogger(__name__)


@dataclass
class VCSConfig:
    """
    All VCS-related configuration. Typically populated from config/default.yaml
    and the vcs section via topic_config.py.
    """
    enabled: bool = False

    # "git" | "github" | "gitlab"
    backend: str = "git"

    # Git settings
    remote: str = "origin"
    default_branch: str = "main"
    auto_commit: bool = True     # commit after init/scan
    auto_push: bool = True       # push to remote
    auto_pr: bool = True         # open PR on accept (github/gitlab only)

    pr_base_branch: str = "main"
    pr_reviewers: list[str] = field(default_factory=list)
    pr_labels: list[str] = field(default_factory=lambda: ["schema-change"])

    commit_author_name: str = "StreamForge Bot"
    commit_author_email: str = "streamforge-bot@noreply.local"

    # GitHub
    github_repo: str = ""        # "owner/repo"
    github_token: str = ""       # GITHUB_TOKEN env var

    # GitLab
    gitlab_url: str = "https://gitlab.com"
    gitlab_repo: str = ""        # "group/project"
    gitlab_token: str = ""       # GITLAB_TOKEN env var


def get_vcs_backend(cfg: VCSConfig, repo_root: Path | None = None) -> VCSBackend | None:
    """
    Construct the right VCS backend from config.

    Returns None if VCS is disabled or unavailable — callers should check
    `if backend:` before using it.
    """
    if not cfg.enabled:
        return None

    root = (repo_root or Path(".")).resolve()

    common = {
        "repo_root": root,
        "remote": cfg.remote,
        "default_branch": cfg.default_branch,
        "auto_push": cfg.auto_push,
        "commit_author_name": cfg.commit_author_name,
        "commit_author_email": cfg.commit_author_email,
    }

    if cfg.backend == "github":
        from .github import GitHubBackend

        token = cfg.github_token or os.environ.get("GITHUB_TOKEN", "")
        repo = cfg.github_repo or os.environ.get("GITHUB_REPO", "")

        if not token or not repo:
            logger.warning(
                "GitHub backend selected but GITHUB_TOKEN / GITHUB_REPO not set. "
                "Falling back to local git."
            )
            from .git_backend import GitBackend
            return GitBackend(**common)

        return GitHubBackend(
            github_repo=repo,
            github_token=token,
            **common,
        )

    if cfg.backend == "gitlab":
        from .gitlab import GitLabBackend

        token = cfg.gitlab_token or os.environ.get("GITLAB_TOKEN", "")
        repo = cfg.gitlab_repo or os.environ.get("GITLAB_REPO", "")
        url = os.environ.get("GITLAB_URL", cfg.gitlab_url)

        if not token or not repo:
            logger.warning(
                "GitLab backend selected but GITLAB_TOKEN / GITLAB_REPO not set. "
                "Falling back to local git."
            )
            from .git_backend import GitBackend
            return GitBackend(**common)

        return GitLabBackend(
            gitlab_repo=repo,
            gitlab_token=token,
            gitlab_url=url,
            **common,
        )

    # Default: local git only
    from .git_backend import GitBackend
    return GitBackend(**common)


__all__ = [
    "VCSConfig",
    "VCSResult",
    "VCSBackend",
    "SchemaCommitContext",
    "get_vcs_backend",
]
