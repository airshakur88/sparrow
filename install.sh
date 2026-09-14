#!/bin/sh
set -eu

sparrow_ref="${SPARROW_REF:-main}"
sparrow_source="git+https://github.com/airshakur88/sparrow@${sparrow_ref}"

usage() {
    printf '%s\n' \
        'Install Sparrow with uv.' \
        'Usage: curl -fsSL https://raw.githubusercontent.com/airshakur88/sparrow/refs/heads/main/install.sh | sh'
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

"$uv_cmd" tool install --python 3.11 --force "$sparrow_source"
bin_dir=$($uv_cmd tool dir --bin)
PATH="$bin_dir:$PATH"
export PATH
if ! command -v sparrow >/dev/null 2>&1; then
    printf '%s\n' 'sparrow command was not found after installation.' >&2
    exit 1
fi
printf '%s\n' 'Sparrow installed from GitHub.'
sparrow --version
