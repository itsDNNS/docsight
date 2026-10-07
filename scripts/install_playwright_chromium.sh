#!/usr/bin/env bash
# Install Chromium and its system packages for the browser tests.
#
# The workflow restores ~/.cache/ms-playwright and ~/.cache/playwright-apt from
# the Actions cache, so the browser and the .deb files usually come from there.
# A slow Ubuntu mirror then no longer decides how long a browser job takes.
set -euo pipefail

archives="$HOME/.cache/playwright-apt"
mkdir -p "$archives/partial"
echo "Dir::Cache::Archives \"$archives/\";" | sudo tee /etc/apt/apt.conf.d/90docsight-playwright-cache >/dev/null

python -m playwright install --with-deps chromium

# apt leaves root- and _apt-owned files behind; the cache saves as the runner user.
sudo rm -f "$archives/lock"
sudo chown -R "$(id -u):$(id -g)" "$archives"
