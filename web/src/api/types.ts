// Shapes of the backend API (src/api/routes); only the fields the web UI uses.

export type Role = "admin" | "editor" | "viewer" | "guest";

export interface TokenResponse {
  access_token: string;
  refresh_token?: string | null;
  role: Role;
  username: string;
  expires_in: number;
  must_change_password?: boolean;
}

export interface UserProfile {
  username: string;
  role: Role;
  disabled?: boolean;
  created_at?: string | null;
  must_change_password?: boolean;
  groups: string[];
  /** unit (faculty, directorate), program, level; agents answer for them */
  profile?: Profile;
}

export interface Profile {
  unit?: string;
  program?: string;
  level?: string;
}

export interface Evidence {
  text: string;
  citation: string;
}

export interface Source {
  source: string;
  chunk_index?: number;
  content?: string;
  article?: string;
  page?: number;
  page_end?: number;
  reranker_score?: number;
  distance?: number;
  evidence?: Evidence[];
  used?: boolean;
}

export type VerificationLevel = "verified" | "partial" | "unverified";

export interface Verification {
  level?: VerificationLevel;
  issues?: string[];
}

export interface TraceEntry {
  agent?: string;
  display_name?: string;
  action?: string;
  status?: string;
  duration_ms?: number;
  search_query?: string;
  sql?: string;
  tools_called?: string[];
  from_agent?: string;
  target_agent?: string;
  combined_agents?: string[];
  plan?: { agent: string; question: string; uses?: number[] }[];
}

/** A question the assistant asked back, with answers to pick. */
export interface Clarification {
  question: string;
  options: string[];
}

export interface QueryResult {
  answer: string;
  sources: Source[];
  active_agent: string;
  agents?: string[];
  agent_trace?: TraceEntry[];
  hallucination_grade?: string;
  is_refined?: boolean;
  verification?: Verification;
  clarification?: Clarification | null;
}

/** One line of /api/v1/query-stream (NDJSON). */
export type StreamEvent =
  | { type: "status"; message: string; node?: string }
  | { type: "agent_selected"; agent: string; display_name?: string; reason?: string }
  | { type: "plan"; steps: { agent: string; question: string }[] }
  | { type: "handoff"; from: string; to: string; reason?: string }
  | { type: "progress"; agent: string; stage: string }
  | { type: "sources"; sources: Source[] }
  | { type: "error"; message: string; code?: "busy" }
  | ({ type: "done" } & QueryResult);

export interface AgentInfo {
  name: string;
  display_name?: string;
  description?: string;
}

export interface Stats {
  llm_model?: string;
  router_model?: string;
  grader_model?: string;
  llm_status?: string;
  device?: string;
  embedding_model?: string;
  total_documents?: number;
  total_chunks?: number;
}

export interface DocumentInfo {
  filename: string;
  size_kb: number;
  chunk_count: number;
  modified_at: string;
  groups: string[];
}

export type RequestStatus = "open" | "in_progress" | "resolved" | "rejected" | "cancelled";

export interface ServiceRequest {
  id: number;
  created_at: string;
  updated_at: string;
  username: string;
  category: string;
  title: string;
  description: string;
  status: RequestStatus;
  resolution_note: string;
  updated_by?: string | null;
}

export interface CustomAgent {
  name: string;
  display_name: string;
  description: string;
  instructions: string;
  tools: string[];
  enabled: boolean;
  available?: boolean;
  created_by?: string;
  updated_at?: string;
}

export interface AgentTool {
  name: string;
  label: string;
  description: string;
  available: boolean;
}

export interface AuditEntry {
  id?: number;
  timestamp: string;
  username: string;
  role?: string;
  action: string;
  detail?: string;
  status: string;
  ip_address?: string;
  duration_ms?: number;
  reason?: string;
  /** Review items: the question text ("" when questions are not stored) */
  question?: string;
}

export interface FaqEntry {
  id: string;
  question: string;
  answer: string;
  groups: string[];
  author: string;
  created_at: string;
  updated_at?: string;
  asked: { username: string; question: string }[];
}

/** A staff answer to a question the user asked. */
export interface FaqNotice {
  id: string;
  question: string;
  answer: string;
  updated_at: string;
}

export interface AgentStat {
  agent: string;
  questions: number;
  warnings: number;
  errors: number;
  positive: number;
  negative: number;
  median_ms: number;
  p90_ms: number;
  warning_rate: number;
  error_rate: number;
}

export interface Backup {
  name: string;
  type: "full" | "vector_db";
  created_at: string;
}
