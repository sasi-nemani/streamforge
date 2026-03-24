"""
tests/test_vcs_integration.py — VCS integration unit tests
============================================================

Tests are written FIRST (RED phase) before any config changes.

Covers:
  1. VCSConfig parses correctly from default.yaml via topic_config
  2. VCS disabled when GITHUB_TOKEN not set
  3. VCS enabled when GITHUB_TOKEN is set (returns GitHubBackend)
  4. SchemaCommitContext validates correctly
  5. VCSResult bool semantics
  6. GitHub branch name format
  7. get_vcs_backend returns None when enabled=False
"""

from __future__ import annotations

import os
import re
import sys
import unittest.mock as mock
from pathlib import Path

import pytest

# Make sure project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from streamforge.vcs import VCSConfig, get_vcs_backend
from streamforge.vcs.base import SchemaCommitContext, VCSResult


# ---------------------------------------------------------------------------
# 1. VCSConfig parses correctly from config via topic_config
# ---------------------------------------------------------------------------

def test_vcs_config_loaded_from_default_yaml():
    """
    topic_config.load_topic_config() must expose a .vcs_config property that
    returns a VCSConfig whose fields match config/default.yaml vcs section.

    After Task 1, the default config enables VCS with the GitHub backend.
    """
    from streamforge.topic_config import load_topic_config

    cfg_root = Path(__file__).parent.parent / "config"
    tc = load_topic_config(topic=None, env="dev", config_root=cfg_root)
    vcs = tc.vcs_config

    assert isinstance(vcs, VCSConfig)
    # Task 1: enabled=true, backend=github in default.yaml
    assert vcs.enabled is True, "VCS should be enabled by default (Task 1)"
    assert vcs.backend == "github", "Default backend should be 'github' (Task 1)"
    assert vcs.remote == "origin"
    assert vcs.default_branch == "main"
    assert vcs.auto_commit is True
    assert vcs.auto_push is True
    assert vcs.auto_pr is True
    assert vcs.pr_base_branch == "main"
    assert "schema-change" in vcs.pr_labels
    assert vcs.commit_author_name == "StreamForge Bot"
    assert "github.com" in vcs.commit_author_email


# ---------------------------------------------------------------------------
# 2. VCS disabled when GITHUB_TOKEN not set
# ---------------------------------------------------------------------------

def test_vcs_disabled_when_no_github_token():
    """
    When the backend is 'github' but GITHUB_TOKEN is absent,
    get_vcs_backend falls back to GitBackend which may or may not be
    available (git on path). What MUST be true is that it does NOT return
    a GitHubBackend instance.
    """
    from streamforge.vcs.github import GitHubBackend

    cfg = VCSConfig(
        enabled=True,
        backend="github",
        github_token="",    # empty — no token
        github_repo="",     # empty — no repo
    )

    env_without_token = {k: v for k, v in os.environ.items()
                         if k not in ("GITHUB_TOKEN", "GITHUB_REPO")}

    with mock.patch.dict(os.environ, env_without_token, clear=True):
        backend = get_vcs_backend(cfg, repo_root=Path("/tmp"))

    # Must NOT be a GitHubBackend when token is absent
    assert not isinstance(backend, GitHubBackend), (
        "Expected GitBackend fallback when GITHUB_TOKEN is absent"
    )


# ---------------------------------------------------------------------------
# 3. VCS enabled when GITHUB_TOKEN is set
# ---------------------------------------------------------------------------

def test_vcs_enabled_when_github_token_set():
    """
    When enabled=True, backend='github', and both GITHUB_TOKEN and
    GITHUB_REPO are present, get_vcs_backend returns a GitHubBackend.
    """
    from streamforge.vcs.github import GitHubBackend

    cfg = VCSConfig(
        enabled=True,
        backend="github",
        github_token="ghp_fake_token_for_testing",
        github_repo="test-org/test-repo",
    )

    backend = get_vcs_backend(cfg, repo_root=Path("/tmp"))
    assert isinstance(backend, GitHubBackend), (
        f"Expected GitHubBackend, got {type(backend)}"
    )


