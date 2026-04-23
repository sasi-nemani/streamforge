import { useState, useEffect } from 'react'
import { api } from '../lib/api'
import type { Source, MetricsSummary, DriftAlert, PiiSummary, HealthStatus, Connector } from '../lib/types'

interface DataState {
  sources: Source[]
  connectors: Connector[]
  metrics: MetricsSummary | null
  drifts: DriftAlert[]
  pii: PiiSummary | null
  health: HealthStatus | null
  loading: boolean
  error: string | null
}

export function useData() {
  const [state, setState] = useState<DataState>({
    sources: [],
    connectors: [],
    metrics: null,
    drifts: [],
    pii: null,
    health: null,
    loading: true,
    error: null,
  })

  useEffect(() => {
    async function load() {
      try {
        const [sources, connectors, metrics, drifts, pii, health] = await Promise.all([
          api.getSources(),
          api.getConnectors(),
          api.getMetrics(),
          api.getActiveDrifts(),
          api.getPiiSummary(),
          api.getHealth(),
        ])
        setState({ sources, connectors, metrics, drifts, pii, health, loading: false, error: null })
      } catch (e) {
        setState(s => ({ ...s, loading: false, error: e instanceof Error ? e.message : 'Unknown error' }))
      }
    }
    load()
    const interval = setInterval(load, 5000)
    return () => clearInterval(interval)
  }, [])

  return state
}
