# gitignore doesn't match new org_id/ nesting in feature_store, models

## Summary

During Epoch 10, PR 15 (#151), the change in file export path caused
git to recognize parquet files as changes. Parquet files are
sensitive files that contain customer organization data.

## Why happened?

Because we changed the file path for parquet from `feature_store/*.parquet`
to `feature_store/org_id=1/daily_sales.parquet`, this caused `.gitignore`
to see them as unignored files. We caught this during a `git status` check
before committing.

## Rule

Run `git status` before staging/committing, especially right
after a script or pipeline generates new files.

## Fix

The fix is easy. We changed the pattern to `feature_store/**/*.parquet`,
which ignores all parquet files in the `feature_store` directory
regardless of nesting depth. `*` doesn't match across a `/`, `**` does.
