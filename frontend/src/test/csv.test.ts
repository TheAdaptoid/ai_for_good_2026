import { describe, expect, it } from 'vitest'
import { parseCsv } from '../csv'

describe('CSV table fields', () => {
  it('preserves quoted commas, escaped quotes, embedded line breaks and empty cells', () => {
    expect(parseCsv('id,note,source\r\n1,"Singing, ""together""\nagain",HUMAN\r\n2,,\r\n')).toEqual([
      ['id', 'note', 'source'], ['1', 'Singing, "together"\nagain', 'HUMAN'], ['2', '', ''],
    ])
  })
  it('handles headers alone, a final row without newline and no content', () => {
    expect(parseCsv('id,note\n')).toEqual([['id', 'note']])
    expect(parseCsv('id,note\n1,')).toEqual([['id', 'note'], ['1', '']])
    expect(parseCsv('')).toEqual([])
    expect(parseCsv('""')).toEqual([['']])
  })
})
