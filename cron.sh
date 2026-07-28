#!/usr/bin/env bash
# py-stremio cronjob installer — generates and installs the crontab
# entries that drive ``py-stremio-cron`` on a recurring schedule.
#
# Actions:
#   ./cron.sh install      # write the py-stremio cron entries
#   ./cron.sh uninstall    # remove only the py-stremio entries
#   ./cron.sh show         # print the current py-stremio entries
#   ./cron.sh dry-run      # print what would be installed
#   ./cron.sh run-now NAME # run a named job once (for testing)
#
# Re-running ``install`` is idempotent: existing py-stremio entries
# are replaced in place, the rest of the user's crontab is preserved.
set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────
PY_STREMIO_BIN="${PY_STREMIO_BIN:-}"
LOG_DIR="${PY_STREMIO_LOG_DIR:-$HOME/.local/share/py-stremio/logs}"
SPEED_PERCENT="${PY_STREMIO_CRON_SPEED:-50}"   # half of the user's pipe
INSTALL_ROOT="${PY_STREMIO_ROOT:-$HOME/.py-stremio}"
SOURCE_DIR="$(pwd)"
ACTION="install"

# ── Pretty output ────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
    C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'
    C_CYAN=$'\033[96m'; C_GREEN=$'\033[92m'
    C_YELLOW=$'\033[93m'; C_RED=$'\033[91m'
    C_DIM=$'\033[2m'
else
    C_RESET=""; C_BOLD=""; C_CYAN=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_DIM=""
fi
info() { printf '%s==>%s %s\n' "$C_CYAN" "$C_RESET" "$*"; }
ok()   { printf '%s  ✓%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '%s  !%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
err()  { printf '%s  ✗%s %s\n' "$C_RED"   "$C_RESET" "$*" >&2; }
hr()   { printf '%s%s%s\n' "$C_DIM" "$(printf '─%.0s' {1..72})" "$C_RESET"; }

usage() {
    sed -n '2,15p' "$0"
    exit 0
}

# ── Parse args ───────────────────────────────────────────────────────────
POSITIONAL=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        install|uninstall|show|dry-run) ACTION="$1"; shift ;;
        run-now) ACTION="run-now"; JOB_NAME="${2:-}"; shift 2 ;;
        --bin) PY_STREMIO_BIN="$2"; shift 2 ;;
        --root) INSTALL_ROOT="$2"; shift 2 ;;
        --logs) LOG_DIR="$2"; shift 2 ;;
        --speed) SPEED_PERCENT="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) err "unknown argument: $1"; usage ;;
    esac
done

# ── Detect the py-stremio-cron binary ───────────────────────────────────
# Priority:
#   1. Explicit --bin / PY_STREMIO_BIN env var
#   2. Venv at $INSTALL_ROOT/venv/bin/py-stremio-cron
#   3. Local venv next to this script (./venv/bin/py-stremio-cron)
#   4. Anywhere on PATH
detect_bin() {
    if [[ -n "$PY_STREMIO_BIN" && -x "$PY_STREMIO_BIN" ]]; then
        echo "$PY_STREMIO_BIN"
        return
    fi
    local candidates=(
        "$INSTALL_ROOT/venv/bin/py-stremio-cron"
        "$SOURCE_DIR/venv/bin/py-stremio-cron"
    )
    for c in "${candidates[@]}"; do
        if [[ -x "$c" ]]; then
            echo "$c"
            return
        fi
    done
    if command -v py-stremio-cron >/dev/null 2>&1; then
        command -v py-stremio-cron
        return
    fi
    return 1
}

PY_STREMIO_BIN="$(detect_bin || true)"
if [[ -z "$PY_STREMIO_BIN" ]]; then
    err "py-stremio-cron not found"
    err "  pass --bin /full/path/to/py-stremio-cron, or"
    err "  set PY_STREMIO_BIN, or"
    err "  run ./install.sh first (it puts the binary on PATH)"
    exit 1
fi
ok "using binary: $PY_STREMIO_BIN"

# ── Detect the ROOT_FOLDER override ─────────────────────────────────────
# On a network share the .env on the share has the original author's
# path.  If ``py-stremio --show-config`` reports a root that does not
# exist on this machine, we need ``--root`` on every cron invocation
# so the scanner looks in the right place.
ROOT_OVERRIDE=""
if [[ -x "$PY_STREMIO_BIN" ]]; then
    RESOLVED_ROOT="$("$PY_STREMIO_BIN" --show-config 2>/dev/null | awk -F'= ' '/ROOT_FOLDER/ {print $2; exit}')"
    if [[ -n "$RESOLVED_ROOT" && ! -d "$RESOLVED_ROOT" ]]; then
        warn "configured ROOT_FOLDER ($RESOLVED_ROOT) does not exist on this machine"
        warn "every cron job will be wrapped with --root PATH (you will be prompted)"
    fi
