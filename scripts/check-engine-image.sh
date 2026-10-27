#!/usr/bin/env bash
# Check whether a newer build exists for each image pinned by digest in this
# repo's compose files (e.g. eugr/spark-vllm-b12x@sha256:…), by comparing the
# pinned digest with the digest behind the image's tracked tag (default
# "latest"). Read-only: never pulls, never edits compose files.
#
# Run by the systemd user timer engine-image-check.timer (~3 min after boot,
# then daily). A newer build writes a notice that every interactive shell
# prints (see the block in ~/.bashrc) until it is dismissed or the pin is
# updated.
#
# Usage:
#   ./scripts/check-engine-image.sh            # check now (what the timer runs)
#   ./scripts/check-engine-image.sh show       # print the current notice, if any
#   ./scripts/check-engine-image.sh dismiss    # silence the notice for the digests shown
#
# Env: TRACK_TAG (default: latest)
set -uo pipefail
cd "$(dirname "$0")/.."

TRACK_TAG="${TRACK_TAG:-latest}"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/engine-image-check"
NOTICE="$STATE_DIR/notice"
DISMISSED="$STATE_DIR/dismissed"     # lines: <repo> <remote digest>
LOG="$STATE_DIR/check.log"
mkdir -p "$STATE_DIR"
touch "$DISMISSED"

log() { echo "$(date -u +%FT%TZ) $*" >> "$LOG"; }

case "${1:-check}" in
    show)
        [[ -s "$NOTICE" ]] && grep -v '^#> ' "$NOTICE" || echo "No new engine image."
        exit 0 ;;
    dismiss)
        if [[ -s "$NOTICE" ]]; then
            grep -oE '^#> [^ ]+ [0-9a-f]{64}$' "$NOTICE" | cut -c4- >> "$DISMISSED"
            rm -f "$NOTICE"
            echo "Dismissed. You'll be told again only when an even newer build appears."
        else
            echo "Nothing to dismiss."
        fi
        exit 0 ;;
    check) ;;
    *) echo "usage: $0 [check|show|dismiss]" >&2; exit 2 ;;
esac

# Every image pinned by digest in any compose file, deduplicated: "<repo> <digest> <file>".
# Lines carrying "check-engine-image: skip" are frozen on purpose (e.g. the rollback
# stacks' vllm/vllm-openai nightly, whose :latest is the stable release, not a newer nightly).
mapfile -t pins < <(grep -HE '^\s*image:\s*[^ #]+@sha256:[0-9a-f]{64}' docker-compose*.yml 2>/dev/null \
    | grep -v 'check-engine-image: skip' \
    | sed -E 's/^([^:]+):\s*image:\s*([^@ ]+)@sha256:([0-9a-f]{64}).*$/\2 \3 \1/' | sort -u -k1,2)

if [[ ${#pins[@]} -eq 0 ]]; then
    log "no digest-pinned images found"; rm -f "$NOTICE"; exit 0
fi

body=""
for line in "${pins[@]}"; do
    read -r repo pinned file <<< "$line"
    if ! remote=$(docker buildx imagetools inspect "$repo:$TRACK_TAG" 2>/dev/null \
                  | awk '/^Digest:/{sub("sha256:","",$2); print $2; exit}') || [[ -z "$remote" ]]; then
        log "$repo:$TRACK_TAG lookup failed (network/registry?); keeping previous notice"
        exit 0
    fi
    if [[ "$remote" == "$pinned" ]]; then
        log "$repo up to date (${pinned:0:12}) [$file]"
        continue
    fi
    if grep -qxF "$repo $remote" "$DISMISSED"; then
        log "$repo:$TRACK_TAG ${remote:0:12} differs from pin ${pinned:0:12} but was dismissed"
        continue
    fi
    created=$(docker buildx imagetools inspect --format '{{json .Image}}' "$repo:$TRACK_TAG" 2>/dev/null \
              | python3 -I -c 'import json,sys; print(json.load(sys.stdin).get("created","?")[:10])' 2>/dev/null || echo "?")
    log "NEW: $repo:$TRACK_TAG ${remote:0:12} (built $created) vs pinned ${pinned:0:12} [$file]"
    body+="  $repo:$TRACK_TAG → ${remote:0:12} (built $created); pinned ${pinned:0:12} in $file"$'\n'
    body+="#> $repo $remote"$'\n'
done

if [[ -n "$body" ]]; then
    {
        echo "⚠ New engine image build available (checked $(date -u '+%F %H:%M') UTC):"
        printf '%s' "$body" | grep -v '^#> '
        echo "  To adopt: put the new digest in that compose file (and CLAUDE.md's image table), then"
        echo "  ./scripts/flash-next-compose.sh up -d  — expect a slower first boot (compile caches rebuild)."
        echo "  To silence this build: $PWD/scripts/check-engine-image.sh dismiss"
        printf '%s' "$body" | grep '^#> '
    } > "$NOTICE"
else
    rm -f "$NOTICE"
fi
