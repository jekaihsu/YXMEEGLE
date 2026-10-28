while pgrep -f "Build the Yongxiang" >/dev/null; do sleep 20; done
/home/box/.local/bin/codex exec --dangerously-bypass-approvals-and-sandbox -c service_tier="default" -c model_reasoning_effort="high" "$(cat PHASE2.md)" > codex_phase2.log 2>&1
cd /workspace/yongxiang_arch/ai_switchboard_mvp && /home/box/.local/bin/claude -p --permission-mode bypassPermissions "$(cat INTERROGATE.md)" > claude_interrogate.log 2>&1
echo CHAIN_DONE > chain.done
