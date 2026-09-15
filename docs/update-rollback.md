# Update and rollback Marcel

These instructions apply to the source checkout installed by the Marcel
installer. They are written for a user with an existing installation and do
not require a provider credential.

## Before updating

1. Record the current version and commit:

   ```bash
   marcel --version
   git -C "$HOME/.marcel/marcel-agent" rev-parse HEAD
   ```

   On Windows, use the installation directory passed to
   `scripts/install.ps1` in place of `$HOME/.marcel/marcel-agent`.
2. Stop any long-running Marcel process that owns the checkout.
3. Copy the Marcel home directory (normally `~/.marcel`) and any local
   configuration to protected storage. Never put API keys in a commit or
   support bundle.
4. Read the release notes and verify the release tag's SHA-256 manifest before
   changing the checkout.

## Normal update routes

The two supported routes are:

### `marcel update`

Run this from the installed checkout:

```bash
marcel update
```

Follow the prompt, or use `marcel update --yes` when the installed version
advertises that option. The updater preserves local changes through its normal
update handling and refreshes the environment for the new checkout. Confirm
the result:

```bash
marcel --version
git -C "$HOME/.marcel/marcel-agent" status --short
```

### Re-run the installer

For an installer-managed checkout, download the installer from the repository
at the desired release ref and run it over the existing installation. Do not
pipe an unreviewed script from a moving branch:

```bash
curl -fsSL \
  https://raw.githubusercontent.com/AdMind-ai/marcel-agent/<TAG>/scripts/install.sh \
  -o /tmp/marcel-install.sh
bash /tmp/marcel-install.sh --non-interactive --commit <COMMIT_SHA>
```

On Windows, download `scripts/install.ps1` at the same tag and pass
`-NonInteractive -Commit <COMMIT_SHA>`. The commit must be the SHA verified
from the release evidence. Re-running the installer is an update route, not a
source-archive publisher.

## Rollback

Rollback means returning the code and environment to a previously qualified
commit; it does not delete the Marcel home directory or credentials.

1. Stop Marcel and save the current version, commit, and logs.
2. Choose a previously qualified tag and resolve its commit:

   ```bash
   git -C "$HOME/.marcel/marcel-agent" fetch --tags --force
   git -C "$HOME/.marcel/marcel-agent" rev-parse '<PREVIOUS_TAG>^{commit}'
   ```

   Verify that SHA against the old release evidence. Never use an unverified
   branch name for a rollback.
3. Re-run the installer with that immutable commit (the safest route):

   ```bash
   bash /tmp/marcel-install.sh --non-interactive \
     --commit <PREVIOUS_COMMIT_SHA> --force-commit
   ```

   If an operator must recover a checkout manually (this is not the automated
   qualification path):

   ```bash
   git -C "$HOME/.marcel/marcel-agent" checkout --detach <PREVIOUS_COMMIT_SHA>
   ```

   Then run the installer's dependency/bootstrap step for that checkout.
4. Confirm the rollback before restarting services:

   ```bash
   git -C "$HOME/.marcel/marcel-agent" rev-parse HEAD
   marcel --version
   ```

5. Restore the backed-up Marcel home only if a migration needs to be undone.
   Do not restore a newer database or configuration over an older schema
   without checking the release notes.

The qualification workflow records update and rollback evidence without
publishing anything. A rollback is successful only when the checkout lands on
the requested immutable commit and the installed CLI can run afterward.