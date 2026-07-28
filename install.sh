#!/usr/bin/env bash
# py-stremio installer — installs the source tree you already have on disk.
#
# Usage:
#   ./install.sh                     # install from the current dir (default)
#   ./install.sh --user              # install into ~/.py-stremio (default)
#   ./install.sh --system            # install into /opt/py-stremio (needs sudo)
#   ./install.sh --no-venv           # use the system Python (not recommended)
#   ./install.sh --with-cloudflare   # install tls_client + cloudscraper too
#   ./install.sh --uninstall         # undo a previous install
#
# Bring the source to the target machine however you like (clone, scp,
# USB stick, tarball, whatever) and then run this script from inside the
# checkout.  The script does NOT pull code from anywhere — it installs
# whatever is in the current directory.
#
# Re-running is safe — the script is idempotent.  An existing venv is
# reused unless --recreate-venv is passed.
set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────
INSTALL_MODE="user"
USE_VENV=1
INSTALL_CLOUDFLARE=0
ACTION="install"
RECREATE_VENV=0
SOURCE_DIR="$(pwd)"

# ── Pretty output ────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
    C_RESET=$'\033[0m'
    C_BOLD=$'\033[1m'
    C_CYAN=$'\033[96m'
    C_GREEN=$'\033[92m'
    C_YELLOW=$'\033[93m'
    C_RED=$'\033[91m'
    C_DIM=$'\033[2m'
else
    C_RESET=""; C_BOLD=""; C_CYAN=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_DIM=""
fi

info()  { printf '%s==>%s %s\n' "$C_CYAN" "$C_RESET" "$*"; }
ok()    { printf '%s  ✓%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn()  { printf '%s  !%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
err()   { printf '%s  ✗%s %s\n' "$C_RED"   "$C_RESET" "$*" >&2; }
hr()    { printf '%s%s%s\n' "$C_DIM" "$(printf '─%.0s' {1..64})" "$C_RESET"; }

require_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        err "required command not found: $1"
        return 1
    fi
}

usage() {
    sed -n '2,17p' "$0"
    exit 0
}

# ── Parse args ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --user)            INSTALL_MODE="user"; shift ;;
        --system)          INSTALL_MODE="system"; shift ;;
        --no-venv)         USE_VENV=0; shift ;;
        --with-cloudflare) INSTALL_CLOUDFLARE=1; shift ;;
        --uninstall)       ACTION="uninstall"; shift ;;
        --recreate-venv)   RECREATE_VENV=1; shift ;;
        -h|--help)         usage ;;
        *) err "unknown argument: $1"; usage ;;
    esac
done

# ── Paths ────────────────────────────────────────────────────────────────
if [[ "$INSTALL_MODE" == "system" ]]; then
    INSTALL_ROOT="${PY_STREMIO_ROOT:-/opt/py-stremio}"
    BIN_DIR="${PY_STREMIO_BIN:-/usr/local/bin}"
    NEED_SUDO=1
else
    INSTALL_ROOT="${PY_STREMIO_ROOT:-$HOME/.py-stremio}"
    BIN_DIR="${PY_STREMIO_BIN:-$HOME/.local/bin}"
    NEED_SUDO=0
fi

SUDO=""
if [[ "$NEED_SUDO" -eq 1 ]] && [[ $EUID -ne 0 ]]; then
    SUDO="sudo"
fi

# ── Pick a Python interpreter ────────────────────────────────────────────
pick_python() {
    local candidates=(python3.12 python3.11 python3.10 python3)
    for c in "${candidates[@]}"; do
        if command -v "$c" >/dev/null 2>&1; then
            local ver
            ver="$("$c" -c 'import sys; print("%d.%d"%sys.version_info[:2])')"
            if [[ "$(printf '%s\n' "3.10" "$ver" | sort -V | head -1)" == "3.10" ]]; then
                echo "$c"
                return 0
            fi
        fi
    done
    return 1
}

