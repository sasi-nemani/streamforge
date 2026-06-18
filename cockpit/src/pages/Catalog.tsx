import { useState, useEffect, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { Layout } from '../components/Layout'
import { api } from '../lib/api'
import type { SearchResult, StreamDetail, FieldDetail } from '../lib/types'

interface EnrichedField extends SearchResult {
  confidence?: number
  sample_values?: unknown[]
  enum_values?: { value: string; count: number }[] | null
}

function TypeBadge({ type }: { type: string }) {
  const colors: Record<string, string> = {
    string: 'bg-slate-100 text-slate-700',
    uuid: 'bg-violet-100 text-violet-700',
    email: 'bg-blue-100 text-blue-700',
    timestamp_epoch_ms: 'bg-amber-100 text-amber-700',
    object: 'bg-cyan-100 text-cyan-700',
    mixed: 'bg-orange-100 text-orange-700',
    integer: 'bg-emerald-100 text-emerald-700',
    boolean: 'bg-pink-100 text-pink-700',
  }
  return (
    <span className={`px-1.5 py-0.5 rounded text-xs font-mono ${colors[type] || 'bg-gray-100 text-gray-600'}`}>
      {type}
    </span>
  )
}

function ConfidenceDot({ value }: { value: number }) {
  const color = value >= 0.9 ? 'bg-green-500' : value >= 0.7 ? 'bg-yellow-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-1">
      <span className={`w-2 h-2 rounded-full ${color}`} />
      <span className="text-xs text-gray-500">{(value * 100).toFixed(0)}%</span>
    </div>
  )
}

