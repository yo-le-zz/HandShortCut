# Paquet "binaire" : l'executable Nuitka (dossier /opt/handshortcut) est pre-compile
# par build.sh et fourni via --define "stage <dossier>".
Name:           handshortcut
Version:        %{hsc_version}
Release:        1
Summary:        Gestes de la main vers actions (webcam, MediaPipe)
License:        MIT
BuildArch:      x86_64
AutoReqProv:    no
Requires:       glibc >= %{hsc_glibc}, mesa-libGL, glib2, libX11, libXrandr, wmctrl
Recommends:     playerctl, xclip, libnotify, xdotool, pulseaudio-utils
Suggests:       brightnessctl, ydotool
URL:            https://github.com/yo-le-zz/HandShortCut

%global debug_package %{nil}
%global _build_id_links none
%global __os_install_post %{nil}
%global _binary_payload w9.xzdio
%global _source_payload w9.xzdio

%description
HandShortCut detecte des gestes de la main via la webcam et declenche des
actions : lancer une application, deplacer une fenetre, ouvrir une URL,
envoyer un raccourci clavier, etc. Executable natif compile avec Nuitka, installe dans /opt/handshortcut. Interface : http://127.0.0.1:5678

%prep
%build

%install
mkdir -p %{buildroot}
cp -a %{stage}/. %{buildroot}/

%files
/opt/handshortcut
/usr/bin/handshortcut
/usr/lib/systemd/user/handshortcut.service
/usr/share/applications/handshortcut.desktop
/usr/share/icons/hicolor/*/apps/handshortcut.png
/usr/share/pixmaps/handshortcut.png
%doc /usr/share/doc/handshortcut/README.md
%doc /usr/share/doc/handshortcut/CHANGELOG.md
%license /usr/share/doc/handshortcut/LICENSE

%post
systemctl --global enable handshortcut.service >/dev/null 2>&1 || :
gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor >/dev/null 2>&1 || :
update-desktop-database -q /usr/share/applications >/dev/null 2>&1 || :
echo "HandShortCut installe. Lancer : handshortcut --open (demarrage auto a la prochaine connexion)"

%preun
/usr/bin/handshortcut stop >/dev/null 2>&1 || :
if [ $1 -eq 0 ]; then
    systemctl --global disable handshortcut.service >/dev/null 2>&1 || :
fi

%postun
if [ $1 -eq 0 ]; then
    rm -rf /opt/handshortcut
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor >/dev/null 2>&1 || :
    update-desktop-database -q /usr/share/applications >/dev/null 2>&1 || :
fi

%changelog
* Mon Nov 23 2026 yolezz - %{hsc_version}-1
- Executable natif (Nuitka), icone hicolor, desktop entry
