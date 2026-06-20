import type { AuthSessionResponse, NotificationChannel, NotificationChannelsResponse, NotificationRule, NotificationRulesResponse, OpenRouterModelsResponse, PricingEntry, PricingResponse, StatusResponse, SyncOpenRouterResponse, UsageAnalysisResponse, UsageEventFilterOptionsResponse, UsedModelsResponse, UsageCredentialsResponse, UsageEventsResponse, UsageOverviewResponse } from './types'

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

const APP_BASE_PATH_PLACEHOLDER = '__APP_BASE_PATH__'

declare global {
  interface Window {
    __APP_BASE_PATH__?: string
  }
}

function normalizeBasePath(basePath: string | undefined): string {
  if (!basePath || basePath === '/' || basePath === APP_BASE_PATH_PLACEHOLDER) {
    return ''
  }
  return basePath.endsWith('/') ? basePath.slice(0, -1) : basePath
}

export function apiPath(path: string): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return `${normalizeBasePath(window.__APP_BASE_PATH__)}/api/v1${normalizedPath}`
}

async function parseApiError(response: Response, fallback: string): Promise<never> {
  let message = fallback
  try {
    const payload = await response.json() as { error?: string }
    if (payload.error) {
      message = payload.error
    }
  } catch {
    // ignore invalid error payloads
  }
  throw new ApiError(message, response.status)
}

async function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  return fetch(input, {
    credentials: 'include',
    ...init,
  })
}

export async function getSession(signal?: AbortSignal): Promise<AuthSessionResponse> {
  const response = await apiFetch(apiPath('/auth/session'), { signal })
  if (!response.ok) {
    await parseApiError(response, `Failed to load auth session: ${response.status}`)
  }
  return response.json()
}

export async function login(password: string): Promise<void> {
  const response = await apiFetch(apiPath('/auth/login'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ password }),
  })
  if (!response.ok) {
    await parseApiError(response, `Failed to login: ${response.status}`)
  }
}

export async function fetchUsageOverview(range: string, start?: string, end?: string, signal?: AbortSignal): Promise<UsageOverviewResponse> {
  const params = new URLSearchParams()
  params.set('range', range)
  if (start) {
    params.set('start', start)
  }
  if (end) {
    params.set('end', end)
  }
  const query = params.toString()
  const response = await apiFetch(`${apiPath('/usage/overview')}${query ? `?${query}` : ''}`, { signal })
  if (!response.ok) {
    await parseApiError(response, `Failed to load usage overview: ${response.status}`)
  }
  return response.json()
}

export interface FetchUsageEventsOptions {
  page?: number
  pageSize?: number
  model?: string
  source?: string
  result?: string
}

export async function fetchUsageEventFilterOptions(range: string, start?: string, end?: string, signal?: AbortSignal): Promise<UsageEventFilterOptionsResponse> {
  const params = new URLSearchParams()
  params.set('range', range)
  if (start) {
    params.set('start', start)
  }
  if (end) {
    params.set('end', end)
  }
  const query = params.toString()
  const response = await apiFetch(`${apiPath('/usage/events/filters')}${query ? `?${query}` : ''}`, { signal })
  if (!response.ok) {
    await parseApiError(response, `Failed to load usage event filters: ${response.status}`)
  }
  return response.json()
}

export async function fetchUsageEvents(range: string, start?: string, end?: string, signal?: AbortSignal, options?: FetchUsageEventsOptions): Promise<UsageEventsResponse> {
  const params = new URLSearchParams()
  params.set('range', range)
  if (start) {
    params.set('start', start)
  }
  if (end) {
    params.set('end', end)
  }
  if (typeof options?.page === 'number' && Number.isFinite(options.page) && options.page > 0) {
    params.set('page', String(Math.floor(options.page)))
  }
  if (typeof options?.pageSize === 'number' && Number.isFinite(options.pageSize) && options.pageSize > 0) {
    params.set('page_size', String(Math.floor(options.pageSize)))
  }
  const model = options?.model?.trim()
  if (model) {
    params.set('model', model)
  }
  const source = options?.source?.trim()
  if (source) {
    params.set('source', source)
  }
  const result = options?.result?.trim()
  if (result) {
    params.set('result', result)
  }
  const query = params.toString()
  const response = await apiFetch(`${apiPath('/usage/events')}${query ? `?${query}` : ''}`, { signal })
  if (!response.ok) {
    await parseApiError(response, `Failed to load usage events: ${response.status}`)
  }
  return response.json()
}

export async function fetchUsageCredentials(range: string, start?: string, end?: string, signal?: AbortSignal): Promise<UsageCredentialsResponse> {
  const params = new URLSearchParams()
  params.set('range', range)
  if (start) {
    params.set('start', start)
  }
  if (end) {
    params.set('end', end)
  }
  const query = params.toString()
  const response = await apiFetch(`${apiPath('/usage/credentials')}${query ? `?${query}` : ''}`, { signal })
  if (!response.ok) {
    await parseApiError(response, `Failed to load usage credentials: ${response.status}`)
  }
  return response.json()
}

export async function fetchUsageAnalysis(range: string, start?: string, end?: string, signal?: AbortSignal): Promise<UsageAnalysisResponse> {
  const params = new URLSearchParams()
  params.set('range', range)
  if (start) {
    params.set('start', start)
  }
  if (end) {
    params.set('end', end)
  }
  const query = params.toString()
  const response = await apiFetch(`${apiPath('/usage/analysis')}${query ? `?${query}` : ''}`, { signal })
  if (!response.ok) {
    await parseApiError(response, `Failed to load usage analysis: ${response.status}`)
  }
  return response.json()
}

