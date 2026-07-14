#!/usr/bin/env bash
# Daily Hermes home backup: mirror -> commit -> push.
# Invoked by cron. Self-contained; reuses token from ~/.secrets.
# Stays SILENT on "nothing to commit"; prints a line only on real change or error.
set -euo pipefail

HERMES_HOME="/opt/data"
MIRROR="$HERMES_HOME/code/hermes-mirror"
TOKEN_FILE="$HERMES_HOME/.secrets/hermes-mirror.token"
REPO="github.com/ndominguez-cell/hermes-mirror.git"
USER_NAME="ndominguez-cell"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }
fail() { echo "BACKUP FAILED: $*" >&2; exit 1; }

[ -f "$TOKEN_FILE" ] || fail "token file missing: $TOKEN_FILE"
GIT_TOKEN="$(tr -d '\r\n' < "$TOKEN_FILE")"
[ -n "$GIT_TOKEN" ] || fail "token file empty"

# 1) Rebuild the mirror (copies, redacts, credential-scans). Exit 2 = leak found.
set +e
SCAN_OUT="$(python3 "$HERMES_HOME/scripts/hermes_mirror_backup.py" 2>&1)"
SCAN_RC=$?
set -e
if [ "$SCAN_RC" -eq 2 ]; then
  echo "BACKUP ABORTED: credential detected in a file slated for push. Nothing pushed."
  echo "$SCAN_OUT" | grep '^leak=' || true
  exit 2
elif [ "$SCAN_RC" -ne 0 ]; then
  fail "mirror script error (rc=$SCAN_RC): $SCAN_OUT"
fi

cd "$MIRROR" || fail "mirror dir missing: $MIRROR"

# 2) Commit only if something changed.
git add -A
if git diff --cached --quiet; then
  # Nothing changed — stay silent (watchdog pattern).
  exit 0
fi

STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
git -c user.name="$USER_NAME" \
    -c user.email="${USER_NAME}@users.noreply.github.com" \
    commit -q -m "Automated Hermes backup $STAMP"

# 3) Push using an ephemeral in-memory credential helper (token never on disk in repo).
git -c credential.helper='!f() { echo "username='"$USER_NAME"'"; echo "password='"$GIT_TOKEN"'"; }; f' \
    push -q origin main 2>&1 | sed -E 's/[A-Za-z0-9_]{20,}/[hidden]/g' || fail "git push failed"

CHANGED=$(git show --stat --oneline HEAD | tail -1)
echo "Hermes backup pushed $STAMP — $(git rev-parse --short HEAD)"
