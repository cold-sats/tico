#!/bin/sh
# fetch-tool node|gh|litestream DEST: download one pinned tool for this architecture, checked against
# the sha256 in docker/versions.env, and unpack it under DEST.
set -eu
# shellcheck disable=SC1091
. /tmp/versions.env
case "$(dpkg --print-architecture)" in
  amd64) sha=X64;   node=x64;   go=amd64; ls=x86_64 ;;
  arm64) sha=ARM64; node=arm64; go=arm64; ls=arm64 ;;
  *) echo "unsupported architecture" >&2; exit 1 ;;
esac
fetch() {  # url sha256 dest
  curl -fsSL --retry 3 -o "$3" "$1"
  echo "$2  $3" | sha256sum -c -
}
dl=$(mktemp -d)
mkdir -p "$2"
case "$1" in
  node)
    fetch "https://nodejs.org/dist/v$NODE_VERSION/node-v$NODE_VERSION-linux-$node.tar.xz" "$(eval echo "\$NODE_SHA256_$sha")" "$dl/t"
    tar -xJf "$dl/t" -C "$2" --strip-components=1 --exclude='*/include' --exclude='*/share' --exclude='*.md' ;;
  gh)
    fetch "https://github.com/cli/cli/releases/download/v$GH_VERSION/gh_${GH_VERSION}_linux_$go.tar.gz" "$(eval echo "\$GH_SHA256_$sha")" "$dl/t"
    tar -xzf "$dl/t" -C "$dl"
    install -m 0755 "$dl/gh_${GH_VERSION}_linux_$go/bin/gh" "$2/gh" ;;
  litestream)
    fetch "https://github.com/benbjohnson/litestream/releases/download/v$LITESTREAM_VERSION/litestream-$LITESTREAM_VERSION-linux-$ls.tar.gz" "$(eval echo "\$LITESTREAM_SHA256_$sha")" "$dl/t"
    tar -xzf "$dl/t" -C "$dl" litestream
    install -m 0755 "$dl/litestream" "$2/litestream" ;;
  *) echo "unknown tool $1" >&2; exit 1 ;;
esac
