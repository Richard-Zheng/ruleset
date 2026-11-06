#!/usr/bin/env bash
# 构建 linux/amd64 与 linux/arm64 的 sing-box、mihomo，并上传到 OSS。
#
#   sing-box  官方 tag 配置（release/DEFAULT_BUILD_TAGS_OTHERS），自编为了统一版本/flag
#   mihomo    -tags no_easytier（去掉 easytier），arm64 额外 upx --lzma --best
#   amd64     GOAMD64=v1（兼容 Pentium/Celeron、老 U 和 qemu64 类 VM；v3 收益在代理场景可忽略）
#   arm64     GOARM64=v8.0（Redmi AX6000=MT7986A、RAX3000M=MT7981B 都是 Cortex-A53，无 LSE）
#
# 用法：
#   ./build_bins.sh                 # 构建 + 上传
#   ./build_bins.sh --no-upload     # 只构建
#   ONLY=mihomo ./build_bins.sh     # 只做 mihomo（singbox / all，默认 all）
#
# 版本号从 git tag 注入，mihomo -v / sing-box version 均显示真实版本。
set -euo pipefail

WORK=${WORK:-/tmp/sb-bins}
OUT=${OUT:-$WORK/out}
OSS_PREFIX=${OSS_PREFIX:-oss://rulesets}
ONLY=${ONLY:-all}
UPX_ARM64=${UPX_ARM64:-1}       # 1 = arm64 产物 upx --lzma --best
QEMU=${QEMU:-qemu-aarch64}      # 用来跑 arm64 产物做自检

UPLOAD=1
for arg in "$@"; do
    case "$arg" in
        --no-upload) UPLOAD=0 ;;
        *) echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done

BUILD_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)

latest_tag() {
    # 只看稳定 tag（不含 -alpha/-beta/-rc）
    git ls-remote --tags --refs "$1" 'v*' \
        | awk '{print $2}' | sed 's#refs/tags/##' \
        | grep -v -- '-' | sort -V | tail -1
}

fetch_src() {
    local repo=$1 tag=$2 dst=$3
    rm -rf "$dst"
    git -c advice.detachedHead=false clone -q --depth 1 --branch "$tag" "$repo" "$dst"
}

# 统一的交叉编译环境：amd64 固定 v1，arm64 固定 v8.0
go_build() {
    local arch=$1; shift
    if [[ $arch == amd64 ]]; then
        env CGO_ENABLED=0 GOOS=linux GOARCH=amd64 GOAMD64=v1 "$@"
    else
        env CGO_ENABLED=0 GOOS=linux GOARCH=arm64 GOARM64=v8.0 "$@"
    fi
}

show_buildinfo() {
    go version -m "$1" 2>/dev/null \
        | grep -E '^\s+build\s+(GOARCH|GOAMD64|GOARM64)=' \
        | sed 's/^[[:space:]]*/    /' || true
}

build_mihomo() {
    local tag src
    tag=$(latest_tag https://github.com/MetaCubeX/mihomo.git)
    src=$WORK/mihomo
    echo ">>> mihomo $tag"
    fetch_src https://github.com/MetaCubeX/mihomo.git "$tag" "$src"

    # 版本号默认值写死在 constant/version.go（"1.10.0"），必须用 -X 覆盖，
    # 否则 mihomo -v 显示的是默认值而不是真实版本。
    local ldflags
    ldflags="-s -w -buildid="
    ldflags+=" -X github.com/metacubex/mihomo/constant.Version=$tag"
    ldflags+=" -X github.com/metacubex/mihomo/constant.BuildTime=$BUILD_TIME"

    local arch
    for arch in amd64 arm64; do
        echo "--- mihomo linux/$arch"
        (
            cd "$src"
            go_build "$arch" go build -trimpath -tags "no_easytier" \
                -ldflags "$ldflags" -o "$OUT/mihomo-linux-$arch" .
        )
        show_buildinfo "$OUT/mihomo-linux-$arch"
    done

    # arm64 体积减半（amd64 保留原样）
    if [[ $UPX_ARM64 == 1 ]]; then
        echo "--- upx --lzma --best mihomo-linux-arm64"
        upx -q --lzma --best "$OUT/mihomo-linux-arm64" >/dev/null
    fi
}

build_singbox() {
    local tag src tags ldflags
    tag=$(latest_tag https://github.com/SagerNet/sing-box.git)
    src=$WORK/sing-box
    echo ">>> sing-box $tag"
    fetch_src https://github.com/SagerNet/sing-box.git "$tag" "$src"

    # 官方 linux 非 naive 版本用的 tag 与 ldflags
    tags=$(cat "$src/release/DEFAULT_BUILD_TAGS_OTHERS")
    ldflags="-X github.com/sagernet/sing-box/constant.Version=${tag#v} $(cat "$src/release/LDFLAGS") -s -w -buildid="

    local arch
    for arch in amd64 arm64; do
        echo "--- sing-box linux/$arch"
        (
            cd "$src"
            go_build "$arch" go build -trimpath -tags "$tags" \
                -ldflags "$ldflags" -o "$OUT/sing-box-linux-$arch" ./cmd/sing-box
        )
        show_buildinfo "$OUT/sing-box-linux-$arch"
    done
}

mkdir -p "$OUT"
rm -rf "${OUT:?}"/*
case "$ONLY" in
    mihomo) build_mihomo ;;
    singbox|sing-box) build_singbox ;;
    all) build_mihomo; build_singbox ;;
    *) echo "ONLY must be mihomo|singbox|all" >&2; exit 2 ;;
esac

echo
echo ">>> 产物"
for f in "$OUT"/*; do
    printf '%-28s %10s  %s\n' "$(basename "$f")" "$(stat -c %s "$f")" \
        "$(sha256sum "$f" | cut -d' ' -f1)"
done

echo
echo ">>> 自检"
[[ -x $OUT/mihomo-linux-amd64 ]] && "$OUT/mihomo-linux-amd64" -v
[[ -x $OUT/sing-box-linux-amd64 ]] && "$OUT/sing-box-linux-amd64" version | head -2
if command -v "$QEMU" >/dev/null; then
    echo "--- arm64 via $QEMU"
    [[ -x $OUT/mihomo-linux-arm64 ]] && "$QEMU" "$OUT/mihomo-linux-arm64" -v
    [[ -x $OUT/sing-box-linux-arm64 ]] && "$QEMU" "$OUT/sing-box-linux-arm64" version | head -2
else
    echo "(没有 $QEMU，跳过 arm64 运行自检)"
fi
file "$OUT"/*

if [[ $UPLOAD == 1 ]]; then
    echo
    echo ">>> 上传到 $OSS_PREFIX"
    for f in "$OUT"/*; do
        ossutil cp -f "$f" "$OSS_PREFIX/$(basename "$f")"
    done
fi
