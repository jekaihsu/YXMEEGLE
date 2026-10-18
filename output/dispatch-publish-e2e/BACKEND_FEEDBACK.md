# Backend observation from the real browser run

After a draft is saved, an unknown preview is created, verification reasons are added and a second preview of the same draft is published, `/work` still returns the earlier unknown preview as `workbench_preview` alongside the committed `v4_task` with the same title. It again appears in `needs_me` with verification blockers. This is distinct from a duplicate remote task or an unjoined command.

Both previews carried the same `draft_id`. `Store.overlay()` excludes published hashes before `build_work()` chooses the latest preview for that draft, so the earlier hash becomes visible again. The frontend cannot safely infer supersession from title equality. It retains the server rows.

Reproduce with `frontend/qa/dispatch-real-e2e.mjs`. The first create saves a draft, creates a blocked preview, verifies and re-previews, obtains three decisions and publishes. Read `/api/v2/dispatch/work?from=2026-10-19&to=2026-10-25&scope=all` afterward. See `real-network.json` for both preview hashes and their draft id.