PYTHON_BIN="$(pick_python || true)"
if [[ -z "$PYTHON_BIN" ]]; then
    err "no Python 3.10+ interpreter found on PATH"
    err "install one (e.g. 'sudo apt install python3.11' or 'brew install python@3.12') and re-run"
    exit 1
fi
PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print("%d.%d"%sys.version_info[:2])')"
ok "using ${PYTHON_BIN} (${PY_VERSION})"

# ── Detect distro for OS-specific hints ──────────────────────────────────
detect_pkg_manager() {
    if   command -v apt-get >/dev/null 2>&1; then echo "apt"
    elif command -v dnf     >/dev/null 2>&1; then echo "dnf"
    elif command -v yum     >/dev/null 2>&1; then echo "yum"
    elif command -v pacman  >/dev/null 2>&1; then echo "pacman"
    elif command -v apk     >/dev/null 2>&1; then echo "apk"
    elif command -v brew    >/dev/null 2>&1; then echo "brew"
    else echo "unknown"
    fi
}
PKG_MGR="$(detect_pkg_manager)"

suggest_install_python() {
    case "$PKG_MGR" in
        apt)    warn "try:  ${SUDO} apt install -y python3 python3-venv python3-pip" ;;
        dnf|yum) warn "try:  ${SUDO} $PKG_MGR install -y python3 python3-venv python3-pip" ;;
        pacman) warn "try:  ${SUDO} pacman -S --needed python python-pip" ;;
        apk)    warn "try:  ${SUDO} apk add python3 py3-pip py3-venv" ;;
        brew)   warn "try:  brew install python" ;;
        *)      warn "install Python 3.10+ manually, then re-run" ;;
    esac
}

# ── Uninstall path ──────────────────────────────────────────────────────
if [[ "$ACTION" == "uninstall" ]]; then
    hr
    info "uninstalling py-stremio from ${INSTALL_ROOT}"
    if [[ -d "$INSTALL_ROOT" ]]; then
        $SUDO rm -rf "$INSTALL_ROOT"
        ok "removed ${INSTALL_ROOT}"
    else
        warn "${INSTALL_ROOT} does not exist — nothing to remove"
    fi
    for bin in py-stremio py-stremio-cron; do
        if [[ -e "$BIN_DIR/$bin" ]]; then
            $SUDO rm -f "$BIN_DIR/$bin"
            ok "removed ${BIN_DIR}/${bin}"
        fi
    done
    info "done — re-run ${0##*/} without --uninstall to reinstall"
    exit 0
fi

# ── Verify the source on disk ───────────────────────────────────────────
hr
if [[ ! -f "$SOURCE_DIR/pyproject.toml" ]]; then
    err "no pyproject.toml in $SOURCE_DIR"
    err "run this script from inside the py-stremio checkout"
    err "(cd /path/to/py-stremio && ./install.sh)"
    exit 1
fi
if ! grep -q '^name = "py-stremio"' "$SOURCE_DIR/pyproject.toml" 2>/dev/null; then
    err "pyproject.toml in $SOURCE_DIR does not name 'py-stremio'"
    err "are you sure this is the right directory?"
    exit 1
fi
ok "source: ${SOURCE_DIR}"

# ── Install target summary ──────────────────────────────────────────────
hr
info "install target"
printf '  %s%-12s%s %s\n' "$C_BOLD" "prefix"     "$C_RESET" "$INSTALL_ROOT"
printf '  %s%-12s%s %s\n' "$C_BOLD" "bin dir"    "$C_RESET" "$BIN_DIR"
printf '  %s%-12s%s %s\n' "$C_BOLD" "python"     "$C_RESET" "$PYTHON_BIN ($PY_VERSION)"
printf '  %s%-12s%s %s\n' "$C_BOLD" "pkg manager" "$C_RESET" "$PKG_MGR"
printf '  %s%-12s%s %s\n' "$C_BOLD" "venv"       "$C_RESET" "$([[ $USE_VENV -eq 1 ]] && echo yes || echo no)"
printf '  %s%-12s%s %s\n' "$C_BOLD" "cloudflare" "$C_RESET" "$([[ $INSTALL_CLOUDFLARE -eq 1 ]] && echo yes || echo no)"

