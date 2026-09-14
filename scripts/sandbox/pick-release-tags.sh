#!/usr/bin/env bash
# Pick the release tags the install/update E2E should update FROM.
#
# Emits a JSON array of tag names on stdout, suitable for a GitHub Actions
# matrix (`fromJSON`). Choosing at runtime rather than hardcoding keeps the
# matrix honest as releases land: a pinned list silently stops covering the
# newest release the day after it ships, and pins the "oldest" forever even
# after it stops being a version anyone still runs.
#
# Selection: the newest tag, the oldest tag, and evenly spaced tags in between.
# Newest catches "did the last release break updating?", oldest is the longest
# upgrade jump anyone can still make, and the spread samples the migrations in
# between (config-schema bumps, venv layout changes, dependency floors).
#
# Usage:
#   scripts/sandbox/pick-release-tags.sh [--count N] [--repo DIR] [--exclude-tag TAG]
#
#   --count   how many tags to emit (default 5, minimum 1). Fewer tags than
#             requested emits all of them.
#   --repo    repository to read tags from (default: this checkout).
#   --exclude-tag
#             omit one release tag before sampling (for example, the tag that
#             triggered a release workflow).
#
# Reads tags from the local checkout, so it needs one fetched with tags
# (actions/checkout with fetch-depth: 0, or `fetch-tags: true`). A shallow
# checkout has no tags and this exits non-zero rather than silently emitting an
# empty matrix.
#
# Only SemVer vMAJOR.MINOR.PATCH[.N][-prerelease] release tags are considered;
# the repo also carries backup/* and one-off tags that are not releases.

set -euo pipefail

COUNT=5
EXCLUDE_TAG=""
# Default to the repository containing this script, resolved through its real
# path so a symlinked or copied script still reads the checkout it lives in
# rather than whatever repo the caller happens to be standing in.
REPO=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --count)
      [ "$#" -ge 2 ] || { echo 'error: --count needs a value' >&2; exit 1; }
      COUNT="$2"; shift 2 ;;
    --repo)
      [ "$#" -ge 2 ] || { echo 'error: --repo needs a value' >&2; exit 1; }
      REPO="$2"; shift 2 ;;
    --exclude-tag)
      [ "$#" -ge 2 ] || { echo 'error: --exclude-tag needs a value' >&2; exit 1; }
      EXCLUDE_TAG="$2"; shift 2 ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "error: unknown argument: $1" >&2; exit 1 ;;
  esac
done
case "$COUNT" in
  ''|*[!0-9]*) echo "error: --count must be a positive integer: $COUNT" >&2; exit 1 ;;
esac
[ "$COUNT" -ge 1 ] || { echo 'error: --count must be at least 1' >&2; exit 1; }

# Resolve the script's own location through symlinks, then ask git which
# worktree that path belongs to. Deriving the repo from the script rather than
# from $PWD means a copied script cannot silently report a different checkout's
# tags, and --show-toplevel keeps it correct when invoked from a subdirectory.
if [ -z "$REPO" ]; then
  script_path="${BASH_SOURCE[0]}"
  if command -v readlink >/dev/null 2>&1; then
    script_path="$(readlink -f "$script_path" 2>/dev/null || printf '%s' "$script_path")"
  fi
  script_dir="$(cd "$(dirname "$script_path")" && pwd)"
  REPO="$(git -C "$script_dir" rev-parse --show-toplevel 2>/dev/null || printf '%s' "$script_dir")"
fi

# Sort with SemVer precedence rather than sort -V.  The fourth numeric
# component is retained for the historical CalVer-style tags; prereleases sort
# before their final release, and numeric prerelease identifiers sort before
# non-numeric identifiers.
mapfile -t tags < <(
  git -C "$REPO" tag --list 'v*' |
    { if [ -n "$EXCLUDE_TAG" ]; then grep -Fvx -- "$EXCLUDE_TAG" || true; else cat; fi; } |
    python3 -c '
import re
import sys

pattern = re.compile(
    r"^v([0-9]+)\.([0-9]+)\.([0-9]+)(?:\.([0-9]+))?"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)

def key(tag):
    match = pattern.fullmatch(tag)
    if not match:
        return None
    major, minor, patch, fourth, prerelease = match.groups()
    core = (int(major), int(minor), int(patch), int(fourth or 0))
    if prerelease is None:
        return core + (1, ())
    identifiers = []
    for identifier in prerelease.split("."):
        if identifier.isdigit():
            identifiers.append((0, int(identifier)))
        else:
            identifiers.append((1, identifier))
    return core + (0, tuple(identifiers))

tags = [(key(tag), tag) for tag in sys.stdin.read().splitlines()]
tags = [(sort_key, tag) for sort_key, tag in tags if sort_key is not None]
print("\n".join(
    tag for sort_key, tag in sorted(tags, key=lambda item: (item[0], item[1]))
))
'
)
if [ "${#tags[@]}" -eq 1 ] && [ -z "${tags[0]}" ]; then
  tags=()
fi

total="${#tags[@]}"
if [ "$total" -eq 0 ]; then
  if [ -n "$EXCLUDE_TAG" ]; then
    printf '[]\n'
    exit 0
  fi
  echo "error: no release tags found in $REPO" >&2
  echo '       A shallow clone has no tags: fetch with tags (actions/checkout' >&2
  echo '       with fetch-depth: 0, or fetch-tags: true).' >&2
  exit 1
fi

if [ "$total" -le "$COUNT" ]; then
  picked=("${tags[@]}")
elif [ "$COUNT" -eq 1 ]; then
  # One slot means the newest release; there is no span to spread across.
  picked=("${tags[$((total - 1))]}")
else
  # Evenly spaced indices across [0, total-1], endpoints included, so the
  # oldest and newest are always present and the rest are spread between them.
  picked=()
  for slot in $(seq 0 $((COUNT - 1))); do
    # Round to nearest rather than truncate, so the spacing does not bunch
    # toward the oldest end.
    index=$(( (slot * (total - 1) * 2 + (COUNT - 1)) / ((COUNT - 1) * 2) ))
    candidate="${tags[$index]}"
    # Guard against a duplicate if rounding lands twice on the same tag.
    case " ${picked[*]-} " in
      *" $candidate "*) continue ;;
    esac
    picked+=("$candidate")
  done
fi

printf '['
for i in "${!picked[@]}"; do
  [ "$i" -eq 0 ] || printf ','
  printf '"%s"' "${picked[$i]}"
done
printf ']\n'
