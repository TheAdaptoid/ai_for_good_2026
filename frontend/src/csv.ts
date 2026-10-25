/** Read the quoted fields, escaped quotes and line breaks emitted by the CSV exporter. */
export function parseCsv(csv: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let quoted = false
  for (let i = 0; i < csv.length; i++) {
    const char = csv[i]
    if (char === '"') {
      if (quoted && csv[i + 1] === '"') { field += '"'; i++ }
      else quoted = !quoted
    } else if (!quoted && (char === ',' || char === '\n' || char === '\r')) {
      row.push(field)
      field = ''
      if (char !== ',') {
        rows.push(row)
        row = []
        if (char === '\r' && csv[i + 1] === '\n') i++
      }
    } else field += char
  }
  if (field || row.length || csv.endsWith('"')) rows.push([...row, field])
  return rows
}
