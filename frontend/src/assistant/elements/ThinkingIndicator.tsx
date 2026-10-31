// Ported from assistant-ui ThinkingIndicator, copyright (c) 2026 AgentbaseAI Inc. MIT, see LICENSE.assistant-ui.
export function ThinkingIndicator(){
 return <div data-slot="thinking-indicator" className="assistant-working" role="status"><span aria-hidden="true" className="assistant-thinking-dot"/><span>思考中…</span></div>;
}