fi

# ── Schedule ─────────────────────────────────────────────────────────────
# Names are stable so uninstall / show can find them.  Every entry is
# tagged with the marker comment below so we can identify our lines
# inside the user's crontab without touching anything else.
#
# Format per job:  "NAME|SCHEDULE|SUBCOMMAND"
# The pipe separator avoids the ambiguity of splitting the schedule
# (which is itself space-separated) on a single space.
CRON_MARKER="# py-stremio-managed:"

declare -A JOBS=(
    [scan-light]='0 */3 * * *|--scan'
    [scan-full]='0 */6 * * *|--scan --metadata'
    [download]='30 */2 * * *|--download'
    [combined]='0 0,12 * * *|--update-and-download'
)

# ── Build a single crontab line ─────────────────────────────────────────
# Each crontab entry calls a thin wrapper (``cron-run.sh``) that
# owns all the environment setup (PATH, PY_STREMIO_ROOT, INTERNET_SPEED_LIMIT)
# and dispatches to the right ``py-stremio-cron`` subcommand.  This
# keeps the crontab lines short, readable, and easy to move: if the
# user ever relocates the project, they only have to update one
# wrapper path instead of every cron line.
build_cron_line() {
    local name="$1"
    local schedule="$2"
    local subcmd="$3"
    local log_file="$LOG_DIR/${name}.log"
    mkdir -p "$LOG_DIR"
    printf '%s %s [%s] %s %s >> %s 2>&1\n' \
        "$schedule" \
        "$CRON_MARKER" "$name" \
        "$WRAPPER_PATH" \
        "$name" \
        "$log_file"
}

emit_crontab() {
    for name in scan-light scan-full download combined; do
        local entry="${JOBS[$name]}"
        local schedule="${entry%%|*}"
        local subcmd="${entry#*|}"
        build_cron_line "$name" "$schedule" "$subcmd"
    done
}

# ── Wrapper script ─────────────────────────────────────────────────────
# The wrapper is the only place that hard-codes the venv path, the
# install root, and the speed cap.  Relocating the project is a
# one-line edit of the wrapper itself; the crontab never has to
# change.  ``cron-run.sh`` is also handy for running a job by hand
# from a shell (``./cron-run.sh download``) without remembering all
# the ``--key`` flags.
WRAPPER_PATH="$INSTALL_ROOT/cron-run.sh"
write_wrapper() {
    # The install root may not exist yet (e.g. the user only ran the
    # install.sh's ``--no-venv`` path, or they're pointing
    # ``PY_STREMIO_ROOT`` at a fresh directory on a new client).
    mkdir -p "$(dirname "$WRAPPER_PATH")"
    cat > "$WRAPPER_PATH" <<EOF
#!/usr/bin/env bash
# Auto-generated by cron.sh — do not edit by hand (re-run cron.sh
# install to refresh).  Owns all the per-job environment so the
# crontab stays free of long binary paths and per-invocation flags.
set -euo pipefail
export PATH="$VENV_BIN:\$PATH"
export PY_STREMIO_ROOT="${INSTALL_ROOT:-\$HOME/.py-stremio}"
export INTERNET_SPEED_LIMIT="$SPEED_PERCENT"

case "\${1:-}" in
    scan-light)  exec py-stremio-cron --scan ;;
    scan-full)   exec py-stremio-cron --scan --metadata ;;
    download)    exec py-stremio-cron --download ;;
    combined)    exec py-stremio-cron --update-and-download ;;
    *)
        echo "cron-run.sh: unknown job '\$1' (expected: scan-light, scan-full, download, combined)" >&2
        exit 1
        ;;
esac
EOF
    chmod +x "$WRAPPER_PATH"
}

# ── Filter the user's crontab ───────────────────────────────────────────
filter_crontab() {
    # Drop every line that belongs to py-stremio.  A line is ours if:
    #   - it starts with our marker comment (covers the header AND every entry), OR
    #   - it invokes our binary path (``py-stremio-cron``)
    # The rest of the user's crontab is preserved verbatim.
    crontab -l 2>/dev/null | grep -v -F -e "$CRON_MARKER" -e "$PY_STREMIO_BIN" || true
}

