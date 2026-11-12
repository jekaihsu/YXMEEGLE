# Frontend integration decisions

The frontend reads captured backend responses from `docs/dispatch-publish-api-examples.json`. `dispatchPublishModel.ts` owns response parsing, error interpretation, endpoint paths and proposal serialization. The UI uses Chinese phase labels and serializes `formal` or `intake`. Manual verifications use `kind:ref` keys.

Work rows use a task, preview, draft or command identifier. This retains proposals that do not have a task record. PMs can open these proposals to record verification reasons and resume publication. Seat holders can review and decide a preview without assignment permission. The backend remains the authority for seat eligibility and allowed actions.

Assignment pickers read `/options`. Existing task forms read `/tasks/{id}`. Board occupancy does not define the available roster. Inactive people and people without a Lark account remain visible with an explanation and cannot be added.

A commit attempt creates one UUIDv4. Local recovery retains it across uncertain responses and retries. A duplicate-command response switches to the existing command. A 409 reservation refusal keeps the proposal and requires a new preview. A 502 response carrying a definitive failed command displays that command and permits editing before another attempt. Reconciliation follows the server's `next_action`.

Draft writes use PUT and the last known version. A version conflict leaves the local proposal intact and offers explicit loading of the server version. Reloading the server draft list cannot erase an in-flight local command.

A changed verification reason disables approval and publication until another preview. Refreshing seat decisions uses GET for the same preview. Published work details expose all 21 V4 extension fields.

This is an implementation delegate following the owner's fixed architecture and path restrictions. Architecture and code review stay in this thread. No child worktrees or pull requests are created.