# ── Sync source into the install prefix ─────────────────────────────────
hr
info "syncing source ${SOURCE_DIR} → ${INSTALL_ROOT}"
$SUDO mkdir -p "$INSTALL_ROOT"
if command -v rsync >/dev/null 2>&1; then
    $SUDO rsync -a --delete \
        --exclude='.git/' --exclude='__pycache__/' --exclude='*.pyc' \
        --exclude='venv/' --exclude='.env' --exclude='addons/addons.txt' \
        --exclude='addons/experimental.txt' --exclude='downloads/' \
        --exclude='*.part' --exclude='*.swp' --exclude='.pytest_cache/' \
        "$SOURCE_DIR/" "$INSTALL_ROOT/"
else
    $SUDO rm -rf "$INSTALL_ROOT"
    $SUDO mkdir -p "$INSTALL_ROOT"
    $SUDO tar -C "$SOURCE_DIR" \
        --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
        --exclude='venv' --exclude='.env' --exclude='addons/addons.txt' \
        --exclude='addons/experimental.txt' --exclude='downloads' \
        --exclude='*.part' --exclude='*.swp' --exclude='.pytest_cache' \
        -cf - . | $SUDO tar -C "$INSTALL_ROOT" -xf -
fi
ok "synced source into ${INSTALL_ROOT}"

# ── Create / refresh venv ───────────────────────────────────────────────
VENV_DIR="$INSTALL_ROOT/venv"
if [[ $USE_VENV -eq 1 ]]; then
    hr
    info "setting up venv at ${VENV_DIR}"
    if [[ $RECREATE_VENV -eq 1 && -d "$VENV_DIR" ]]; then
        $SUDO rm -rf "$VENV_DIR"
    fi
    if [[ ! -d "$VENV_DIR" ]]; then
        $SUDO "$PYTHON_BIN" -m venv "$VENV_DIR"
        ok "created venv"
    else
        ok "reusing existing venv"
    fi
    PIP="$VENV_DIR/bin/pip"
    PYTHON="$VENV_DIR/bin/python"
    $SUDO "$PIP" install --upgrade pip wheel >/dev/null
    ok "upgraded pip + wheel"
else
    warn "skipping venv — using system Python"
    PYTHON="$PYTHON_BIN"
    PIP="$PYTHON_BIN -m pip"
    warn "you may need to use 'pip install --user' or '${SUDO} pip install' below"
fi

# ── Check prerequisites ──────────────────────────────────────────────────
hr
info "checking prerequisites"

if ! "$PYTHON" -c 'import venv' >/dev/null 2>&1; then
    err "python venv module is missing"
    err "on Debian/Ubuntu install it with:  ${SUDO} apt install -y python3-venv"
    err "on Fedora/RHEL:                    ${SUDO} dnf install -y python3-virtualenv"
    suggest_install_python
    exit 1
fi
ok "python venv module is available"

# ── Install the package + runtime deps ──────────────────────────────────
hr
info "installing py-stremio + runtime dependencies"
$SUDO "$PIP" install --upgrade pip >/dev/null

# Editable install so re-syncing the source picks up code changes.
$SUDO "$PIP" install -e "$INSTALL_ROOT"
ok "installed py-stremio (editable) from ${INSTALL_ROOT}"

if [[ $INSTALL_CLOUDFLARE -eq 1 ]]; then
    info "installing optional Cloudflare bypass dependencies"
    $SUDO "$PIP" install "tls_client>=1.0.0" "cloudscraper>=1.2.71" || warn "cloudflare extras failed — continuing without them"
    ok "cloudflare dependencies installed"
