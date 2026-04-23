interface MetricsCardProps {
  label: string
  value: number | string
  sublabel?: string
}

export function MetricsCard({ label, value, sublabel }: MetricsCardProps) {
  const formatted = typeof value === 'number' ? value.toLocaleString() : value

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6">
      <p className="text-xs text-gray-500 uppercase tracking-wide mb-2">{label}</p>
      <p className="text-3xl font-semibold font-mono tracking-tight text-gray-900">{formatted}</p>
      {sublabel && <p className="text-sm text-gray-400 mt-1">{sublabel}</p>}
    </div>
  )
}
