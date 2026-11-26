#!/usr/bin/env bash
# Construit les paquets de PhysicalShortCut : compile l'executable natif (Nuitka) puis
# le package. Detecte le systeme, les outils disponibles et se relance en sudo.
#
#   ./build.sh                 auto : tous les formats possibles sur cette machine
#   ./build.sh --deb | --rpm   limite aux formats demandes (cumulables)
#   ./build.sh --docker        compile dans Ubuntu 22.04 (binaire compatible partout)
#   ./build.sh --list          affiche ce qui est possible, sans construire
#   ./build.sh --no-install    n'installe aucun outil manquant
#   ./build.sh --jobs N        parallelisme de la compilation
#
# Resultat dans dist/. Windows : voir packaging/windows/build.ps1 (a lancer sous Windows).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

WANT=(); LIST=0; INSTALL=1; DOCKER=0; JOBS="$(nproc 2>/dev/null || echo 2)"
while [ $# -gt 0 ]; do
    case "$1" in
        --deb) WANT+=(deb) ;; --rpm) WANT+=(rpm) ;;
        --list) LIST=1 ;; --no-install) INSTALL=0 ;; --docker) DOCKER=1 ;;
        --jobs) JOBS="$2"; shift ;;
        -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Option inconnue : $1 (voir --help)" >&2; exit 2 ;;
    esac
    shift
done

# --- 1. Droits root : relance automatique via sudo (PATH conserve pour retrouver uv) ---
if [ "$(id -u)" -ne 0 ] && [ "$LIST" -eq 0 ]; then
    echo "==> Droits root requis (installation des outils manquants) : relance avec sudo"
    exec sudo -E env "PATH=$PATH" "$ROOT/build.sh" "$@"
fi
REAL_USER="${SUDO_USER:-root}"

# --- 2. Detection du systeme et du gestionnaire de paquets ---
. /etc/os-release 2>/dev/null || true
FAMILY="${ID:-unknown} ${ID_LIKE:-}"
PM=""
case " $FAMILY " in
    *" debian "*|*" ubuntu "*) PM=apt ;;
    *" fedora "*|*" rhel "*|*" centos "*) PM=dnf ;;
    *" suse "*|*" opensuse"*) PM=zypper ;;
    *" arch "*) PM=pacman ;;
esac
ARCH="$(uname -m)"
echo "==> Systeme : ${PRETTY_NAME:-inconnu} ($ARCH), gestionnaire : ${PM:-aucun}, glibc $(getconf GNU_LIBC_VERSION | awk '{print $2}')"
[ "$ARCH" = x86_64 ] || echo "    Attention : les paquets sont declares x86_64 (architecture detectee : $ARCH)."

# Nom du paquet fournissant chaque outil, selon le gestionnaire.
pkg_for() { # outil -> paquet
    case "$PM:$1" in
        apt:gcc) echo build-essential;;   dnf:gcc) echo "gcc gcc-c++";;
        zypper:gcc) echo "gcc gcc-c++";;  pacman:gcc) echo base-devel;;
        apt:patchelf|dnf:patchelf|zypper:patchelf|pacman:patchelf) echo patchelf;;
        apt:ccache|dnf:ccache|zypper:ccache|pacman:ccache) echo ccache;;
        apt:dpkg-deb) echo dpkg-dev;;     dnf:dpkg-deb) echo dpkg;;
        zypper:dpkg-deb) echo dpkg;;      pacman:dpkg-deb) echo dpkg;;
        apt:rpmbuild) echo rpm;;          dnf:rpmbuild) echo rpm-build;;
        zypper:rpmbuild) echo rpm-build;; pacman:rpmbuild) echo rpm-tools;;
        *) echo "";;
    esac
}
install_pkgs() {
    case "$PM" in
        apt) apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "$@";;
        dnf) dnf install -y "$@";;
        zypper) zypper --non-interactive install "$@";;
        pacman) pacman -S --noconfirm --needed "$@";;
        *) return 1;;
    esac
}
have() { command -v "$1" >/dev/null 2>&1; }
can_get() { [ "$INSTALL" -eq 1 ] && [ -n "$PM" ] && [ -n "$(pkg_for "$1")" ]; }

# --- 3. Capacites : quels formats peut-on produire ici ? ---
status() { if have "$1"; then echo "present"; elif can_get "$1"; then echo "installable ($(pkg_for "$1"))"; else echo "ABSENT"; fi; }
echo "==> Outils :"
for t in uv gcc patchelf dpkg-deb rpmbuild; do printf '    %-10s %s\n' "$t" "$(status "$t")"; done

