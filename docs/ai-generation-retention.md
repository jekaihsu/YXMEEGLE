# AI conversation fence retention

Generation rows fence delayed content writes after a conversation is deleted.
Run registration increments `active_runs`. Run completion decrements it.
Both operations refresh `last_activity_at` in the same transaction.
Content writes also refresh activity when they lock the generation row.

Cleanup retains rows with retained exchanges.
For other rows, `STALE_ACTIVE_RUN_SECONDS` allows cleanup to reclaim a stranded positive count after 24 hours without activity.
This exceeds the default 120-second question deadline and provider request timeouts of 10 seconds to connect, 60 seconds to read, 10 seconds to write, and 10 seconds for the pool.
Deployments that override `AI_QUESTION_TIMEOUT_SECONDS` must keep that deadline plus request timeouts below the stale-run bound.

The timestamp migration is additive and repeatable.
Existing rows receive the migration time.
Older workers can insert rows without the timestamp.
Cleanup initializes those rows with its current time before evaluating retention.
A failed release can leave a positive count, which the stale-run bound eventually reclaims.
