# UI cleanup verification

Branch: `t3/ui-work`. Scope: 我的工作、報價總表、人員／資源與出勤.

- `work-after.png`, `quotes-after.png`, `people-after.png`: live demo, 1440 × 900 full-page captures.
- `quotes-populated-after.png`, `people-populated-after.png`: explicitly synthetic fixture data injected only in the browser to verify row layouts; these are not company records.
- `people-mobile-after.png`: synthetic attendance fixture at 390 × 844.
- Before captures: `/tmp/ui-work/{work,quotes,people}-before.png` (1440 × 1000).

Browser checks: six passed; no page errors. Quote table scroll/client widths both 982px at 1440px viewport. Populated attendance table begins at y=616px and its first rows fit within 900px. Mobile document has no whole-page horizontal overflow.

Tests: `node --test test-quotes.mjs test-quotes-ui.mjs test-people-attendance.mjs test-my-work-view.mjs test-my-work-integrated.mjs test-my-work-return-focus.mjs test-work-assigned-visibility.mjs test-home-people-cards.mjs` — 28 passed, 0 failed. The model suite additionally reports 16 scenarios / 130 checks. Logs are in `/tmp/ui-work/tests.log`.

Demo prerequisites: this checkout is missing `backend/node_assignment/bulk.py`; it was temporarily copied from the main checkout for local demo startup, then removed without committing. Local Vite used API 8813 and port 5813 with a temporary proxy config; neither backend nor proxy changes are included.

Design: use existing tokens and components. Quote engineering number, quote dates, PM and SOP counts remain in the existing detail sheet; all stage filters remain available in one dropdown. Work source uncertainty is one sentence, not zero work; legacy status facts are deduplicated without changing the source contract. Empty board lanes and trips are hidden. No dispatch or navigation changes.

Build validation: `npx tsc -b` passed; `npx vite build --outDir /tmp/ui-work/dist` passed. Impeccable mechanical detector returned no findings.