else
    warn "skipping cloudflare extras — pass --with-cloudflare if any addons need it"
fi

# ── Ship a default .env if missing ──────────────────────────────────────
hr
if [[ ! -f "$INSTALL_ROOT/.env" && -f "$INSTALL_ROOT/.env.example" ]]; then
    info "creating default .env from .env.example"
    $SUDO cp "$INSTALL_ROOT/.env.example" "$INSTALL_ROOT/.env"
    $SUDO chmod 600 "$INSTALL_ROOT/.env"
    ok "wrote ${INSTALL_ROOT}/.env (fill in REAL_DEBRID_API_KEY to enable downloads)"
else
    ok ".env already present — leaving it alone"
fi

# ── Symlink the entry points ───────────────────────────────────────────
hr
info "linking entry points to ${BIN_DIR}"
$SUDO mkdir -p "$BIN_DIR"
for bin in py-stremio py-stremio-cron; do
    if [[ -e "$BIN_DIR/$bin" || -L "$BIN_DIR/$bin" ]]; then
        $SUDO rm -f "$BIN_DIR/$bin"
    fi
    $SUDO ln -s "$VENV_DIR/bin/$bin" "$BIN_DIR/$bin"
    ok "${BIN_DIR}/${bin} → ${VENV_DIR}/bin/${bin}"
done

# ── PATH nudge ──────────────────────────────────────────────────────────
if [[ ":$PATH:" != *":${BIN_DIR}:"* ]]; then
    warn "${BIN_DIR} is not on your PATH"
    case "$INSTALL_MODE" in
        user)
            SHELL_NAME="$(basename "${SHELL:-/bin/bash}")"
            case "$SHELL_NAME" in
                zsh)  RC="$HOME/.zshrc" ;;
                fish) RC="$HOME/.config/fish/config.fish" ;;
                *)    RC="$HOME/.bashrc" ;;
            esac
            printf '\n# py-stremio\nexport PATH="%s:$PATH"\n' "$BIN_DIR" \
                | $SUDO tee -a "$RC" >/dev/null
            ok "appended PATH export to ${RC} (run 'source ${RC}' or restart the shell)"
            ;;
        *)
            warn "add ${BIN_DIR} to PATH manually for the symlinks to work in new shells"
            ;;
    esac
else
    ok "${BIN_DIR} is already on PATH"
fi

# ── Smoke test ──────────────────────────────────────────────────────────
hr
info "running smoke test"
if "$PYTHON" -c "import py_stremio; print('  py_stremio', py_stremio.__name__)" 2>/dev/null; then
    ok "module imports cleanly"
else
    err "import smoke test failed — check $INSTALL_ROOT for details"
    exit 1
fi

if [[ -x "$BIN_DIR/py-stremio" ]]; then
    if "$BIN_DIR/py-stremio" --help >/dev/null 2>&1; then
        ok "py-stremio --help works"
    else
        warn "py-stremio --help returned a non-zero exit — the install is functional but check the binary"
    fi
fi

# ── Done ────────────────────────────────────────────────────────────────
hr
printf '%s%sInstallation complete!%s\n' "$C_BOLD" "$C_GREEN" "$C_RESET"
printf '  source:    %s\n' "$SOURCE_DIR"
printf '  installed: %s\n' "$INSTALL_ROOT"
printf '  bin:       %s\n' "$BIN_DIR/py-stremio"
printf '  cron bin:  %s\n' "$BIN_DIR/py-stremio-cron"
printf '  config:    %s/.env   %s<- edit to add REAL_DEBRID_API_KEY%s\n' \
    "$INSTALL_ROOT" "$C_YELLOW" "$C_RESET"
printf '\n  next step:  %spy-stremio --scan%s\n' "$C_BOLD" "$C_RESET"
hr
