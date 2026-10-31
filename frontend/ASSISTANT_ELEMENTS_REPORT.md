# Assistant elements implementation

The chat renders server-projected tables and charts in tool message parts. Completed replies accept optimistic feedback, cancellation, and optional down-vote reasons.

- The [research report](ASSISTANT_ELEMENTS_RESEARCH.md) records all 151 catalog decisions with one reason each, the upstream source revision, source anatomy, licensing, and pinned API findings.
- Ported DataTable, Chart, and ThinkingIndicator from assistant-ui registry source. Preserved their root data-slot hooks and applicable semantic anatomy. Retained the MIT notice. Added no package, Tailwind, or shadcn dependency.
- Kept existing thread, composer, speaker, starter prompts, model picker, markdown fallback, copy, retry, tool status, and scroll-to-bottom controls. Skipped reasoning, citation links, and timestamps because the contract supplies no corresponding trustworthy data. Source time stays in table captions.
- The table supports stable three-state comparison sorting, nulls last, numeric alignment, keyboard controls, desktop horizontal scrolling, narrow cards, a mobile sort selector, captions, notes, empty rows, and truncation notices.
- The bars chart includes a headline, category labels and values, a summary on role=img, a hidden semantic data table, focus and hover tooltips, and token colors in both themes. No category depends on color alone.
- Feedback uses the real pinned ActionBarPrimitive actions and useLocalRuntime adapters.feedback. Each reply stores usage_id in metadata.custom and its rating in metadata.submittedFeedback. Errors restore the prior rating and reason, with an inline error. Incomplete replies have no thumbs.
- The pinned runtime lacks feedback cancellation and an async metadata setter. The bridge uses public thread export/import while idle. During a new reply it defers a pending save's metadata update until streaming ends. Feedback buttons are disabled while saving or running. This is an API accommodation, not a wire-contract change.

Changed files are `src/Assistant.tsx`, `src/Assistant.css`, `src/assistant/{stream.ts,runtime.ts,ToolResult.tsx,feedback.tsx,fixtures.ts}`, `src/assistant/elements/*`, `package.json`, `test-assistant-elements.mjs`, and `scripts/verify-assistant-elements.mjs`.

Verification passed on the built artifact and node harnesses.

- `npm ci` ran first. npm reported one existing high-severity advisory. Dependency versions were unchanged.
- `npm run build` passed. Vite retains the existing warning about the large assistant chunk.
- `npm run test:assistant` passed, including markdown table fallback and existing stream, error, and session coverage.
- `npm run test:assistant:elements` passed. Covers five fixtures at split UTF-8 boundaries, usage metadata, payload limits, numeric sorting, card markup and mobile sorting, chart accessibility and focus tooltip, StrictMode feedback, toggle-off, reason choices, dismissal, rollback, rerender persistence, incomplete replies, and rollback during a new stream.
- `npm run test:assistant:bundle`, `node test-build-loading.mjs`, and `npm run test:dev-tooling` passed. The tooling suite has six passing tests.
- `node scripts/verify-assistant-elements.mjs` passed against the production build in the real demo backend shell. SQLite, uploads, and an SSE mock were kept under `/tmp`. The mock streams the same fixture module used by the tests. All five fixture scenarios, 390px cards, desktop table sorting, chart tooltips, light and dark themes, selected feedback, reason chips, rollback, and incomplete reply states passed. No browser page errors or horizontal page overflow occurred.

Screenshots are under `/tmp/ai-feat-chat-ui-screenshots/`.

- `table-desktop.png` and `table-390.png` show the table and narrow cards.
- `chart-light.png` and `chart-dark.png` show the chart with its focus tooltip.
- `feedback-reasons.png` and `feedback-pressed.png` show the selected thumb and optional reason choices.
- `feedback-error.png` and `reply-error.png` show rollback and an incomplete reply.

The mock server is `/tmp/ai-feat-chat-ui-mock.py`. Its streams are `/tmp/ai-feat-chat-ui-fixtures.json`. The browser verification script accepts ASSISTANT_DEMO_URL, ASSISTANT_SCREENSHOTS, and CHROME_PATH.

There are no functional wire-contract deviations. The ports intentionally implement only the table primitive values and bars variant in the contract. Live provider calls and the backend worker's implementation were not exercised.

Model the Domain shaped the table/chart union and per-message feedback state. Prove It Works shaped the fixture-driven tests and production browser checks. Implementation and verification ran in-thread because this task is the implementation sub-agent's assigned work. No push or PR was created.

Build sizes at verification follow.

- `assets/Assistant-DjSsxsot.js` is 754875 bytes raw and 224329 bytes gzip.
- `assets/Assistant-DZUMKsLY.css` is 9784 bytes raw and 2245 bytes gzip.
- All initial JavaScript totals 436435 bytes, below the unchanged 460000-byte budget. Assistant JavaScript and CSS remain deferred.
