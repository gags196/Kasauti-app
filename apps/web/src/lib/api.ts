/**
 * The single place the web app talks to FastAPI.
 *
 * Response shapes come from `api-types.ts`, generated off the backend's own
 * OpenAPI schema (`pnpm gen:api`) — so a change to a Pydantic response model
 * surfaces here as a type error rather than a runtime surprise.
 */
import type { components, operations } from "./api-types";

type Schemas = components["schemas"];

export type Topic = Schemas["TopicOut"];
export type Ranking = Schemas["RankingOut"];
export type Analysis = Schemas["AnalysisOut"];
export type Note = Schemas["NoteOut"];
export type Question = Schemas["QuestionOut"];
export type SearchHit = Schemas["SearchHitOut"];
export type QuestionOption = Schemas["OptionOut"];
export type RuleStat = Schemas["RuleStatOut"];
export type QuestionLab = Schemas["QuestionLabOut"];
export type LabFiring = Schemas["LabFiringOut"];
export type LabStatement = Schemas["LabStatementOut"];
export type Trends = Schemas["TrendsOut"];
export type TrendCell = Schemas["TrendCellOut"];
export type EraShift = Schemas["EraShiftOut"];
export type Patterns = Schemas["PatternsOut"];
export type PatternHypothesis = Schemas["PatternHypothesisOut"];
export type DepthProfile = Schemas["DepthProfileOut"];
export type Projection = Schemas["ProjectionOut"];
export type BranchCoverage = Schemas["BranchCoverageOut"];
export type Recurrence = Schemas["RecurrenceOut"];
export type Me = Schemas["UserRead"];
export type PracticeSessionSummary = Schemas["SessionOut"];
export type PracticeSessionDetail = Schemas["SessionDetailOut"];
export type PracticeQuestion = Schemas["PracticeQuestionOut"];
export type PracticeOption = Schemas["PracticeOptionOut"];
export type Performance = Schemas["PerformanceOut"];
export type TopicPerformance = Schemas["TopicPerformanceOut"];
export type StartOptions = Schemas["StartOptionsOut"];
export type PracticeMode = "year_paper" | "full_mock" | "topic_drill";

/** The dimensions a trend chart can be drawn over. `format` and `depth` come from the
 * classification pass and are empty until it runs, so the UI offers the two that are
 * derived from the printed page. */
export type TrendDimension = "regex_format" | "archetype" | "format" | "depth";
export type Era = "all" | "recent" | "legacy";

export type RankingWindow = NonNullable<
  operations["rankings_api_v1_pyq_rankings_get"]["parameters"]["query"]
>["window"];
export type Stage = NonNullable<
  NonNullable<
    operations["rankings_api_v1_pyq_rankings_get"]["parameters"]["query"]
  >["stage"]
>;

/** Predicted angles are stored as free-form JSON, so narrow them here. */
export type PredictedAngle = {
  angle_en: string;
  angle_hi: string;
  rationale_en?: string;
};

/** Tables inside a question — "Match List I with List II" and data tables. Stored as
 * loose JSON server-side because the shape varies per question, so narrow it here. */
export type TableCell = { text_en?: string | null; text_hi?: string | null };
export type QuestionTable = {
  caption_en?: string | null;
  caption_hi?: string | null;
  headers: TableCell[];
  rows: TableCell[][];
};

/** One-pager sections are typed at generation time, JSON at rest. */
export type NoteContent = {
  title: string;
  overview: string;
  sections: { heading: string; points: string[] }[];
  keywords: string[];
};

const BASE_URL = process.env.KASAUTI_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly path: string,
    message: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
  }
}

type Query = Record<string, string | number | undefined | null>;

/** Requests carrying a learner's session are never cached: two learners must not share
 * a rendered response, and a stale answer sheet is worse than a slow one. */
type Options = { token?: string | null; method?: string; body?: unknown };

async function request<T>(
  path: string,
  query: Query = {},
  options: Options = {},
): Promise<T> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  }
  const qs = params.toString();
  const url = `${BASE_URL}${path}${qs ? `?${qs}` : ""}`;
  const headers: Record<string, string> = { accept: "application/json" };
  if (options.token) headers.authorization = `Bearer ${options.token}`;
  if (options.body !== undefined) headers["content-type"] = "application/json";

  let response: Response;
  try {
    response = await fetch(url, {
      method: options.method ?? "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      cache: "no-store",
    });
  } catch (cause) {
    throw new ApiError(0, path, `Cannot reach the API at ${BASE_URL}`, { cause });
  }
  if (!response.ok) {
    throw new ApiError(response.status, path, `API ${response.status} on ${path}`);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function get<T>(path: string, query: Query = {}): Promise<T> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  }
  const qs = params.toString();
  const url = `${BASE_URL}${path}${qs ? `?${qs}` : ""}`;

  let response: Response;
  try {
    response = await fetch(url, {
      headers: { accept: "application/json" },
      // PYQ data changes only when the founder publishes; a short revalidate
      // keeps pages fast without serving a stale corpus for long.
      next: { revalidate: 60 },
    });
  } catch (cause) {
    throw new ApiError(0, path, `Cannot reach the API at ${BASE_URL}`, { cause });
  }

  if (!response.ok) {
    throw new ApiError(response.status, path, `API ${response.status} on ${path}`);
  }
  return (await response.json()) as T;
}