# ── Install ─────────────────────────────────────────────────────────────
do_install() {
    hr
    info "installing py-stremio cron entries"
    mkdir -p "$LOG_DIR"

    # Derive the venv's bin directory from the binary we detected.
    # Used by the wrapper to put the binary on PATH so the crontab
    # itself can just call ``py-stremio-cron`` by name.
    VENV_BIN="$(dirname "$PY_STREMIO_BIN")"

    if [[ "$ACTION" != "dry-run" ]]; then
        # Write (or refresh) the wrapper.  Re-running ``install``
        # overwrites the wrapper so a moved install is picked up
        # automatically the next time install is invoked.
        write_wrapper
        ok "wrapper: $WRAPPER_PATH"
    fi

    local tmp
    tmp="$(mktemp)"
    filter_crontab > "$tmp"
    {
        cat "$tmp"
        echo
        echo "${CRON_MARKER} ── scheduled jobs (managed by cron.sh) ──"
        echo "${CRON_MARKER} wrapper: $WRAPPER_PATH"
        emit_crontab
    } > "${tmp}.new"
    mv "${tmp}.new" "${tmp}"

    if [[ "$ACTION" == "dry-run" ]]; then
        hr
        info "dry-run — the following crontab would be installed"
        cat "$tmp"
        rm -f "$tmp"
        return
    fi

    crontab "$tmp"
    rm -f "$tmp"
    ok "crontab installed — logs at $LOG_DIR"
    hr
    info "installed entries"
    crontab -l | grep -F -e "$CRON_MARKER" || true
}

# ── Uninstall ───────────────────────────────────────────────────────────
do_uninstall() {
    hr
    info "removing py-stremio cron entries"
    local tmp
    tmp="$(mktemp)"
    filter_crontab > "$tmp"
    crontab "$tmp"
    rm -f "$tmp"
    ok "py-stremio entries removed (other crontab entries preserved)"

    # The wrapper is also ours — remove it so a re-install picks up a
    # fresh copy.  Skip silently if it's not ours (the user might
    # have created their own cron-run.sh).
    if [[ -f "$WRAPPER_PATH" ]] && head -3 "$WRAPPER_PATH" 2>/dev/null | grep -q "Auto-generated by cron.sh"; then
        rm -f "$WRAPPER_PATH"
        ok "wrapper removed: $WRAPPER_PATH"
    fi
}

# ── Show ────────────────────────────────────────────────────────────────
do_show() {
    crontab -l 2>/dev/null | grep -F -e "$CRON_MARKER" || {
        echo "(no py-stremio cron entries installed — run ./cron.sh install)"
    }
}

# ── Run now ─────────────────────────────────────────────────────────────
do_run_now() {
    local name="${JOB_NAME:-}"
    if [[ -z "$name" ]]; then
        err "usage: ./cron.sh run-now NAME"
        err "available names: ${!JOBS[*]}"
        exit 1
    fi
    if [[ -z "${JOBS[$name]:-}" ]]; then
        err "unknown job name: $name"
        err "available names: ${!JOBS[*]}"
        exit 1
    fi
    info "running $name once via wrapper"
    if [[ -x "$WRAPPER_PATH" ]]; then
        "$WRAPPER_PATH" "$name"
    else
        # Fallback for first-time testing before ``install`` has been
        # run — invoke the binary directly with the right flags.
        local spec="${JOBS[$name]}"
        local subcmd="${spec#* }"
        "$PY_STREMIO_BIN" --key INTERNET_SPEED_LIMIT="$SPEED_PERCENT" $subcmd
    fi
}

# ── Pre-flight summary ──────────────────────────────────────────────────
# Derive the wrapper location up front so it shows in the summary
# (and so do_install/do_uninstall can refer to it without re-deriving).
WRAPPER_PATH="$INSTALL_ROOT/cron-run.sh"
VENV_BIN="$(dirname "$PY_STREMIO_BIN")"

hr
info "py-stremio cron installer"
printf '  %s%-18s%s %s\n' "$C_BOLD" "binary"  "$C_RESET" "$PY_STREMIO_BIN"
printf '  %s%-18s%s %s\n' "$C_BOLD" "wrapper" "$C_RESET" "$WRAPPER_PATH"
printf '  %s%-18s%s %s\n' "$C_BOLD" "install root" "$C_RESET" "${INSTALL_ROOT:-(unset)}"
printf '  %s%-18s%s %s\n' "$C_BOLD" "log dir" "$C_RESET" "$LOG_DIR"
printf '  %s%-18s%s %s%%\n' "$C_BOLD" "speed cap" "$C_RESET" "$SPEED_PERCENT"
printf '  %s%-18s%s %s\n' "$C_BOLD" "action" "$C_RESET" "$ACTION"
hr

case "$ACTION" in
    install)   do_install ;;
    dry-run)   do_install ;;
    uninstall) do_uninstall ;;
    show)      do_show ;;
    run-now)   do_run_now ;;
    *) err "unknown action: $ACTION"; usage ;;
esac
