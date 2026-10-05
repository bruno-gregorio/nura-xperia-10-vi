# Project Description

This project ports **postmarketOS** to the Sony Xperia 10 VI (`pdx246`,
Qualcomm SM6450 / "parrot").

It began as a LineageOS port; see `docs/02-design.md` for why it changed, and
`README.md` for the shape of the tree.

## Ground rules for agents

- **Never touch the host system.** All build work happens inside the `pmport`
  distrobox container (`distrobox enter pmport -- ...`). Installing packages
  inside that container is fine; installing anything on the Fedora host is not.
- **Keep every change inside this folder.** pmbootstrap is wired to write its
  config, work directory, chroots and caches under `.pmb/` (gitignored),
  because distrobox shares `$HOME` with the host and pmbootstrap's defaults
  would escape the project.
- `aports/` is the source of truth for our packages. `.pmb/pmaports` is a
  disposable upstream checkout; `scripts/sync-aports.sh` copies between them.
  After any command that rewrites an APKBUILD (`pmb checksum`), run
  `scripts/sync-aports.sh --back` before committing.
- Run pmbootstrap only through `scripts/pmb`, never directly — the wrapper is
  what redirects its state into the project.

## Status

Nothing has been run on the device. `docs/05-status.md` tracks what is verified
against sources, what is reasoned but untested, and what is an outright guess.
Keep it honest and up to date; it is the only thing standing between this port
and a bricked phone.
