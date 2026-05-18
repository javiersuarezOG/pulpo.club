# resdet vendored binary (pulpo.club)

Vendored prebuilt binary of `resdet` 2.4.1 from https://github.com/0x09/resdet (MIT + LGPL).

Used by the nightly hires-photo pipeline (`automation/_download_hires_photos`) to validate that each newly-written `<file>.hires.jpg` is actually high-resolution and not a broker-side upscale.

| File | Platform | Source |
|------|----------|--------|
| `resdet-linux-x64` | Linux x86_64 musl (GitHub Actions ubuntu-latest) | release 2.4.1 — `resdet-2.4.1-linux-x86_64-musl.tar.gz` |
| `LICENSE.libresdet.txt` | — | upstream LGPL-2.1 |

## Why only the linux binary

The pulpo.club nightly runs only on GitHub Actions Linux runners. Operators running the pipeline manually from their laptop should call resdet via the vendored binary in `pulpo-social/packages/photo-quality/vendor/resdet/resdet-darwin-arm64` (cross-repo reuse — same release, different arch).

## Subprocess contract

```
./vendor/resdet/resdet-linux-x64 -v1 <path-to-hires.jpg>
```

Prints two whitespace-separated integers: best-guess source width and height. Exit code 0 means "ran successfully" — interpretation of upscaling is done in Python by comparing the detected width/height against the file's actual dimensions.

Update procedure: download a new release artifact from https://github.com/0x09/resdet/releases, drop the new `resdet` binary here named `resdet-linux-x64` (overwrite). Note the new version in the commit body.
