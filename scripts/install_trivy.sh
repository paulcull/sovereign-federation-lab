#!/usr/bin/env bash
set -euo pipefail
# Verify the reviewed upstream binary before executing it. No curl | sh.
version=0.76.0
expected=e24b1c51293c1b15e4ba8d45bbc7891ba053f90278ec2698f3562c993e145fe7
destination=${1:?Usage: scripts/install_trivy.sh DESTINATION_DIRECTORY}
case "$(uname -s)/$(uname -m)" in
  Linux/x86_64) ;;
  *) echo 'This installer supports Linux x86_64; install Trivy 0.76.0 for your platform manually.' >&2; exit 2 ;;
esac
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT
curl --fail --location --silent --show-error --retry 3 \
  "https://github.com/aquasecurity/trivy/releases/download/v${version}/trivy_${version}_Linux-64bit.tar.gz" \
  --output "$temporary/trivy.tar.gz"
printf '%s  %s\n' "$expected" "$temporary/trivy.tar.gz" | sha256sum --check --status
mkdir -p "$destination"
tar -xzf "$temporary/trivy.tar.gz" -C "$temporary" trivy
install -m 0755 "$temporary/trivy" "$destination/trivy"
