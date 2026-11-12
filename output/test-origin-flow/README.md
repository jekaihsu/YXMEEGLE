# Test-origin task acceptance

Verified locally on 2026-10-27 against the production frontend build and the real FastAPI routes, using an isolated SQLite database and existing fictional seeded cases. No staging business data was changed.

## Metis staging steps

Deploy the PR's reviewed head SHA to the existing staging service before acceptance. Staging currently runs the older base and does not have this UI or the projection guard. This PR does not deploy or merge itself.

1. Sign in to the existing staging workspace as a manager. Open the existing case C115211-01A and an already enrolled SOP node under **流程與任務**. Keep the case fields unchanged.
2. In the SOP task section, click **新增任務**. Enter a task title and enable **測試任務** before clicking **建立任務**. Use manual creation for this acceptance path. Imported template tasks cannot acquire disposable test provenance.
3. Confirm that the task list shows **測試** and that its Lark status is **未啟用**. Open the task drawer and confirm its **測試** badge.
4. Change the title or notes and click **儲存任務**. Assign a permitted person and save again. The task keeps its test provenance after both changes.
5. Close the drawer. Select a task filter that includes this task. Reopen the task, click **清除測試任務**, and confirm that **確認清除** is disabled until a nonblank **清除原因** is entered.
6. Enter the acceptance reason and click **確認清除**. Confirm that the task disappears, the drawer closes, the filter stays selected, and keyboard focus returns to the SOP task list. The cleanup audit remains.
7. As a non-manager PM or member, confirm that **測試任務** is absent from creation and **清除測試任務** is absent from a tagged task's drawer. The badge remains visible to permitted readers. Case-management authority alone does not grant test controls.

Only tasks created with the provenance flag are removable. A name or prefix never grants cleanup permission. Do not create another case or tenant, change the named case, or switch workspaces to production.

## Refusals

- `503 cleanup_migration_required` shows the cleanup audit migration message. Stop and ask the operator to verify the existing migration. Do not delete local rows manually.
- `409 test_task_projection_exists` preserves the task and links. It refuses any projection outbox row, including an unsent or paused row. Ask the operator to inspect the recorded projection identity. This feature never deletes or updates Lark business records.
- `409 task_revision_conflict` reloads the task. Check the current task, then retry the confirmation with its refreshed revision.
- `409 test_task_required` refuses ordinary tasks or tasks with their test tag removed.
- `409 task_reopen_required` requires reopening a task that has completed with proof.

## Staging projection gates

Read-only inspection of the existing staging service at approximately 14:55 Asia/Taipei returned:

```json
{"SOP_LARK_PROJECTION_ENABLED":"true","SOP_TASK_WRITES_ENABLED":"true","APP_ENV":"production","LARK_WORKER_IDENTITY":"application"}
{"projection_gates_allowed":true,"external_enabled":true,"workspace_environment":"production","read_only":true}
```

These are the staging service's existing settings. No flag or environment was changed. The effective `gates()` check includes the configured organization, approved app, credentials presence, and table write policy. It made no Lark business-data request.

## Browser evidence

- [Manager creation with the test toggle](manager-create.png).
- [Edited and assigned test task](manager-edited-assigned.png).
- [Cleanup confirmation and required reason](cleanup-confirm.png).
- [PM creation without the test toggle](pm-create.png).
- [PM reading a tagged task without cleanup](pm-tagged-task.png).
- [Cleanup completed with the unassigned filter retained](cleaned-filters.png).

The manager flow recorded create at revision 1, title edit at revision 2, assignment at revision 3, and `test_cleaned` at revision 3. The database then contained zero local SOP tasks, task-node links, and projection outbox rows. All four audit events remained. Separate browser checks verified the non-manager controls and cleanup with the **未指派** filter retained and focus on `#sop-tasks`.

## Review

One independent read-only review by `claudeAgent/claude-opus-5-5`, effort `xhigh`, found no P1/P2 issues. No reviewer wrote files or delegated further work. Implementation, comment inspection, and verification remained with the single writer.

The review noted the pre-existing worker failure for already orphaned outbox rows. This PR prevents new test-task orphans and refuses cleanup of tasks with projection rows. It does not repair historical orphaned rows or delete remote records.

## Tests

- Full backend suite, `python -m pytest backend -q`. **5288 passed, 37 skipped, 1 xfailed**. PostgreSQL-dependent tests were skipped because no test PostgreSQL URL was configured.
- Focused cleanup and projection suites, `python -m pytest backend/test_local_task_cleanup.py backend/test_sop_lark_projection.py -q`. **59 passed, 1 skipped**.
- All **56** configured frontend `test:*` scripts ran. **55 passed**. The sole failure is the known baseline `test:shell-mode` assertion at `test-shell-mode.mjs:57`.
- All **61** additional top-level frontend `test-*.mjs` files outside those scripts passed. Together these runs cover all **134** frontend test files.
- Focused SOP UI suite, `node frontend/test-sop-tasks.mjs`. **41 passed**, including manager/admin versus PM/member toggle visibility, request flags, badges, cleanup reason, cancellation, refreshed errors, filter retention, and focus.
- `npm run build --prefix frontend` and `git diff --check` passed.
