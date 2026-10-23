# Owner control kit

This repository ships a small set of files that keep it under its owner's control. The same kit can be copied into any other repository.

**What is already true on GitHub without any setup:** nobody except you (and collaborators you invite) can push to your repository. Strangers can only fork it, open issues and open pull requests. The kit protects against the remaining risks: merging a bad PR by accident, CI abuse from forks, hijacked GitHub Actions and leaked secrets.

## Files in the repository

| File | What it does |
|---|---|
| `.github/CODEOWNERS` | Makes the owner the required reviewer for every file. |
| `.github/rulesets/main-protection.json` | Ruleset to import: no deletion or force-push of `main`, changes only via PR with code-owner approval and green CI. The owner (admin role) can bypass. |
| `.github/workflows/ci.yml` | Safe CI: `pull_request` trigger only, read-only token, actions pinned to commit SHAs, secret scan on every run. |
| `.github/dependabot.yml` | Keeps the pinned actions updated through PRs that you review. |
| `SECURITY.md` | Private vulnerability reporting instead of public issues. |
| `CONTRIBUTING.md`, `pull_request_template.md` | States the rules for outside contributions up front. |
| `.gitignore` | Keeps `.env`, keys and build output out of git. |

## One-time settings (about 3 minutes, in the browser)

These cannot be stored in files, so set them once per repository.

1. **Settings → Rules → Rulesets → New ruleset → Import a ruleset** and pick `.github/rulesets/main-protection.json`. Save.
   If a push from an automation (for example a Claude session) is rejected afterwards, either push through a PR or add that app under "Bypass list".
2. **Settings → Code security**: enable *Secret scanning*, *Push protection*, *Private vulnerability reporting* and *Dependabot alerts*.
3. **Settings → Actions → General**:
   - *Fork pull request workflows from outside collaborators*: **Require approval for all outside collaborators**.
   - *Workflow permissions*: **Read repository contents** and leave "Allow GitHub Actions to create and approve pull requests" **unchecked**.
4. **Settings → General → Features**: turn off *Wikis* and *Projects* if you do not use them (fewer places for spam).
5. **Settings → Collaborators**: keep the list empty unless you really need a co-maintainer.

## Using the kit in another repository

Copy `.github/CODEOWNERS`, `.github/rulesets/`, `.github/dependabot.yml`, `SECURITY.md`, `CONTRIBUTING.md` and the `.gitignore` secret rules, replace the username if needed, then repeat the one-time settings above.
