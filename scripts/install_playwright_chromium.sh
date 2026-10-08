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

if [ -z "$packages" ]; then
    echo "Could not read Chromium's system packages from Playwright" >&2
    exit 1
fi

# One install from a mirror, bounded. apt's own timeouts do not catch every
# stall: three runs hung after "noble-security InRelease" until the job limit,
# one of them for six hours. A stalled attempt is killed and the next one
# starts with a fresh index update.
install_from_mirror() {
    # shellcheck disable=SC2086 # the package names are meant to split
    sudo timeout --kill-after=10 300 apt-get update \
        && sudo timeout --kill-after=10 600 apt-get install -y --no-install-recommends $packages
}

# Warm cache: the cached package lists and .deb files are enough, so install
# without `apt-get update` and without downloading. Anything missing falls back
# to a mirror, which also fills the cache for the next run.
# shellcheck disable=SC2086 # the package names are meant to split
if sudo apt-get install -y --no-install-recommends --no-download $packages; then
    echo "Chromium system packages installed from the Actions cache"
else
    echo "Cache incomplete; installing Chromium system packages from a mirror"
    attempt=1
    until install_from_mirror; do
        if [ "$attempt" -ge 3 ]; then
            echo "Installing Chromium system packages failed after $attempt attempts" >&2
            exit 1
        fi
        attempt=$((attempt + 1))
        echo "Mirror install stalled or failed; attempt $attempt of 3"
        sleep 5
    done
fi

# apt leaves root- and _apt-owned files behind; the cache saves as the runner user.
sudo rm -f "$archives/lock" "$lists/lock"
sudo chown -R "$(id -u):$(id -g)" "$cache"
