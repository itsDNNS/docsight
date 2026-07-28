# Code signing policy

## Status and provider

DOCSight is preparing to onboard with the SignPath Foundation OSS program.
Provider verification and signing configuration are still in progress.
Current Windows artifacts remain unsigned until onboarding succeeds.

## Conditional provider attribution

The following attribution will apply only if provider approval and onboarding
succeed:

Free code signing provided by SignPath.io, certificate by SignPath Foundation

The official public download surface is
[GitHub Releases](https://github.com/itsDNNS/docsight/releases). Release pages
identify the available artifacts and publish their checksums.

## Project roles and approval

DOCSight is an MIT-licensed project maintained by its repository owner,
[itsDNNS](https://github.com/itsDNNS). The current project roles are:

| Role | Holder |
| --- | --- |
| Maintainer, committer, and reviewer | itsDNNS |
| Signing approver | itsDNNS |

As a compensating control for this sole-maintainer role structure, the
source-control account and any future signing-approval account must use
multi-factor authentication (MFA). Signing approval requires review of the
release source, workflow result, artifact identity, and expected version.

Trusted release signing requires an approved release context. Approval is
limited to an official tagged release from the DOCSight repository. A pull
request, fork, workflow run from an untrusted context, or local build is not
eligible for signing. Pull requests and forks do not receive signing credentials
or signing-service access.

## Signing scope and verification

If onboarding succeeds, the signing scope is limited to Windows executable
files in official DOCSight release assets. Signing is not available for
third-party builds, forks, pull request artifacts, or general development
builds. Signed files are expected to receive a trusted timestamp through the
approved signing service.

Once signed artifacts exist, Windows users can validate an extracted executable
with the Windows SDK SignTool:

```powershell
signtool verify /pa /v .\DOCSight\DOCSight.exe
```

Until then, preview artifacts are unsigned. Each Windows Preview ZIP on the
official release has a corresponding `.sha256` asset for an optional advanced
integrity check. Download both files from the same release, then run this
optional PowerShell comparison from the folder containing them:

```powershell
$zip = ".\DOCSight-Desktop-Preview-win64-<version>.zip"
$checksumFile = "$zip.sha256"
$checksumText = Get-Content -LiteralPath $checksumFile -Raw
$expectedHash = if ([string]::IsNullOrWhiteSpace($checksumText)) { "" } else { ($checksumText.Trim() -split '\s+', 2)[0] }
$actualHash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash
$checksumMatches = [string]::Equals($actualHash, $expectedHash, [System.StringComparison]::OrdinalIgnoreCase)
$checksumMatches
```

The final command returns `True` only when the ZIP hash matches the first hash
value in the checksum file. SHA-256 is hexadecimal, so uppercase and lowercase
letters represent the same hash value and are compared case-insensitively. A
matching checksum verifies download integrity against the published checksum.
It does not verify publisher identity or replace a code signature.

## Privacy and security reporting

DOCSight does not transfer information to other networked systems unless
explicitly configured or requested by the operator. The
[security policy](SECURITY.md) documents the local-first, no-telemetry model and
the private channels for reporting security concerns.

## Revocation and incidents

Signing approval is withheld if the release context, artifact identity, or
signing authorization cannot be verified. If signing access, a certificate, or
a signed artifact may have been compromised or misused, the maintainer will:

1. Stop approving and publishing affected Windows artifacts.
2. Notify SignPath and SignPath Foundation as appropriate, and request
   revocation when required.
3. Investigate affected versions and publish corrected artifacts only from a
   newly verified release context.
4. Publish relevant impact and verification guidance after containment, without
   disclosing credentials or details that would enable further misuse.

Report suspected signing incidents through the private channels in
[SECURITY.md](SECURITY.md).