# ---------------------------------------------------------------------------
# 4. SchemaCommitContext validates correctly
# ---------------------------------------------------------------------------

def test_schema_commit_context_has_required_fields():
    """SchemaCommitContext must be constructable with all required fields."""
    ctx = SchemaCommitContext(
        stream_name="events.payments",
        old_version="1.0.0",
        new_version="1.1.0",
        action="accept",
        drift_summary="## Drift\n- amount: type changed",
        tier=2,
        files=[Path("schemas/events.payments/schema.yaml")],
    )

    assert ctx.stream_name == "events.payments"
    assert ctx.old_version == "1.0.0"
    assert ctx.new_version == "1.1.0"
    assert ctx.action == "accept"
    assert ctx.tier == 2
    assert len(ctx.files) == 1
    assert ctx.drift_summary is not None


def test_schema_commit_context_first_init_allows_none_old_version():
    """On first init, old_version is None (no previous schema)."""
    ctx = SchemaCommitContext(
        stream_name="events.payments",
        old_version=None,
        new_version="1.0.0",
        action="init",
    )
    assert ctx.old_version is None
    assert ctx.action == "init"


def test_schema_commit_context_default_files_is_empty_list():
    """files defaults to an empty list, not None."""
    ctx = SchemaCommitContext(
        stream_name="events.iot",
        old_version=None,
        new_version="1.0.0",
        action="init",
    )
    assert ctx.files == []
    assert isinstance(ctx.files, list)


# ---------------------------------------------------------------------------
# 5. VCSResult bool — True on success
# ---------------------------------------------------------------------------

def test_vcs_result_bool_true_on_success():
    """VCSResult(success=True) must evaluate as truthy."""
    result = VCSResult(
        success=True,
        message="Schema committed successfully",
        commit_sha="abc123",
        branch="schema/events.payments/1.1.0",
    )
    assert bool(result) is True
    assert result  # implicit bool check


# ---------------------------------------------------------------------------
# 6. VCSResult bool — False on failure
# ---------------------------------------------------------------------------

def test_vcs_result_bool_false_on_failure():
    """VCSResult(success=False) must evaluate as falsy."""
    result = VCSResult(
        success=False,
        message="Git push failed",
        error="remote: Permission denied",
    )
    assert bool(result) is False
    assert not result  # implicit bool check


def test_vcs_result_str_includes_url_on_success():
    """str(VCSResult) with url should include the PR URL."""
    result = VCSResult(
        success=True,
        message="PR #42: schema(events.payments): accept drift",
        url="https://github.com/org/repo/pull/42",
    )
    as_str = str(result)
    assert "https://github.com" in as_str


def test_vcs_result_str_shows_error_on_failure():
    """str(VCSResult) on failure should mention the error."""
    result = VCSResult(
        success=False,
        message="PR creation failed",
        error="GitHub API 422: validation failed",
    )
    as_str = str(result)
    assert "ERROR" in as_str or "422" in as_str


# ---------------------------------------------------------------------------
# 7. GitHub branch name format
# ---------------------------------------------------------------------------

