#!/bin/sh
set -eu

usage() {
    printf '%s\n' \
        'Uninstall Sparrow installed with uv.' \
        'Usage: curl -fsSL https://raw.githubusercontent.com/airshakur88/sparrow/refs/heads/main/uninstall.sh | sh'
}

if [ "$#" -gt 0 ]; then
    case "$1" in
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
fi

if command -v uv >/dev/null 2>&1; then
    uv_cmd=uv
elif [ -x "$HOME/.local/bin/uv" ]; then
    uv_cmd="$HOME/.local/bin/uv"
else
    printf '%s\n' 'uv was not found. Sparrow may already be uninstalled.' >&2
    exit 1
fi

"$uv_cmd" tool uninstall sparrow
printf '%s\n' 'Sparrow uninstalled. User configuration and data were preserved.'
