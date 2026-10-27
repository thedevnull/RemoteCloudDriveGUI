#!/usr/bin/env bash
# Gera RcloneMountSetup-x86_64.AppImage (precisa de internet só para baixar o appimagetool).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

ARCH="${ARCH:-x86_64}"
TOOL="./appimagetool-$ARCH.AppImage"

if [ ! -x "$TOOL" ]; then
    echo "==> Baixando appimagetool..."
    curl -fsSL -o "$TOOL" \
      "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage"
    chmod +x "$TOOL"
fi

rm -rf AppDir
mkdir -p AppDir/usr/share/rclone-gui
cp rclone_gui.py AppDir/usr/share/rclone-gui/
cp AppRun rclone-gui.desktop rclone-gui.png AppDir/
chmod +x AppDir/AppRun
cp rclone-gui.png AppDir/.DirIcon

echo "==> Empacotando..."
export ARCH
if ! ARCH="$ARCH" "$TOOL" AppDir "RcloneMountSetup-$ARCH.AppImage" 2>/dev/null; then
    # sem FUSE no sistema de build
    ARCH="$ARCH" "$TOOL" --appimage-extract-and-run AppDir "RcloneMountSetup-$ARCH.AppImage"
fi
echo "==> Pronto: RcloneMountSetup-$ARCH.AppImage"