def test_github_backend_branch_name_format():
    """
    GitHubBackend._branch_name() must return a branch in the format
    schema/<stream-slug>/<version> — e.g. schema/events-payments/1.1.0

    Dots and slashes in stream names are sanitized to dashes so the branch
    name is valid in all git implementations.
    """
    from streamforge.vcs.github import GitHubBackend

    backend = GitHubBackend(
        repo_root=Path("/tmp"),
        github_repo="test-org/test-repo",
        github_token="ghp_test",
    )

    ctx = SchemaCommitContext(
        stream_name="events.payments",
        old_version="1.0.0",
        new_version="1.1.0",
        action="accept",
    )

    branch = backend._branch_name(ctx)
    assert branch.startswith("schema/"), f"Branch should start with 'schema/', got: {branch}"
    # Stream name is sanitized: dots/slashes → dashes
    assert "events" in branch, f"Branch should contain stream name slug, got: {branch}"
    assert "payments" in branch, f"Branch should contain stream name slug, got: {branch}"
    assert "1.1.0" in branch, f"Branch should contain new version, got: {branch}"

    # Full pattern: schema/<stream-slug>/<version>
    pattern = r"^schema/.+/.+$"
    assert re.match(pattern, branch), f"Branch '{branch}' does not match schema/<stream>/<version>"

    # Branch must not contain bare dots in the stream segment (sanitized for git compat)
    # The version segment may have dots — that's expected
    stream_segment = branch.split("/")[1]
    assert "." not in stream_segment, (
        f"Stream segment should be dot-free (sanitized), got: '{stream_segment}'"
    )


# ---------------------------------------------------------------------------
# 8. get_vcs_backend returns None when enabled=False
# ---------------------------------------------------------------------------

def test_get_vcs_backend_returns_none_when_disabled():
    """
    get_vcs_backend must return None immediately when cfg.enabled is False.
    No backend should be constructed.
    """
    cfg = VCSConfig(enabled=False, backend="github")
    backend = get_vcs_backend(cfg, repo_root=Path("/tmp"))
    assert backend is None, (
        f"Expected None when VCS disabled, got {type(backend)}"
    )


def test_get_vcs_backend_returns_none_for_all_backends_when_disabled():
    """All backend types respect enabled=False."""
    for backend_name in ("git", "github", "gitlab"):
        cfg = VCSConfig(enabled=False, backend=backend_name)
        result = get_vcs_backend(cfg, repo_root=Path("/tmp"))
        assert result is None, (
            f"Backend '{backend_name}' with enabled=False should return None"
        )


# ---------------------------------------------------------------------------
# 9. VCSConfig default values are sane
# ---------------------------------------------------------------------------

def test_vcs_config_defaults():
    """Default VCSConfig has sensible values that match the codebase defaults."""
    cfg = VCSConfig()
    assert cfg.enabled is False
    assert cfg.backend == "git"
    assert cfg.remote == "origin"
    assert cfg.default_branch == "main"
    assert cfg.auto_commit is True
    assert cfg.auto_push is True
    assert cfg.auto_pr is True
    assert cfg.github_token == ""
    assert cfg.github_repo == ""
    assert "schema-change" in cfg.pr_labels


def test_vcs_config_github_token_from_explicit_value():
    """VCSConfig stores github_token from explicit constructor arg."""
    cfg = VCSConfig(github_token="ghp_test_token_xyz", github_repo="org/repo")
    assert cfg.github_token == "ghp_test_token_xyz"
    assert cfg.github_repo == "org/repo"


# ---------------------------------------------------------------------------
# 10. Edge cases
# ---------------------------------------------------------------------------

def test_vcs_result_url_is_none_by_default():
    """VCSResult.url is None when not provided (e.g. local git commit)."""
    result = VCSResult(success=True, message="committed")
    assert result.url is None
    assert result.commit_sha is None
    assert result.branch is None
    assert result.error is None


def test_schema_commit_context_drift_summary_optional():
    """drift_summary and tier are optional fields."""
    ctx = SchemaCommitContext(
        stream_name="events.iot",
        old_version=None,
        new_version="1.0.0",
        action="init",
    )
    assert ctx.drift_summary is None
    assert ctx.tier is None


def test_get_vcs_backend_returns_git_backend_when_backend_is_git():
    """When backend='git' and enabled=True, a GitBackend is returned."""
    from streamforge.vcs.git_backend import GitBackend

    cfg = VCSConfig(enabled=True, backend="git")
    backend = get_vcs_backend(cfg, repo_root=Path("/tmp"))
    assert isinstance(backend, GitBackend), (
        f"Expected GitBackend for backend='git', got {type(backend)}"
    )
