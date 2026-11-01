// Ported from assistant-ui ThinkingIndicator, copyright (c) 2026 AgentbaseAI Inc. MIT, see LICENSE.assistant-ui.
export function ThinkingIndicator(){
 return <div data-slot="thinking-indicator" className="assistant-working" role="status"><span aria-hidden="true" className="assistant-thinking-dot"/><span>正在查詢與整理資料…</span></div>;
}
