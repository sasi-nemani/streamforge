import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { Layout } from '../components/Layout'
import { api } from '../lib/api'
import type { SearchResult } from '../lib/types'

export function Search() {
  const [query, setQuery] = useState('')
  const [typeFilter, setTypeFilter] = useState<string>('')
  const [piiOnly, setPiiOnly] = useState(false)
  const [results, setResults] = useState<SearchResult[]>([])
  const [types, setTypes] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(false)

  useEffect(() => {
    api.getFieldTypes().then((r) => setTypes(r.types))
  }, [])

  const handleSearch = async () => {
    setLoading(true)
    setSearched(true)
    const res = await api.searchFields(query, typeFilter || undefined, piiOnly)
    setResults(res.results)
    setLoading(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSearch()
  }

  return (
    <Layout>
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-gray-900 mb-2">Field Search</h1>
        <p className="text-sm text-gray-500">
          Search for fields across all connected streams
        </p>
      </div>

      <div className="bg-white rounded-lg border border-gray-200 p-6 mb-6">
        <div className="flex gap-4 items-end">
          <div className="flex-1">
            <label className="block text-xs font-medium text-gray-500 mb-1">
              Field name
            </label>
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="e.g. user_id, email, timestamp"
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-1 focus:ring-gray-400"
            />
          </div>

          <div className="w-40">
            <label className="block text-xs font-medium text-gray-500 mb-1">
              Type
            </label>
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-1 focus:ring-gray-400"
            >
              <option value="">All types</option>
              {types.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={piiOnly}
              onChange={(e) => setPiiOnly(e.target.checked)}
              className="rounded border-gray-300"
            />
            PII only
          </label>

          <button
            onClick={handleSearch}
            className="px-4 py-2 bg-gray-900 text-white rounded-md text-sm font-medium hover:bg-gray-800"
          >
            Search
          </button>
        </div>
      </div>

      {loading && (
        <div className="text-center py-8 text-gray-500">Searching...</div>
      )}

      {!loading && searched && results.length === 0 && (
        <div className="text-center py-8 text-gray-500">No fields found</div>
      )}

      {!loading && results.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200">
          <div className="px-6 py-3 border-b border-gray-100">
            <span className="text-sm text-gray-500">{results.length} fields found</span>
          </div>
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-100 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                <th className="px-6 py-3">Field Path</th>
                <th className="px-6 py-3">Stream</th>
                <th className="px-6 py-3">Type</th>
                <th className="px-6 py-3">Presence</th>
                <th className="px-6 py-3">PII</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {results.map((r, i) => (
                <tr key={i} className="hover:bg-gray-50">
                  <td className="px-6 py-4 font-mono text-sm">{r.path}</td>
                  <td className="px-6 py-4">
                    <Link
                      to={`/stream/${r.stream}`}
                      className="text-sm text-blue-600 hover:underline"
                    >
                      {r.stream}
                    </Link>
                  </td>
                  <td className="px-6 py-4">
                    <span className="px-2 py-1 bg-gray-100 rounded text-xs font-mono">
                      {r.type}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-600">
                    {(r.presence_rate * 100).toFixed(0)}%
                  </td>
                  <td className="px-6 py-4">
                    {r.pii.length > 0 && (
                      <div className="flex gap-1">
                        {r.pii.map((p) => (
                          <span
                            key={p}
                            className="px-2 py-0.5 bg-red-100 text-red-700 rounded text-xs"
                          >
                            {p}
                          </span>
                        ))}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Layout>
  )
}
