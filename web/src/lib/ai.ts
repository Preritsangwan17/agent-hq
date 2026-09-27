import type { ModelsResponse, BudgetState, ProviderState } from './types';
export interface Usage { calls: number; estimated_cost_usd: number; input_tokens: number; output_tokens: number }
export interface AIMode { id: string; label: string; providers: string[] }
export interface AIControl {
  at: string; current_mode: string; modes: AIMode[];
  recommendation: { mode: string; label: string; reason: string };
  providers: { id: string; label: string; execution: string; billing: string; enabled: boolean; required: boolean;
    status: ProviderState; today: Usage | null; month: Usage | null; quota_note: string;
    performance: { latency: number | null; attempts: number; succeeded: number | null; failed: number | null } }[];
  current_local_model: string | null; models: ModelsResponse['models']; roles: ModelsResponse['roles'];
  memory: ModelsResponse['memory']; servers: ModelsResponse['servers']; budget: BudgetState;
  today: Record<string, Usage>; month: Record<string, Usage>; usage_note: string; signoff_required: boolean;
  execution_today: { execution: string; attempts: number; succeeded: number; failed: number; fallbacks: number; response_ms: number | null }[];
}
export interface AIRun {
  id: string; task_id: string | null; parent_run_id: string | null; escalated_from_run_id: string | null;
  agent_id: string; model_id: string; ai_mode: string; task_type: string; route_reason: string; execution: string;
  status: string; error: string | null; duration_ms: number; prompt_tokens: number | null; completion_tokens: number | null;
  cost_usd: number | null; estimated_cost_usd: number | null; started_at: string; capability: string | null;
  opportunity_id: string | null;
}
export interface AIPlan { workflow: string; preview: boolean; steps: {
  title: string; role: string; task_type: string; local_model: string | null; local_quality_sufficient: boolean | null;
  reason: string; fallback_providers: string[]; execution: string; cloud_cost_note: string;
}[] }
