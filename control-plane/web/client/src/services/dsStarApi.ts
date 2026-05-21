import { getGlobalApiKey } from './api';
import { reasonersApi } from './reasonersApi';
import { getWorkflowDAGLightweight } from './workflowsApi';
import type { AsyncExecuteResponse, ExecutionStatusResponse } from '../types/execution';
import type { WorkflowDAGLightweightResponse } from '../types/workflows';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/ui/v1';

function authHeaders(extra?: HeadersInit): Headers {
  const h = new Headers(extra || {});
  const key = getGlobalApiKey();
  if (key) h.set('X-API-Key', key);
  return h;
}

export interface UploadResponse {
  filename: string;
  size: number;
}

export interface DataFile {
  name: string;
  size: number;
}

export interface DSStarPipelineRequest {
  query: string;
  data_files: string[];
  max_iterations?: number;
  guidelines?: string;
  data_dir?: string;
  num_strategies?: number;
  strategy_max_iters?: number;
  num_code_variants?: number;
  num_verifiers?: number;
}

export interface ChartData {
  name: string;
  data: string;
}

export interface DSStarPipelineResult {
  final_answer?: string;
  final_code?: string;
  iterations?: number;
  verified?: boolean;
  run_score?: number;
  plans?: string[];
  charts?: ChartData[];
  strategies_explored?: number;
  total_ai_calls?: number;
  elapsed_seconds?: number;
  failure_type?: string;
}

const AGENT_ID = 'ds-star';
const REASONER_ID = 'ds-star.orchestration_run_pipeline';

export const dsStarApi = {
  uploadFile: async (file: File): Promise<UploadResponse> => {
    const form = new FormData();
    form.append('file', file);
    const resp = await fetch(`${API_BASE_URL}/agents/${AGENT_ID}/upload`, {
      method: 'POST',
      headers: authHeaders(),
      body: form,
    });
    if (!resp.ok) {
      const msg = await resp.text().catch(() => resp.statusText);
      throw new Error(`Upload failed: ${msg}`);
    }
    return resp.json();
  },

  listFiles: async (): Promise<DataFile[]> => {
    const resp = await fetch(`${API_BASE_URL}/agents/${AGENT_ID}/files`, {
      headers: authHeaders(),
    });
    if (!resp.ok) return [];
    const data = await resp.json();
    return data.files ?? [];
  },

  executePipeline: async (req: DSStarPipelineRequest): Promise<AsyncExecuteResponse> => {
    return reasonersApi.executeReasonerAsync(REASONER_ID, { input: req });
  },

  getExecutionStatus: async (executionId: string): Promise<ExecutionStatusResponse> => {
    return reasonersApi.getExecutionStatus(executionId);
  },

  getWorkflowDAG: async (runId: string): Promise<WorkflowDAGLightweightResponse> => {
    return getWorkflowDAGLightweight(runId);
  },

};
