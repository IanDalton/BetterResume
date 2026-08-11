export function BarChart({ data, title }: { data: Array<{ day: string; label?: string; count: number }>; title: string }) {
  const max = Math.max(1, ...data.map(d => d.count));
  // Show at most ~12 x-axis labels so many bars (e.g. 90d) stay readable.
  const step = Math.max(1, Math.ceil(data.length / 12));
  return (
    <div className="bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-700 rounded-xl p-4 shadow-sm">
      <h3 className="text-sm font-medium mb-3">{title}</h3>
      {data.length === 0 ? (
        <p className="text-xs text-neutral-500">No data yet.</p>
      ) : (
        <div className="flex items-end gap-1 h-32 overflow-hidden">
          {data.map((d, i) => {
            const label = d.label ?? d.day.slice(5);
            return (
              <div key={d.day} className="flex-1 min-w-0 max-w-[48px] flex flex-col items-center justify-end h-full" title={`${label}: ${d.count}`}>
                <div
                  className="w-full bg-primary-500/80 dark:bg-primary-400/80 rounded-t"
                  style={{ height: `${Math.max(4, (d.count / max) * 100)}%` }}
                />
                <span className="text-[9px] text-neutral-500 mt-1 whitespace-nowrap text-center h-3 leading-3 shrink-0">
                  {i % step === 0 ? label : ''}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
