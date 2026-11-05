# Engineering progress acceptance

Run from the `progress-ui` worktree root. This server serves the production frontend build with synthetic API responses. It imports `chain_state` and `RawReader` from `backend/test_project_progress.py` and the frontend node-assignment fixture. It does not connect to Lark. Local SQLite files stay in `.runtime/`.

```sh
(cd frontend && npm ci && npx tsc -b && npm run build)
/Users/vc/Local/YXMEEGLE/.venv/bin/python frontend/qa/progress-fixture.py
```

Open `http://127.0.0.1:8766/?scenario=normal#view=project&project=p2&tab=progress`.
Use `normal`, `ambiguous`, `restricted`, `cold`, or `failure` as `scenario`. Reload between scenarios. Use `tab=overview` to inspect the compact strip. Use `tab=flow` to inspect optional SOP seed creation. The fixture server is read-only and does not implement POST.

Acceptance on 2026-10-17 used the built frontend in T3's collaborative browser at 1280×900 and 390×844.

- Both project tabs were captured and viewed for all five scenarios.
- Four production cards retain unknown actuals without progress bars. Planned quantity strings are displayed without re-summing.
- Ambiguity lists both candidates. Restricted finance shows its permission notice. Cold reports retain all other sections. A 503 retains the project shell and shows retry.
- The existing `ProgressDetail` Sheet opened for the requested case/week without changing the project URL, at both widths.
- Switching progress to overview kept exactly one progress resource request.
- The 390px progress page had no document overflow. All its buttons and disclosure summaries measured at least 44 CSS pixels high.
- Initial navigation/reload loaded `tab=progress` directly. SOP started from Lark displayed its badge and optional seed preview explanation.

Screenshots are outside git at `/tmp/progress-ui-shots/`. The 20 scenario screenshots follow `{normal,ambiguous,restricted,cold,failure}-{progress,overview}-{1280,390}.png`. Extra normal screenshots cover production, unknown actuals, the detail Sheet, and the SOP controls.

The frontend's 59 registered node script files ran. 55 passed. The known base failures were `shell-mode`, `ops-sync-panel`, `search-input`, and `unified-home`. The new progress suite has 10 passing tests. The updated SOP suite has 35 passing tests. TypeScript and the production build passed. No backend source was modified. Production Lark data and live writes were not exercised.
