import type { Source, Connector, MetricsSummary, DriftAlert, PiiSummary, HealthStatus, StreamDetail, SearchResponse } from './types'

const API_BASE = '/api'

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) {
    throw new Error(`API error: ${res.status}`)
  }
  return res.json()
}

export const api = {
  getSources: () => fetchJson<Source[]>('/sources'),
  getConnectors: () => fetchJson<Connector[]>('/connectors'),
  getMetrics: () => fetchJson<MetricsSummary>('/metrics/summary'),
  getActiveDrifts: () => fetchJson<DriftAlert[]>('/drift/active'),
  getPiiSummary: () => fetchJson<PiiSummary>('/pii/summary'),
  getHealth: () => fetchJson<HealthStatus>('/health'),
  getStream: (name: string) => fetchJson<StreamDetail>(`/streams/${name}`),
  searchFields: (q: string, type?: string, piiOnly?: boolean) => {
    const params = new URLSearchParams()
    if (q) params.set('q', q)
    if (type) params.set('type', type)
    if (piiOnly) params.set('pii_only', 'true')
    return fetchJson<SearchResponse>(`/search?${params}`)
  },
  getFieldTypes: () => fetchJson<{ types: string[] }>('/search/types'),
}
