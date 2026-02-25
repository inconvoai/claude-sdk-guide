export function InconvoTable({
  message,
  table,
}: {
  message: string;
  table: { head: string[]; body: string[][] };
}) {
  if (!table.head || !table.body) {
    return <div className="text-red-500">Invalid table data</div>;
  }

  if (table.body.length === 0) {
    return (
      <div>
        <p className="mb-2 text-sm">{message}</p>
        <div className="text-zinc-500">No data</div>
      </div>
    );
  }

  return (
    <div className="my-2">
      <p className="mb-2 text-sm">{message}</p>
      <div className="overflow-x-auto">
        <table className="min-w-full border border-zinc-300 dark:border-zinc-700">
          <thead className="bg-zinc-100 dark:bg-zinc-800">
            <tr>
              {table.head.map((header, idx) => (
                <th
                  key={idx}
                  className="px-4 py-2 text-left text-sm font-semibold"
                >
                  {header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.body.map((row, rowIdx) => (
              <tr
                key={rowIdx}
                className="border-t border-zinc-300 dark:border-zinc-700"
              >
                {row.map((cell, cellIdx) => (
                  <td key={cellIdx} className="px-4 py-2 text-sm">
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