export async function fetchUsedModels(signal?: AbortSignal): Promise<UsedModelsResponse> {
  const response = await apiFetch(apiPath('/models/used'), { signal })
  if (!response.ok) {
    await parseApiError(response, `Failed to load used models: ${response.status}`)
  }
  return response.json()
}

export async function fetchStatus(signal?: AbortSignal): Promise<StatusResponse> {
  const response = await apiFetch(apiPath('/status'), { signal })
  if (!response.ok) {
    await parseApiError(response, `Failed to load status: ${response.status}`)
  }
  return response.json()
}

export async function triggerSync(signal?: AbortSignal): Promise<StatusResponse> {
  const response = await apiFetch(apiPath('/sync'), { method: 'POST', signal })
  if (!response.ok) {
    await parseApiError(response, `Failed to start sync: ${response.status}`)
  }
  return response.json()
}

export async function fetchPricing(signal?: AbortSignal): Promise<PricingResponse> {
  const response = await apiFetch(apiPath('/pricing'), { signal })
  if (!response.ok) {
    await parseApiError(response, `Failed to load pricing: ${response.status}`)
  }
  return response.json()
}

export async function updatePricing(model: string, pricing: Omit<PricingEntry, 'model'>): Promise<PricingEntry> {
  const response = await apiFetch(apiPath('/pricing'), {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ model, ...pricing }),
  })
  if (!response.ok) {
    await parseApiError(response, `Failed to update pricing: ${response.status}`)
  }
  return response.json()
}

export async function deletePricing(model: string): Promise<void> {
  const params = new URLSearchParams({ model })
  const response = await apiFetch(`${apiPath('/pricing')}?${params.toString()}`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    await parseApiError(response, `Failed to delete pricing: ${response.status}`)
  }
}

export async function fetchOpenRouterModels(signal?: AbortSignal): Promise<OpenRouterModelsResponse> {
  const response = await apiFetch(apiPath('/pricing/openrouter-models'), { signal })
  if (!response.ok) {
    await parseApiError(response, `Failed to fetch OpenRouter models: ${response.status}`)
  }
  return response.json()
}

export async function syncOpenRouterPrices(): Promise<SyncOpenRouterResponse> {
  const response = await apiFetch(apiPath('/pricing/sync-openrouter'), {
    method: 'POST',
  })
  if (!response.ok) {
    await parseApiError(response, `Failed to sync OpenRouter prices: ${response.status}`)
  }
  return response.json()
}

  // ── Notification Channels ───────────────────────────────────────────────

  export async function fetchNotificationChannels(signal?: AbortSignal): Promise<NotificationChannelsResponse> {
    const response = await apiFetch(apiPath('/notification/channels'), { signal })
    if (!response.ok) {
      await parseApiError(response, `Failed to load notification channels: ${response.status}`)
    }
    return response.json()
  }

  export async function createNotificationChannel(data: {
    name: string
    channel_type: string
    config: { webhook_url: string }
    enabled?: boolean
  }): Promise<NotificationChannel> {
    const response = await apiFetch(apiPath('/notification/channels'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!response.ok) {
      await parseApiError(response, `Failed to create notification channel: ${response.status}`)
    }
    return response.json()
  }

  export async function updateNotificationChannel(
    id: number,
    data: { name?: string; channel_type?: string; config?: { webhook_url: string }; enabled?: boolean }
  ): Promise<NotificationChannel> {
    const response = await apiFetch(apiPath(`/notification/channels/${id}`), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!response.ok) {
      await parseApiError(response, `Failed to update notification channel: ${response.status}`)
    }
    return response.json()
  }

  export async function deleteNotificationChannel(id: number): Promise<void> {
    const response = await apiFetch(apiPath(`/notification/channels/${id}`), {
      method: 'DELETE',
    })
    if (!response.ok) {
      await parseApiError(response, `Failed to delete notification channel: ${response.status}`)
    }
  }

  export async function testNotificationWebhook(id: number): Promise<{ status: string }> {
    const response = await apiFetch(apiPath(`/notification/channels/${id}/test`), {
      method: 'POST',
    })
    if (!response.ok) {
      await parseApiError(response, `Failed to test notification webhook: ${response.status}`)
    }
    return response.json()
  }

  // ── Notification Rules ───────────────────────────────────────────────────

  export async function fetchNotificationRules(signal?: AbortSignal): Promise<NotificationRulesResponse> {
    const response = await apiFetch(apiPath('/notification/rules'), { signal })
    if (!response.ok) {
      await parseApiError(response, `Failed to load notification rules: ${response.status}`)
    }
    return response.json()
  }

  export async function createNotificationRule(data: {
    name: string
    channel_id: number
    rule_type: string
    config: { threshold?: number; window_minutes: number }
    enabled?: boolean
    cooldown_minutes?: number
  }): Promise<NotificationRule> {
    const response = await apiFetch(apiPath('/notification/rules'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!response.ok) {
      await parseApiError(response, `Failed to create notification rule: ${response.status}`)
    }
    return response.json()
  }

  export async function updateNotificationRule(
    id: number,
    data: { name?: string; channel_id?: number; rule_type?: string; config?: object; enabled?: boolean; cooldown_minutes?: number }
  ): Promise<NotificationRule> {
    const response = await apiFetch(apiPath(`/notification/rules/${id}`), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!response.ok) {
      await parseApiError(response, `Failed to update notification rule: ${response.status}`)
    }
    return response.json()
  }

  export async function deleteNotificationRule(id: number): Promise<void> {
    const response = await apiFetch(apiPath(`/notification/rules/${id}`), {
      method: 'DELETE',
    })
    if (!response.ok) {
      await parseApiError(response, `Failed to delete notification rule: ${response.status}`)
    }
  }
