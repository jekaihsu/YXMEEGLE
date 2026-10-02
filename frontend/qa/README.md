# Browser acceptance record

Validated on 2026-09-25 with the `meegle-ui` Playwright CLI session against `http://127.0.0.1:8000`. Only the isolated demonstration workspace was mutated. The separate `meegle-lark` browser session was not accessed.

## Passed scenarios

- Demo role switch: PM → control member → manager → PM; correct actor persisted through reload.
- Control task `p1-control-t2`: start, enter output, complete; API state and row status updated. Task comment persisted.
- Extension: draft → submit; original deadline retained and task not paused; simulated Lark approval did not automatically apply the new deadline; explicit execute changed deadline to `2026-10-01` while retaining original `2026-09-24`.
- Participant update: node owner and inherited active task owners changed; completed task owner remained unchanged.
- Design change: selected work item and matching downstream paused; unrelated work remained pending; supervisor + client confirmations alone did not approve; third Lark confirmation enabled explicit revision execution. Original tasks became superseded and replacement tasks were retained separately.
- File link, multipart upload, authenticated file download and byte content verified.
- Project search, progress sort, weekly schedule and resource view rendered correctly.
- Daily check reported “尚未查到作業紀錄” for the expected control date, without equating absence with incomplete work.
- Hash deep links survived browser refresh.
- 1440px desktop and 390px mobile dashboard, project and task inspector inspected. A dashboard grid minimum-width overflow was fixed; document width assertions then passed.
- Browser console: 0 errors, 0 warnings.
- `npm run build`: TypeScript and production Vite build passed.

## Artifacts

Screenshots are under `../../output/playwright/`: dashboard desktop/mobile, project desktop/mobile, inspector mobile, task desktop, extension approval, change approval, schedule desktop, projects mobile.

The JavaScript files in this directory are Playwright CLI `run-code --filename=...` scenario segments, not independent tests; they assume preceding UI scenario state. `fixture.txt` is non-sensitive sample upload content.

After acceptance, demonstration data was restored using the visible manager-only reset confirmation and the session was returned to the PM role. Formal Lark OAuth, production source access and native approval integration require their configured environment and were not claimed as verified by these local demo tests.
