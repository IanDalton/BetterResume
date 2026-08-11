export function CountTable({ title, rows, keyLabel }: { title: string; rows: Array<{ label: string; count: number }>; keyLabel: string }) {
  return (
    <div className="bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-700 rounded-xl p-4 shadow-sm">
      <h3 className="text-sm font-medium mb-3">{title}</h3>
      {rows.length === 0 ? (
        <p className="text-xs text-neutral-500">No data yet.</p>
      ) : (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-neutral-500">
              <th className="pb-1 font-normal">{keyLabel}</th>
              <th className="pb-1 font-normal text-right">Count</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.label} className="border-t border-neutral-100 dark:border-neutral-800">
                <td className="py-1 truncate max-w-[200px]" title={r.label}>{r.label}</td>
                <td className="py-1 text-right font-mono">{r.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
