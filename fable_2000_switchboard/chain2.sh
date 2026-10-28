while [ ! -f chain.done ]; do sleep 20; done
/home/box/.local/bin/codex exec --dangerously-bypass-approvals-and-sandbox -c service_tier="default" -c model_reasoning_effort="high" "$(cat R29.md)" > codex_r29.log 2>&1
echo done > chain2.done