AVAILABLE=()
for fmt in deb rpm; do
    tool=$([ $fmt = deb ] && echo dpkg-deb || echo rpmbuild)
    if have "$tool" || can_get "$tool"; then AVAILABLE+=("$fmt"); fi
done
echo "==> Formats possibles ici : ${AVAILABLE[*]:-aucun}   |   Windows (.exe) : seulement sous Windows (packaging/windows/build.ps1)"

if [ ${#WANT[@]} -eq 0 ]; then TARGETS=("${AVAILABLE[@]}"); else
    TARGETS=()
    for fmt in "${WANT[@]}"; do
        if printf '%s\n' "${AVAILABLE[@]:-}" | grep -qx "$fmt"; then TARGETS+=("$fmt")
        else echo "Erreur : le format $fmt n'est pas realisable ici (outil absent, --no-install ?)." >&2; exit 1; fi
    done
fi
[ "$LIST" -eq 1 ] && { echo "==> A construire : ${TARGETS[*]:-rien}"; exit 0; }
[ ${#TARGETS[@]} -gt 0 ] || { echo "Erreur : aucun format de paquet realisable sur ce systeme." >&2; exit 1; }

# --- 4. Mode Docker : tout se fait dans un conteneur Ubuntu 22.04 ---
if [ "$DOCKER" -eq 1 ]; then
    ENGINE="$(command -v docker || command -v podman)" || { echo "docker/podman introuvable" >&2; exit 1; }
    mkdir -p dist
    "$ENGINE" build -t physicalshortcut-build -f packaging/linux/Dockerfile packaging/linux
    ARGS=(); for f in "${TARGETS[@]}"; do ARGS+=("--$f"); done
    # :Z = etiquette SELinux (Fedora/RHEL)
    "$ENGINE" run --rm -v "$ROOT:/src:Z" -e HOST_UID="$(id -u "$REAL_USER")" -e HOST_GID="$(id -g "$REAL_USER")" \
        -e JOBS="$JOBS" -e ARGS="${ARGS[*]}" physicalshortcut-build bash -euc '
            mkdir /tmp/work
            tar -C /src --exclude=.venv --exclude=node_modules --exclude=dist --exclude=build --exclude=.git -cf - . | tar -C /tmp/work -xf -
            cd /tmp/work && ./build.sh $ARGS --jobs "$JOBS"
            cp dist/* /src/dist/ && chown "$HOST_UID:$HOST_GID" /src/dist/*'
    echo "==> Paquets dans $ROOT/dist"; exit 0
fi

# --- 5. Installation des outils manquants ---
MISSING=()
have gcc || have cc || MISSING+=("$(pkg_for gcc)")
have patchelf || MISSING+=("$(pkg_for patchelf)")
have ccache || [ -z "$(pkg_for ccache)" ] || MISSING+=("$(pkg_for ccache)")  # accelere les recompilations
for fmt in "${TARGETS[@]}"; do
    tool=$([ $fmt = deb ] && echo dpkg-deb || echo rpmbuild); have "$tool" || MISSING+=("$(pkg_for "$tool")")
done
if [ ${#MISSING[@]} -gt 0 ]; then
    [ "$INSTALL" -eq 1 ] && [ -n "$PM" ] || { echo "Erreur : outils manquants (${MISSING[*]}) et installation impossible." >&2; exit 1; }
    echo "==> Installation : ${MISSING[*]}"
    install_pkgs ${MISSING[*]}
fi
if ! have uv; then
    for c in "${UV_BIN:-}" "$(getent passwd "$REAL_USER" | cut -d: -f6)/.local/bin/uv" /usr/local/bin/uv; do
        [ -x "$c" ] && { PATH="$(dirname "$c"):$PATH"; break; }
    done
fi
have uv || { echo "Erreur : uv introuvable. Installe-le : https://docs.astral.sh/uv/getting-started/installation/" >&2; exit 1; }

# --- 6. Compilation de l'executable natif ---
export UV_PYTHON_PREFERENCE=managed
echo "==> Compilation de l'executable (Nuitka)"
uv sync --frozen --group build --python 3.12
uv run --frozen --group build python packaging/build_exe.py --jobs "$JOBS"
DIST="$ROOT/build/exe/physicalshortcut.dist"
"$DIST/physicalshortcut-bin" --version

# --- 7. Packaging ---
mkdir -p dist
for fmt in "${TARGETS[@]}"; do
    echo "==> Paquet $fmt"
    packaging/linux/package.sh "$fmt" "$DIST" "$ROOT/dist"
done
chown -R "$REAL_USER:$(id -gn "$REAL_USER")" dist build .venv 2>/dev/null || true
echo "==> Termine :"; ls -lh dist