function FieldRow({ field, expanded, onToggle }: { field: EnrichedField; expanded: boolean; onToggle: () => void }) {
  const hasPii = field.pii.length > 0

  return (
    <div className={`border-b border-gray-100 ${hasPii ? 'bg-red-50/30' : ''}`}>
      <div
        className="flex items-center gap-4 px-4 py-3 cursor-pointer hover:bg-gray-50"
        onClick={onToggle}
      >
        <div className="w-6 text-gray-400 text-xs">{expanded ? '▼' : '▶'}</div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm font-medium truncate">{field.path}</span>
            {hasPii && (
              <span className="px-1.5 py-0.5 bg-red-100 text-red-700 rounded text-xs font-medium">
                PII
              </span>
            )}
            {field.required && (
              <span className="px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded text-xs">
                req
              </span>
            )}
          </div>
        </div>

        <div className="w-24">
          <TypeBadge type={field.type} />
        </div>

        <div className="w-20">
          <Link
            to={`/stream/${field.stream}`}
            className="text-xs text-gray-500 hover:text-blue-600 hover:underline"
            onClick={(e) => e.stopPropagation()}
          >
            {field.stream}
          </Link>
        </div>

        <div className="w-16 text-right">
          <span className="text-xs text-gray-500">{(field.presence_rate * 100).toFixed(0)}%</span>
        </div>

        <div className="w-16">
          <ConfidenceDot value={field.confidence || 1} />
        </div>
      </div>

      {expanded && (
        <div className="px-4 pb-4 pl-14 space-y-3 bg-gray-50/50">
          {field.pii.length > 0 && (
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-gray-500 w-20">PII Type</span>
              <div className="flex gap-1">
                {field.pii.map((p) => (
                  <span key={p} className="px-2 py-0.5 bg-red-100 text-red-700 rounded text-xs">
                    {p}
                  </span>
                ))}
              </div>
            </div>
          )}

          {field.sample_values && field.sample_values.length > 0 && (
            <div className="flex items-start gap-2">
              <span className="text-xs font-medium text-gray-500 w-20 pt-0.5">Samples</span>
              <div className="flex flex-wrap gap-1.5">
                {field.sample_values.slice(0, 5).map((v, i) => (
                  <span
                    key={i}
                    className="px-2 py-0.5 bg-white border border-gray-200 rounded text-xs font-mono truncate max-w-48"
                  >
                    {typeof v === 'object' ? JSON.stringify(v).slice(0, 40) : String(v).slice(0, 40)}
                  </span>
                ))}
              </div>
            </div>
          )}

          {field.enum_values && field.enum_values.length > 0 && (
            <div className="flex items-start gap-2">
              <span className="text-xs font-medium text-gray-500 w-20 pt-0.5">Enums</span>
              <div className="flex flex-wrap gap-1.5">
                {field.enum_values.slice(0, 8).map((e) => (
                  <span
                    key={e.value}
                    className="px-2 py-0.5 bg-purple-50 border border-purple-200 rounded text-xs"
                  >
                    {e.value} <span className="text-purple-400">({e.count})</span>
                  </span>
                ))}
                {field.enum_values.length > 8 && (
                  <span className="text-xs text-gray-400">+{field.enum_values.length - 8}</span>
                )}
              </div>
            </div>
          )}

          {field.notes && (
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-gray-500 w-20">Notes</span>
              <span className="text-xs text-gray-600">{field.notes}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function Catalog() {
  const [fields, setFields] = useState<EnrichedField[]>([])
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [piiFilter, setPiiFilter] = useState<'all' | 'pii' | 'clean'>('all')
  const [types, setTypes] = useState<string[]>([])
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set())

  useEffect(() => {
    Promise.all([
      api.searchFields(''),
      api.getFieldTypes(),
    ]).then(async ([searchRes, typesRes]) => {
      setTypes(typesRes.types)

      // Fetch stream details for enrichment
      const streams = [...new Set(searchRes.results.map((r) => r.stream))]
      const details: Record<string, StreamDetail> = {}
      await Promise.all(
        streams.map(async (s) => {
          try {
            details[s] = await api.getStream(s)
          } catch {
            /* stream detail enrichment is best-effort */
          }
        })
      )
      // Enrich fields with sample values and enums
      const enriched = searchRes.results.map((f) => {
        const streamDetail = details[f.stream]
        const fieldDetail = streamDetail?.fields?.find((fd: FieldDetail) => fd.path === f.path)
        return {
          ...f,
          confidence: fieldDetail?.confidence || 1,
          sample_values: fieldDetail?.sample_values || [],
          enum_values: fieldDetail?.enum_values || null,
        }
      })
      setFields(enriched)
      setLoading(false)
    })
  }, [])

  const filteredFields = useMemo(() => {
    return fields.filter((f) => {
      if (query && !f.path.toLowerCase().includes(query.toLowerCase())) return false
      if (typeFilter && f.type !== typeFilter) return false
      if (piiFilter === 'pii' && f.pii.length === 0) return false
      if (piiFilter === 'clean' && f.pii.length > 0) return false
      return true
    })
  }, [fields, query, typeFilter, piiFilter])

  const stats = useMemo(() => {
    const piiCount = fields.filter((f) => f.pii.length > 0).length
    const streamCount = new Set(fields.map((f) => f.stream)).size
    return { total: fields.length, pii: piiCount, streams: streamCount }
  }, [fields])

  const toggleExpand = (path: string, stream: string) => {
    const key = `${stream}:${path}`
    setExpandedPaths((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  if (loading) {
    return (
      <Layout>
        <div className="flex items-center justify-center h-64 text-gray-500">
          Loading field catalog...
        </div>
      </Layout>
    )
  }

  return (
    <Layout>
      <div className="mb-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">Field Catalog</h1>
            <p className="text-sm text-gray-500 mt-1">
              {stats.total} fields across {stats.streams} streams • {stats.pii} PII fields
            </p>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-green-500" />
              <span className="text-gray-500">High confidence</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-yellow-500" />
              <span className="text-gray-500">Medium</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-red-500" />
              <span className="text-gray-500">Low</span>
            </div>
          </div>
        </div>
      </div>

      <div className="bg-white rounded-lg border border-gray-200 mb-4">
        <div className="flex items-center gap-4 p-4 border-b border-gray-100">
          <div className="flex-1">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter fields..."
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-1 focus:ring-gray-400"
            />
          </div>
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-1 focus:ring-gray-400"
          >
            <option value="">All types</option>
            {types.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
          <div className="flex border border-gray-300 rounded-md overflow-hidden">
            {(['all', 'pii', 'clean'] as const).map((v) => (
              <button
                key={v}
                onClick={() => setPiiFilter(v)}
                className={`px-3 py-2 text-sm ${
                  piiFilter === v
                    ? 'bg-gray-900 text-white'
                    : 'bg-white text-gray-600 hover:bg-gray-50'
                }`}
              >
                {v === 'all' ? 'All' : v === 'pii' ? 'PII Only' : 'Clean'}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-4 px-4 py-2 bg-gray-50 border-b border-gray-100 text-xs font-medium text-gray-500 uppercase tracking-wider">
          <div className="w-6"></div>
          <div className="flex-1">Field Path</div>
          <div className="w-24">Type</div>
          <div className="w-20">Stream</div>
          <div className="w-16 text-right">Present</div>
          <div className="w-16">Confidence</div>
        </div>

        <div className="max-h-[calc(100vh-320px)] overflow-y-auto">
          {filteredFields.map((field) => (
            <FieldRow
              key={`${field.stream}:${field.path}`}
              field={field}
              expanded={expandedPaths.has(`${field.stream}:${field.path}`)}
              onToggle={() => toggleExpand(field.path, field.stream)}
            />
          ))}
        </div>

        {filteredFields.length === 0 && (
          <div className="text-center py-12 text-gray-500">No fields match filters</div>
        )}

        <div className="px-4 py-3 border-t border-gray-100 bg-gray-50 text-xs text-gray-500">
          Showing {filteredFields.length} of {fields.length} fields
        </div>
      </div>
    </Layout>
  )
}
