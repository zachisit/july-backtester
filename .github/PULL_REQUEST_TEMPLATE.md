## What this PR does
<!-- One paragraph. What problem does it solve or what does it add? -->

## Tasks addressed
<!-- Reference the ticket or task list item(s) this covers, e.g. "Task 3 from #42" -->

## Changes made
<!-- List every file added, modified, or deleted and one line explaining why -->

| File | Change |
|------|--------|
| | |

## Tests
<!-- Paste the full test suite result below — not just the files you added -->
```
rtk pytest tests/ --ignore=tests/test_report_batch.py -q
```

<!-- Paste result here -->

## Checklist

- [ ] Full test suite passes locally (`rtk pytest tests/ --ignore=tests/test_report_batch.py -q`)
- [ ] No API keys, `.env` files, `data_cache/`, or `output/` committed
- [ ] `CLAUDE.md` updated if new helpers, config keys, or architecture changes were made
- [ ] `README.md` updated if user-facing config or behaviour changed
- [ ] New strategies have a docstring explaining signal logic and params
- [ ] If a new config key was added, it has a default that preserves existing behaviour

## ⚠️ Bonus work policy

Any work not defined in the original task should be submitted as a separate PR.
If this PR contains work beyond the referenced task(s), move it to its own branch
and open a new PR before this one is reviewed.
