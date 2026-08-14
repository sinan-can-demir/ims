# Wiki

Short, searchable write-ups of specific bugs/gotchas found while working on
this repo — distinct from `docs/`'s other files (`model-registry.md`,
`multi-tenancy.md`, etc.), which document how a whole subsystem works.
A wiki page documents one incident: what happened, why, and the rule that
prevents it next time.

Each page should be short (a page or less) and follow the same shape:

- **Summary** — what happened, one or two sentences
- **Why happened?** — the actual mechanism, with exact evidence (real
  paths/commands/PR numbers, not paraphrased)
- **Rule** — one actionable sentence a skimming reader can act on
- **Fix** — what changed, and *why* the fix works, not just what it is

## Pages

- [gitignore doesn't match new `org_id=` nesting in `feature_store`, `models`](gitignore-org-id-nesting.md)
- [Tauri plugin JS packages need a bundler — this frontend doesn't have one](tauri-plugin-bare-imports-dont-resolve.md)
- [Android release builds silently block all cleartext HTTP](android-release-blocks-cleartext-http.md)
