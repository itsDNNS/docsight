#!/usr/bin/env bash
# Install Chromium and its system packages for the browser tests.
#
# The workflow restores ~/.cache/ms-playwright and ~/.cache/playwright-apt from
# the Actions cache: the browser, the .deb files and apt's package lists. With
# a warm cache nothing here contacts an Ubuntu mirror, so a slow or silent
# mirror no longer decides whether a browser job finishes.
set -euo pipefail

cache="$HOME/.cache/playwright-apt"
archives="$cache/archives"
lists="$cache/lists"
mkdir -p "$archives/partial" "$lists/partial"
printf 'Dir::Cache::Archives "%s/";\nDir::State::Lists "%s/";\n' "$archives" "$lists" \
    | sudo tee /etc/apt/apt.conf.d/90docsight-playwright-cache >/dev/null

# When a mirror has to be asked (cold cache), give up on a silent request after
# 30 s and retry instead of waiting until the job times out.
printf 'Acquire::http::Timeout "30";\nAcquire::https::Timeout "30";\nAcquire::Retries "3";\n' \
    | sudo tee /etc/apt/apt.conf.d/80docsight-network >/dev/null

# The browser itself comes from ~/.cache/ms-playwright when cached.
python -m playwright install chromium

# Chromium's system packages, exactly as `playwright install-deps` would install them.
packages=$(python -m playwright install-deps --dry-run chromium \
    | sed -n 's/.*--no-install-recommends \([^"]*\).*/\1/p')

# Warm cache: the cached package lists and .deb files are enough, so install
# without `apt-get update` and without downloading. Anything missing falls back
# to the regular install, which updates the lists and downloads from a mirror.
# shellcheck disable=SC2086 # the package names are meant to split
if [ -n "$packages" ] && sudo apt-get install -y --no-install-recommends --no-download $packages; then
    echo "Chromium system packages installed from the Actions cache"
else
    echo "Cache incomplete; installing Chromium system packages from the mirror"
    python -m playwright install-deps chromium
fi

# apt leaves root- and _apt-owned files behind; the cache saves as the runner user.
sudo rm -f "$archives/lock" "$lists/lock"
sudo chown -R "$(id -u):$(id -g)" "$cache"
