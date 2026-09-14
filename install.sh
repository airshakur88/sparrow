#!/bin/sh
set -eu

usage() {
    printf '%s\n' \
        'Install Sparrow with uv.' \
        'Usage: curl -fsSL https://raw.githubusercontent.com/airshakur88/sparrow/main/install.sh | sh'
}

if [ "$#" -gt 0 ]; then
    case "$1" in
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
fi

if command -v uv >/dev/null 2>&1; then
    uv_cmd=uv
else
    if ! command -v curl >/dev/null 2>&1; then
        printf '%s\n' 'curl is required to install uv.' >&2
        exit 1
    fi
    curl --fail --silent --show-error --location https://astral.sh/uv/install.sh | sh
    uv_cmd="$HOME/.local/bin/uv"
fi

if [ ! -x "$uv_cmd" ]; then
    printf '%s\n' 'uv was not found after installation.' >&2
    exit 1
fi

"$uv_cmd" tool install --python 3.11 --force sparrow
printf '%s\n' 'Sparrow installed. Open a new shell if sparrow is not on PATH yet.'
"$uv_cmd" tool run --from sparrow sparrow --version
