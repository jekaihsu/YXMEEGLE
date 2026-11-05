# Project detail UX: synthetic verification route and evidence

Everything here uses synthetic data. Nothing reads or writes a real case, task or Lark record.

## The in-app fixture route (works on staging)

Open the staging app, sign in as usual, then use one of these URLs:

`https://yongxiang-workbench-staging.zeabur.app/#view=stage-fixture&tab=<scenario>`

| `tab=` | What it shows |
| --- | --- |
| `normal` | Save succeeds, drawer closes, list shows the new executor, focus returns to the trigger |
| `validation` | Candidate rejected (422): error beside the field and in the top summary, draft kept |
| `conflict` | Revision conflict (409): draft kept, latest value diff, explicit re-check before any resubmit |
| `forbidden` | Server 403 on submit: "權限已變更", save disabled, capabilities re-read |
| `timeout` | Timeout / unknown outcome: retry stays disabled until the latest result is read, then retries with the same request id |
| `partial` | Change executor and deadline together: result read-back shows executor saved, deadline not |
| `revoked` | The assign capability disappears about 2.5 s after the drawer opens: save is disabled with the reason |

The page renders the real `AssignDrawer` against in-memory stand-ins for the mutation, read-back and retry calls. It never calls `fetch`, so no request of any kind is sent for the scenarios (`test-stage-fixture.mjs` fails if `fetch` is used, and `qa/stage-evidence.mjs` counts non-GET requests). The route sits behind the normal sign-in, so no authentication or authorization is changed. It is a lazy chunk, outside the entry bundle.

## Reproducing the screenshots

```
cd frontend
npm ci
node qa/project-flow-preview.mjs &        # builds the app and serves it with synthetic API fixtures on :5208
node qa/stage-evidence.mjs ../.runtime/evidence
```

The script writes PNGs and `report.json` for 1440, 1024, 768, 390 (DPR 2) and 200 % zoom (720 x 450 CSS px at DPR 2, which is 200 % of a 1440 px window). It covers the case page (top, node and tasks, drawer), the seven fixture scenarios at every width, page-open zero writes, write, conflict, 403 and unknown outcome against the fixture API server, and a 100-task timing run (CDP throttled to 20 Mbps / 100 ms RTT, local static build).

## Not run (UNTESTED)

- Live writes on staging or any real data. The write paths ran only against the synthetic fixture server and the in-memory route.
- Staging performance. Timings come from a local static build with emulated network.
- A signed-in browser pass on staging with real Lark data.