/** 404 is a normal answer here: "no analysis generated for this topic yet". */
async function getOrNull<T>(path: string, query: Query = {}): Promise<T | null> {
  try {
    return await get<T>(path, query);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export const api = {
  topics: () => get<Topic[]>("/api/v1/pyq/topics"),

  rankings: (params: { window?: RankingWindow; stage?: Stage; limit?: number }) =>
    get<Ranking[]>("/api/v1/pyq/rankings", {
      window: params.window ?? "all",
      stage: params.stage,
      limit: params.limit ?? 50,
    }),

  analysis: (topicId: number, scope: "prelims" | "mains" | "combined" = "combined") =>
    getOrNull<Analysis>(`/api/v1/pyq/topics/${topicId}/analysis`, { scope }),

  note: (topicId: number) => getOrNull<Note>(`/api/v1/pyq/topics/${topicId}/note`),

  question: (id: number) => getOrNull<Question>(`/api/v1/pyq/questions/${id}`),

  /** Elimination Lab. `era` narrows which years the measured rates are taken over —
   * "recent" is the 2022-onwards exam, where none of the rules survives. */
  eliminationRules: (era: Era = "all") =>
    get<RuleStat[]>("/api/v1/pyq/elimination/rules", { era }),

  questionLab: (id: number, era: Era = "all") =>
    getOrNull<QuestionLab>(`/api/v1/pyq/questions/${id}/elimination`, { era }),

  trends: (params: { dimension?: TrendDimension; stage?: Stage; topic_path?: string }) =>
    get<Trends>("/api/v1/pyq/trends", {
      dimension: params.dimension ?? "regex_format",
      stage: params.stage,
      topic_path: params.topic_path,
    }),

  patterns: (era: Era = "all") => get<Patterns>("/api/v1/pyq/patterns", { era }),

  recurrence: (params: { stage?: Stage; threshold?: number } = {}) =>
    get<Recurrence>("/api/v1/pyq/recurrence", {
      stage: params.stage,
      threshold: params.threshold,
    }),

  topicProfile: (topicId: number, stage?: Stage) =>
    getOrNull<DepthProfile>(`/api/v1/pyq/topics/${topicId}/profile`, { stage }),

  topicProjection: (topicId: number, stage?: Stage) =>
    getOrNull<Projection>(`/api/v1/pyq/topics/${topicId}/projection`, { stage }),

  // ---- learner account + practice ----
  // Every call below carries the session token explicitly. Nothing reads the cookie
  // here: `lib/session.ts` is server-only, and threading the token through keeps this
  // module importable from anywhere.

  register: (body: { email: string; password: string; name?: string }) =>
    request<Me>("/api/v1/auth/register", {}, { method: "POST", body }),

  /** The token endpoint speaks form-encoding (OAuth2 password flow), not JSON. */
  login: async (email: string, password: string): Promise<string> => {
    const response = await fetch(`${BASE_URL}/api/v1/auth/jwt/login`, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ username: email, password }),
      cache: "no-store",
    }).catch((cause) => {
      throw new ApiError(0, "/api/v1/auth/jwt/login", "Cannot reach the API", { cause });
    });
    if (!response.ok) {
      throw new ApiError(response.status, "/api/v1/auth/jwt/login", "Login failed");
    }
    return ((await response.json()) as { access_token: string }).access_token;
  },

  me: (token: string) => request<Me>("/api/v1/users/me", {}, { token }),

  practiceOptions: () => request<StartOptions>("/api/v1/practice/options"),

  startSession: (
    token: string,
    // Typed off the generated schema rather than restated here, so a new field on the
    // API (paper_code was one) is a compile error at the call site, not a silent drop.
    body: Schemas["StartSessionIn"],
  ) =>
    request<PracticeSessionSummary>(
      "/api/v1/practice/sessions",
      {},
      { token, method: "POST", body },
    ),

  practiceSession: (token: string, id: string) =>
    request<PracticeSessionDetail>(`/api/v1/practice/sessions/${id}`, {}, { token }),

  practiceSessions: (token: string) =>
    request<PracticeSessionSummary[]>("/api/v1/practice/sessions", {}, { token }),

  saveAnswer: (
    token: string,
    sessionId: string,
    questionId: number,
    body: { selected_label: string | null; seconds_taken?: number },
  ) =>
    request<void>(
      `/api/v1/practice/sessions/${sessionId}/answers/${questionId}`,
      {},
      { token, method: "PUT", body },
    ),

  submitSession: (token: string, id: string) =>
    request<PracticeSessionSummary>(
      `/api/v1/practice/sessions/${id}/submit`,
      {},
      { token, method: "POST" },
    ),

  performance: (token: string) =>
    request<Performance>("/api/v1/practice/performance", {}, { token }),

  search: (params: {
    query: string;
    topic_path?: string;
    year_from?: number;
    year_to?: number;
    k?: number;
  }) => get<SearchHit[]>("/api/v1/pyq/search", { ...params, k: params.k ?? 20 }),
};
