/**
 * SearchClaw Node.js SDK — Cheap, fast search API for AI agents.
 */

export class SearchClawError extends Error {
  statusCode?: number;
  response?: Record<string, unknown>;

  constructor(message: string, statusCode?: number, response?: Record<string, unknown>) {
    super(message);
    this.name = "SearchClawError";
    this.statusCode = statusCode;
    this.response = response;
  }
}

export class AuthError extends SearchClawError {
  constructor(message: string, statusCode?: number, response?: Record<string, unknown>) {
    super(message, statusCode, response);
    this.name = "AuthError";
  }
}

export class RateLimitError extends SearchClawError {
  retryAfter?: number;

  constructor(message: string, statusCode?: number, response?: Record<string, unknown>, retryAfter?: number) {
    super(message, statusCode, response);
    this.name = "RateLimitError";
    this.retryAfter = retryAfter;
  }
}

export interface SearchClawOptions {
  apiKey: string;
  baseUrl?: string;
  timeout?: number;
}

export interface SearchParams {
  q: string;
  count?: number;
  offset?: number;
  country?: string;
  language?: string;
  safesearch?: number;
  freshness?: string;
  engines?: string;
  format?: string;
}

export interface NewsParams {
  q: string;
  count?: number;
  offset?: number;
  country?: string;
  language?: string;
  safesearch?: number;
  freshness?: string;
}

export interface ImageParams {
  q: string;
  count?: number;
  offset?: number;
  country?: string;
  language?: string;
  safesearch?: number;
}

export interface AiSearchParams {
  q: string;
  count?: number;
  country?: string;
  language?: string;
  freshness?: string;
}

export interface SearchResult {
  title: string;
  url: string;
  snippet: string;
  source: string;
  position: number;
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
  infobox?: {
    title: string;
    content: string;
    url: string;
  };
  suggestions: string[];
  meta: {
    total_results: number;
    cached: boolean;
    response_time_ms: number;
    engines_used: string[];
  };
}

export interface AiSearchResponse {
  query: string;
  context: string;
  results: SearchResult[];
  meta: {
    credits_used: number;
    cached: boolean;
    response_time_ms: number;
  };
}

export interface UsageResponse {
  credits_used: number;
  credits_remaining: number;
  plan: string;
  billing_period_start: string;
  billing_period_end: string;
}

const DEFAULT_BASE_URL = "https://api.searchclaw.dev/v1";
const DEFAULT_TIMEOUT = 30000;

function buildQuery(params: Record<string, unknown>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null);
  if (entries.length === 0) return "";
  return "?" + entries.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join("&");
}

async function handleError(response: Response): Promise<never> {
  let body: Record<string, unknown>;
  try {
    body = await response.json();
  } catch {
    body = { detail: await response.text() };
  }

  const message = (body.detail as string) || `HTTP ${response.status}`;

  if (response.status === 401 || response.status === 403) {
    throw new AuthError(message, response.status, body);
  }
  if (response.status === 429) {
    const retryAfter = response.headers.get("Retry-After");
    throw new RateLimitError(message, 429, body, retryAfter ? parseInt(retryAfter, 10) : undefined);
  }
  throw new SearchClawError(message, response.status, body);
}

export class SearchClaw {
  private apiKey: string;
  private baseUrl: string;
  private timeout: number;

  constructor(options: SearchClawOptions) {
    this.apiKey = options.apiKey;
    this.baseUrl = (options.baseUrl || DEFAULT_BASE_URL).replace(/\/+$/, "");
    this.timeout = options.timeout || DEFAULT_TIMEOUT;
  }

  private async request<T>(path: string, params: Record<string, unknown> = {}): Promise<T> {
    const url = `${this.baseUrl}${path}${buildQuery(params)}`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout);

    try {
      const response = await fetch(url, {
        method: "GET",
        headers: { "X-API-Key": this.apiKey },
        signal: controller.signal,
      });

      if (!response.ok) {
        await handleError(response);
      }

      return (await response.json()) as T;
    } finally {
      clearTimeout(timer);
    }
  }

  async search(q: string, params?: Omit<SearchParams, "q">): Promise<SearchResponse> {
    return this.request<SearchResponse>("/search", { q, ...params });
  }

  async news(q: string, params?: Omit<NewsParams, "q">): Promise<SearchResponse> {
    return this.request<SearchResponse>("/news", { q, ...params });
  }

  async images(q: string, params?: Omit<ImageParams, "q">): Promise<SearchResponse> {
    return this.request<SearchResponse>("/images", { q, ...params });
  }

  async suggest(q: string): Promise<string[]> {
    return this.request<string[]>("/suggest", { q });
  }

  async aiSearch(q: string, params?: Omit<AiSearchParams, "q">): Promise<AiSearchResponse> {
    return this.request<AiSearchResponse>("/search/ai", { q, ...params });
  }

  async usage(): Promise<UsageResponse> {
    return this.request<UsageResponse>("/usage");
  }
}

export default SearchClaw;
