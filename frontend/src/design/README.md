# Shared foundation

`DataState` is exported from `design` and `design/DataState`.

- `kind`: Loading, Empty, Stale, Partial, Error, Denied, Conflict, UnknownOutcome.
- `title`: short Traditional Chinese heading.
- `body`: ReactNode describing what happened, what survives, and next steps.
- `actions?`: explicit buttons/links; omit to omit the action row entirely. Use shared Button or `.ds-button` links (44px).

Loading/Empty/Stale/Partial use `role=status`. Error/Denied/Conflict/UnknownOutcome use `role=alert`. Icons are decorative. Tokens support light, dark and system themes; no fixed height or automatic retry. One instance per shared source; independent errors remain local. Denial requires the owning data layer to remove protected content. No other pages were migrated.

Shell recents store case IDs in sessionStorage under user + workspace + API session epoch, bounded to five. A visited route must match a case in the current authorized workspace; no first-three or hovered/prefetched entries. Storage exceptions keep the in-memory list functional. Scope cleanup removes the old key. Names are resolved only from current workspace data.
