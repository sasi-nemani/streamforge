# Publishing StreamForge Action to GitHub Marketplace

## Prerequisites
- GitHub account/org: `streamforge` (or your username)
- The action must live at the ROOT of a dedicated repo, not a subdirectory

## Step 1: Create the dedicated action repo

```bash
# Create repo: streamforge/streamforge-action
gh repo create streamforge/streamforge-action \
  --public \
  --description "Block breaking Kafka schema changes in CI — like a type checker, for event streams"
```

## Step 2: Push action files

```bash
cd streamforge-action/
git init
git add action.yml README.md
git commit -m "feat: initial StreamForge Schema Drift Gate action"
git remote add origin https://github.com/streamforge/streamforge-action.git
git push -u origin main
```

## Step 3: Create a release (required for Marketplace)

```bash
gh release create v1.0.0 \
  --repo streamforge/streamforge-action \
  --title "StreamForge Schema Drift Gate v1.0.0" \
  --notes "Initial release. Blocks breaking Kafka schema changes in CI.

## What's included
- Composite action (no Docker, fast startup)
- Auto-discovers topics from committed schemas/ directory
- Blocks Tier 3 (critical) drift by default, configurable
- Posts drift report as PR comment when GITHUB_TOKEN available"
```

## Step 4: Publish to Marketplace (GitHub UI)

1. Go to: https://github.com/streamforge/streamforge-action/releases
2. Click your `v1.0.0` release → Edit
3. Check: **"Publish this Action to the GitHub Marketplace"**
4. Fill in:
   - **Primary category**: `Continuous integration`
   - **Secondary category**: `Code quality`
5. Click "Update release"

## Step 5: Verify Marketplace listing

URL will be: https://github.com/marketplace/actions/streamforge-schema-drift-gate

## Step 6: Update references in main repo

Once published, update `schema-guard.yml` in this repo to reference the marketplace action:

```yaml
# Before (uses local action)
- uses: ./streamforge-action

# After (uses marketplace)
- uses: streamforge/streamforge-action@v1
```

## Notes on the composite action

The action installs StreamForge from the GitHub source:
```
pip install git+https://github.com/sasi-nemani/streamforge.git@main
```

Once the package is published to PyPI as `streamforge-cli`, update this to:
```
pip install streamforge-cli==X.Y.Z
```

## PyPI publishing (when ready)

```bash
# Build
pip install build twine
python -m build

# Upload to PyPI
python -m twine upload dist/*
```

Then update the Dockerfile and action install step to use `pip install streamforge-cli`.
