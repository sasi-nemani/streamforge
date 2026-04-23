import { Link } from 'react-router-dom'
import type { Source } from '../lib/types'

interface SourcesTableProps {
  sources: Source[]
}

function StatusDot({ status }: { status: Source['status'] }) {
  const colors = {
    active: 'bg-green-500',
    inactive: 'bg-gray-400',
    error: 'bg-red-500',
    unknown: 'bg-yellow-500',
  }
  return <span className={`w-2 h-2 rounded-full ${colors[status]}`} />
}

export function SourcesTable({ sources }: SourcesTableProps) {
  if (sources.length === 0) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <p className="text-gray-500 text-center">No sources connected</p>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <table className="w-full">
        <thead className="bg-gray-50 border-b border-gray-200">
          <tr>
            <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">Source</th>
            <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">Type</th>
            <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">Status</th>
            <th className="text-right px-4 py-3 text-xs font-medium text-gray-500 uppercase">Messages</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {sources.map((source) => (
            <tr key={source.name} className="hover:bg-gray-50">
              <td className="px-4 py-3">
                <Link
                  to={`/stream/${source.name}`}
                  className="font-mono text-sm text-blue-600 hover:underline"
                >
                  {source.name}
                </Link>
              </td>
              <td className="px-4 py-3 text-sm text-gray-600">{source.type}</td>
              <td className="px-4 py-3">
                <div className="flex items-center gap-2">
                  <StatusDot status={source.status} />
                  <span className="text-sm capitalize">{source.status}</span>
                </div>
              </td>
              <td className="px-4 py-3 text-right font-mono text-sm">
                {source.messages_sampled.toLocaleString()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
