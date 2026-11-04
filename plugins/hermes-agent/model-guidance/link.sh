#!/bin/sh
set -eu

HERMES_HOME_REAL="${HERMES_HOME:?set HERMES_HOME to the target profile home before linking}"
SRC_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
TARGET="$HERMES_HOME_REAL/plugins/model-guidance"

mkdir -p "$HERMES_HOME_REAL/plugins"

if [ -L "$TARGET" ]; then
    CURRENT=$(readlink -f "$TARGET" 2>/dev/null || true)
    if [ "$CURRENT" = "$SRC_DIR" ]; then
        printf '%s\n' "model-guidance link already points to $SRC_DIR"
        exit 0
    fi
    printf '%s\n' "refusing to replace existing symlink: $TARGET -> $CURRENT" >&2
    exit 1
fi

if [ -e "$TARGET" ]; then
    printf '%s\n' "refusing to replace existing file or directory: $TARGET" >&2
    printf '%s\n' "move it to a verified backup first, then rerun this script" >&2
    exit 1
fi

ln -s "$SRC_DIR" "$TARGET"
printf '%s\n' "linked $TARGET -> $SRC_DIR"
