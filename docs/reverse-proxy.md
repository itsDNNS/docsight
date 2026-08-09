# Reverse-Proxy Path Prefixes

DOCSight can run at an origin root or below a same-origin path such as
`https://monitor.example.test/docsight/`. The reverse proxy owns the public
boundary: it accepts only the configured mount, removes that prefix from the
path sent upstream, and forwards the remainder to DOCSight at `/`.

`REVERSE_PROXY` and path-prefix configuration solve different problems:

- `REVERSE_PROXY=N` trusts exactly `N` proxy hops for forwarded client address
  and protocol information and enables secure session cookies.
- `BASE_PATH` or `REVERSE_PROXY_PREFIX=N` tells DOCSight about its external URL
  mount. Neither setting enables the other.

## Choose one mount mode

Explicit mode is the simplest option when the mount is known before startup:

```dotenv
BASE_PATH=/docsight
# REVERSE_PROXY_PREFIX is unset or 0
```

The proxy strips `/docsight` and removes `X-Forwarded-Prefix` before forwarding.
DOCSight still receives `/health`, `/api/config`, and other paths at the origin
root of its local listener; it uses `BASE_PATH` only when generating external
URLs and cookie scope.

Trusted-prefix mode is useful only when the mount must come from trusted proxy
configuration:

```dotenv
# BASE_PATH is unset
REVERSE_PROXY_PREFIX=1
```

The number is an exact trusted hop count, selected from right to left. The edge
must strip any incoming `X-Forwarded-Prefix` and replace it with the canonical
mount. For multiple trusted prefix-setting proxies, configure the exact count
and a complete chain. A missing, short, malformed, or ambiguous selected value
fails closed.

You may set both modes as a deployment assertion. In that case the selected
trusted header, explicit `BASE_PATH`, and any existing WSGI `SCRIPT_NAME` must
all agree after normalization. `BASE_PATH=/` is an explicit root value and must
agree with a selected `/` header entry.

## Nginx prefix-stripping examples

Explicit mode removes any prefix header received from the client:

```nginx
location = /docsight {
    return 308 /docsight/;
}

location /docsight/ {
    proxy_set_header X-Forwarded-Prefix "";
    proxy_set_header Host $host;
    proxy_pass http://127.0.0.1:8765/;
}
```

The trailing slash on `proxy_pass` makes Nginx strip the matched `/docsight/`
prefix. Configure the container with `BASE_PATH=/docsight`.

Trusted-prefix mode replaces, rather than appends to, the incoming header:

```nginx
location = /docsight {
    return 308 /docsight/;
}

location /docsight/ {
    proxy_set_header X-Forwarded-Prefix /docsight;
    proxy_set_header Host $host;
    proxy_pass http://127.0.0.1:8765/;
}
```

Configure the container with `REVERSE_PROXY_PREFIX=1`. Do not allow the public
origin to forward `/health`, `/api`, `/static`, `/sw.js`, or any other DOCSight
path outside the external mount. All UI, API, manifest, service-worker, export,
and authentication traffic must remain on the same origin and within that
mount.

## Container healthcheck

The image healthcheck always requests the local upstream URL
`http://localhost:${WEB_PORT:-8765}/health`; it never adds the external mount to
that URL because the production proxy strips the mount before forwarding.

- Root mode and explicit `BASE_PATH` mode need no prefix header.
- Trusted-prefix mode sends a fixed valid synthetic prefix chain sized for the
  configured `REVERSE_PROXY_PREFIX` hop count.
- Combined mode sends the explicit mount for every probe chain entry, including
  `/` for an explicit root, so runtime source agreement is exercised.

Invalid configuration, network failures, non-2xx responses, malformed JSON, or
a response whose `status` is not `ok` marks the container unhealthy. Probe
failures emit only a short generic message; request headers, response bodies,
mounts, and ingress-like values are not printed.

## Platform wrappers and authentication

DOCSight Core does not query a platform supervisor or consume platform identity
headers. A wrapper may obtain its platform-assigned mount and set an explicit
`BASE_PATH` before DOCSight starts. The wrapper must still enforce prefix
stripping and the same-origin boundary described above.

Home Assistant can authenticate access to its Ingress gateway, but DOCSight
Core does not inherit Home Assistant identity or session state. DOCSight's own
admin-password boundary remains active; apply the same network-access controls
you would use for any other DOCSight deployment.
