#!/usr/bin/env bash
# Assemble un paquet Linux a partir de l'executable Nuitka deja compile.
#   package.sh <deb|rpm> <physicalshortcut.dist> <dossier-sortie>
# Ne compile rien et ne demande pas root (dpkg-deb --root-owner-group, rpmbuild).
set -euo pipefail
KIND="$1"; DIST="$(cd "$2" && pwd)"; OUT="$(mkdir -p "$3" && cd "$3" && pwd)"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
VERSION="$(sed -n 's/^version *= *"\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -1)"
GLIBC="$(getconf GNU_LIBC_VERSION | awk '{print $2}')"   # version de la machine de build
WORK="$(mktemp -d "${TMPDIR:-/var/tmp}/hsc-pkg.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
STAGE="$WORK/stage"

mkdir -p "$STAGE/opt" "$STAGE/usr/bin" "$STAGE/usr/lib/systemd/user" "$STAGE/usr/share/applications" \
         "$STAGE/usr/share/pixmaps" "$STAGE/usr/share/doc/physicalshortcut"
cp -a "$DIST" "$STAGE/opt/physicalshortcut"
ln -s /opt/physicalshortcut/physicalshortcut-bin "$STAGE/usr/bin/physicalshortcut"
install -m 644 "$HERE/physicalshortcut.service" "$STAGE/usr/lib/systemd/user/"
install -m 644 "$HERE/physicalshortcut.desktop" "$STAGE/usr/share/applications/"
# icone du menu d'applications : toutes les tailles hicolor + pixmaps (repli)
for png in "$ROOT"/assets/icons/physicalshortcut-*.png; do
    size="$(basename "$png" .png)"; size="${size#physicalshortcut-}"
    install -Dm 644 "$png" "$STAGE/usr/share/icons/hicolor/${size}x${size}/apps/physicalshortcut.png"
done
install -m 644 "$ROOT/assets/icon.png" "$STAGE/usr/share/pixmaps/physicalshortcut.png"
install -m 644 "$ROOT/README.md" "$ROOT/LICENSE" "$ROOT/CHANGELOG.md" "$STAGE/usr/share/doc/physicalshortcut/"

case "$KIND" in
deb)
    DEB="$WORK/deb"; mkdir -p "$DEB/DEBIAN"; cp -a "$STAGE/." "$DEB/"
    cat > "$DEB/DEBIAN/control" <<CTRL
Package: physicalshortcut
Version: $VERSION
Section: utils
Priority: optional
Architecture: amd64
Installed-Size: $(du -sk "$STAGE" | cut -f1)
Maintainer: yolezz <noreply@invalid>
Depends: libc6 (>= $GLIBC), libgl1, libglib2.0-0, libx11-6, libxrandr2, wmctrl
Recommends: playerctl, xclip | xsel | wl-clipboard, libnotify-bin, pulseaudio-utils, xdotool
Suggests: brightnessctl, ydotool
Homepage: https://github.com/yo-le-zz/PhysicalShortCut
Description: Gestes de la main vers actions (webcam, MediaPipe)
 PhysicalShortCut detecte des gestes de la main via la webcam et declenche des
 actions : lancer une application, deplacer une fenetre, ouvrir une URL,
 envoyer un raccourci clavier, piloter le volume, etc. Executable natif
 (compile avec Nuitka). Interface : http://127.0.0.1:5678
CTRL
    install -m 755 "$HERE/postinst" "$HERE/prerm" "$HERE/postrm" "$DEB/DEBIAN/"
    dpkg-deb --root-owner-group -Zxz -z6 --build "$DEB" "$OUT/physicalshortcut_${VERSION}_amd64.deb" >/dev/null
    echo "    $OUT/physicalshortcut_${VERSION}_amd64.deb"
    ;;
rpm)
    rpmbuild -bb "$HERE/physicalshortcut.spec" --define "_topdir $WORK/rpmbuild" --define "stage $STAGE" \
        --define "hsc_version $VERSION" --define "hsc_glibc $GLIBC" --target x86_64 >"$WORK/rpmbuild.log" 2>&1 \
        || { tail -40 "$WORK/rpmbuild.log"; exit 1; }
    cp "$WORK"/rpmbuild/RPMS/x86_64/*.rpm "$OUT/"
    echo "    $OUT/physicalshortcut-${VERSION}-1.x86_64.rpm"
    ;;
*) echo "usage: $0 <deb|rpm> <dist> <out>" >&2; exit 2 ;;
esac
