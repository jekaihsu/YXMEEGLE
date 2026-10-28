while [ ! -f chain2.done ] || pgrep -f "Red-team review" >/dev/null; do sleep 20; done
/home/box/.local/bin/codex exec --dangerously-bypass-approvals-and-sandbox -c service_tier="default" -c model_reasoning_effort="high" "$(cat R30.md)" > codex_r30.log 2>&1
echo done > chain3.done
