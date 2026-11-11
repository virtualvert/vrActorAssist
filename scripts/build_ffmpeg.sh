#!/usr/bin/env bash
# Minimal LGPL ffmpeg.exe for the ShaderMotion live preview, bundled by build_agent.py.
# It has only what agent/shadermotion.py command() runs for live capture:
#   lavfi input: gfxcapture (Windows.Graphics.Capture, D3D11) -> hwdownload -> format -> crop -> setpts -> raw BGRA on a pipe.
# The test-only file mode (VRCAS_SHADERMOTION_SOURCE=<video>) still needs a full ffmpeg.
#
# Run in an MSYS2 UCRT64 shell (pacman -S mingw-w64-ucrt-x86_64-gcc make pkgconf diffutils):
#   bash scripts/build_ffmpeg.sh      ->  build/ffmpeg/ffmpeg.exe + COPYING.* + README.txt
set -euo pipefail

VERSION=8.1.3   # gfxcapture is new in 8.1
# Checked once against ffmpeg-8.1.3.tar.xz.asc (FFmpeg release signing key FCF986EA15E6E293A5644F10B4322F04D67658D8)
SHA256=7138d28c96d9d3e3af4ee3d8cad72741f8ffb40da90c1112235dea3ecd3178a3
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=$ROOT/build/ffmpeg
WORK=/tmp/vrcas-ffmpeg   # FFmpeg's build breaks on paths with spaces, such as C:\Users\Danny Grey\...

[ "${MSYSTEM:-}" = UCRT64 ] || { echo "Run this in an MSYS2 UCRT64 shell" >&2; exit 1; }

mkdir -p "$WORK" "$OUT"
cd "$WORK"
[ -f "ffmpeg-$VERSION.tar.xz" ] || curl -fL -o "ffmpeg-$VERSION.tar.xz" "https://ffmpeg.org/releases/ffmpeg-$VERSION.tar.xz"
echo "$SHA256  ffmpeg-$VERSION.tar.xz" | sha256sum -c -
rm -rf "ffmpeg-$VERSION"
tar -xJf "ffmpeg-$VERSION.tar.xz"
cd "ffmpeg-$VERSION"

FLAGS=(
  --disable-everything --disable-autodetect --disable-doc --disable-network --disable-x86asm
  --disable-programs --enable-ffmpeg --disable-swscale --disable-swresample --enable-small
  --enable-w32threads --enable-d3d11va
  --enable-indev=lavfi
  --enable-filter=gfxcapture,hwdownload,format,crop,setpts
  --enable-decoder=wrapped_avframe --enable-encoder=rawvideo --enable-muxer=rawvideo --enable-protocol=pipe
  --extra-ldflags=-static
)
./configure "${FLAGS[@]}"
# configure drops a filter whose dependencies are missing (here: C++17, the WinRT capture headers) with only a warning
grep -q 'define CONFIG_GFXCAPTURE_FILTER 1' config_components.h || { echo "gfxcapture didn't make it into the build" >&2; exit 1; }
make -j"$(nproc)"

cp ffmpeg.exe COPYING.LGPLv2.1 "$OUT/"
cp /ucrt64/share/licenses/*winpthreads*/COPYING "$OUT/COPYING.winpthreads"   # linked in statically
cat > "$OUT/README.txt" <<EOF
FFmpeg $VERSION for vrcActorSync's ShaderMotion live preview, built by scripts/build_ffmpeg.sh.
Licence: LGPL v2.1 or later (COPYING.LGPLv2.1). winpthreads is linked in statically (COPYING.winpthreads).
Source: https://ffmpeg.org/releases/ffmpeg-$VERSION.tar.xz (sha256 $SHA256), unmodified.
Configured with: ${FLAGS[*]}
Compiler: $(gcc --version | head -1)
ffmpeg.exe sha256: $(sha256sum ffmpeg.exe | cut -d' ' -f1)
EOF
ls -l "$OUT/ffmpeg.exe"
