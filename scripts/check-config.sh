#!/usr/bin/env bash
set -euo pipefail

fail() {
    echo "Mapper configuration check failed: $1" >&2
    exit 1
}

env_file="${MAPPER_ENV_FILE:-.env}"
[[ -f "$env_file" ]] || fail "missing $env_file (copy .env.example to .env first)"

read_value() {
    local key="$1"
    awk -F= -v key="$key" '
        $0 ~ "^[[:space:]]*" key "[[:space:]]*=" {
            sub(/^[^=]*=/, "")
            sub(/\r$/, "")
            print
            exit
        }
    ' "$env_file"
}

data_dir="$(read_value MAPPER_DATA_DIR)"
nodeodm_token="$(read_value NODEODM_TOKEN)"
internal_token="$(read_value MAPPER_INTERNAL_TOKEN)"
mapper_uid="$(read_value MAPPER_UID)"
mapper_gid="$(read_value MAPPER_GID)"
cookie_secure="$(read_value MAPPER_COOKIE_SECURE)"
session_hours="$(read_value MAPPER_SESSION_HOURS)"
disk_reserve_bytes="$(read_value MAPPER_DISK_RESERVE_BYTES)"
mapper_uid="${mapper_uid:-1000}"
mapper_gid="${mapper_gid:-1000}"
cookie_secure="${cookie_secure:-true}"
session_hours="${session_hours:-24}"
disk_reserve_bytes="${disk_reserve_bytes:-5368709120}"

[[ "$data_dir" == /* ]] || fail "MAPPER_DATA_DIR must be an absolute host path"
[[ "$data_dir" != "/" ]] || fail "MAPPER_DATA_DIR cannot be the filesystem root"
[[ "$data_dir" != *$'\n'* ]] || fail "MAPPER_DATA_DIR contains an invalid newline"

for token_name in NODEODM_TOKEN MAPPER_INTERNAL_TOKEN; do
    token="$(read_value "$token_name")"
    [[ ${#token} -ge 32 ]] || fail "$token_name must contain at least 32 characters"
    [[ "$token" != replace-with-* ]] || fail "$token_name still contains the example placeholder"
done
[[ "$nodeodm_token" != "$internal_token" ]] || fail "the two service tokens must be different"

[[ "$mapper_uid" =~ ^[0-9]+$ ]] || fail "MAPPER_UID must be numeric (run: id -u)"
[[ "$mapper_gid" =~ ^[0-9]+$ ]] || fail "MAPPER_GID must be numeric (run: id -g)"
(( mapper_uid >= 1 && mapper_uid <= 60000 )) \
    || fail "MAPPER_UID must be between 1 and 60000 (containers may not run as root)"
(( mapper_gid >= 1 && mapper_gid <= 60000 )) \
    || fail "MAPPER_GID must be between 1 and 60000 (containers may not run as root)"
[[ "$cookie_secure" == "true" || "$cookie_secure" == "false" ]] \
    || fail "MAPPER_COOKIE_SECURE must be true or false"
[[ "$session_hours" =~ ^[0-9]+$ ]] || fail "MAPPER_SESSION_HOURS must be a whole number"
(( session_hours >= 1 && session_hours <= 168 )) \
    || fail "MAPPER_SESSION_HOURS must be between 1 and 168"
[[ "$disk_reserve_bytes" =~ ^[0-9]+$ ]] \
    || fail "MAPPER_DISK_RESERVE_BYTES must be a whole number of bytes"
(( disk_reserve_bytes >= 1073741824 )) \
    || fail "MAPPER_DISK_RESERVE_BYTES must reserve at least 1 GiB"

echo "Mapper configuration check passed."
