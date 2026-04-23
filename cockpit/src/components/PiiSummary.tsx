import type { PiiSummary as PiiSummaryType } from '../lib/types'

interface PiiSummaryProps {
  pii: PiiSummaryType | null
}

const CATEGORY_ICONS: Record<string, string> = {
  email: '📧',
  phone: '📱',
  name: '👤',
  card_number: '💳',
  ip_address: '🌐',
  passport: '🛂',
  national_id: '🆔',
  date_of_birth: '🎂',
}

export function PiiSummary({ pii }: PiiSummaryProps) {
  if (!pii || pii.total === 0) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <p className="text-sm text-gray-500">No PII fields detected</p>
      </div>
    )
  }

  const categories = Object.entries(pii.by_category).sort((a, b) => b[1] - a[1])

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6">
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm font-medium text-gray-700">PII Fields Detected</p>
        <span className="text-2xl font-mono font-semibold">{pii.total}</span>
      </div>
      <div className="space-y-2">
        {categories.map(([category, count]) => (
          <div key={category} className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span>{CATEGORY_ICONS[category] || '🔒'}</span>
              <span className="text-sm capitalize">{category.replace('_', ' ')}</span>
            </div>
            <span className="font-mono text-sm text-gray-600">{count}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
