#!/usr/bin/env bash
# Install pinned independent second-kernel verification tools (`lean4export` + `nanoda_bin`)
# matching Anthropic's Palomar verification bar for Linux CI.
set -euo pipefail

TOOLCHAIN="${LEAN_TOOLCHAIN:-leanprover/lean4:v4.33.1}"
NANODA_COMMIT="${NANODA_COMMIT:-68d5ca9db226849b41a6fff59d796ff19d0a8840}"
TOOLS_DIR="${TOOLS_DIR:-$HOME/.cache/lean-ci-tools}"

mkdir -p "$TOOLS_DIR/bin"

checkout_at() {
  if [ ! -d "$2/.git" ]; then
    git clone --quiet --filter=blob:none "$1" "$2"
  fi
  if [ "$(git -C "$2" rev-parse HEAD)" != "$3" ]; then
    git -C "$2" fetch --quiet --depth 1 origin "$3"
    git -C "$2" checkout --quiet --detach "$3"
  fi
}

# 1. Resolve matching lean4export tag (v4.33.1 -> fallback v4.33.0 for patch releases)
tags=("v${TOOLCHAIN#*:v}")
if [[ "$TOOLCHAIN" =~ ^(.*:v[0-9]+\.[0-9]+)\.[1-9][0-9]*$ ]]; then
  tags+=("v${BASH_REMATCH[1]#*:v}.0")
fi

LEAN4EXPORT_COMMIT="${LEAN4EXPORT_COMMIT:-}"
if [ -z "$LEAN4EXPORT_COMMIT" ]; then
  for tag in "${tags[@]}"; do
    refs="$(git ls-remote https://github.com/leanprover/lean4export "refs/tags/$tag" "refs/tags/$tag^{}")"
    LEAN4EXPORT_COMMIT="$(awk -v t="refs/tags/$tag^{}" '$2==t {print $1}' <<<"$refs")"
    [ -n "$LEAN4EXPORT_COMMIT" ] || LEAN4EXPORT_COMMIT="$(awk -v t="refs/tags/$tag" '$2==t {print $1}' <<<"$refs")"
    [ -z "$LEAN4EXPORT_COMMIT" ] || break
  done
fi
[ -n "$LEAN4EXPORT_COMMIT" ] || { echo "error: could not resolve lean4export for $TOOLCHAIN" >&2; exit 1; }

echo "== Building lean4export @ $LEAN4EXPORT_COMMIT ($TOOLCHAIN)"
checkout_at https://github.com/leanprover/lean4export.git "$TOOLS_DIR/lean4export" "$LEAN4EXPORT_COMMIT"
(cd "$TOOLS_DIR/lean4export" && lake "+$TOOLCHAIN" build lean4export)
ln -sf "$TOOLS_DIR/lean4export/.lake/build/bin/lean4export" "$TOOLS_DIR/bin/lean4export"

echo "== Building nanoda_lib @ $NANODA_COMMIT"
checkout_at https://github.com/robsimmons/nanoda_lib.git "$TOOLS_DIR/nanoda" "$NANODA_COMMIT"
cargo build --release --locked --quiet --manifest-path "$TOOLS_DIR/nanoda/Cargo.toml"
ln -sf "$TOOLS_DIR/nanoda/target/release/nanoda_bin" "$TOOLS_DIR/bin/nanoda_bin"

echo "Dual-kernel tools installed under $TOOLS_DIR/bin:"
ls -la "$TOOLS_DIR/bin"
