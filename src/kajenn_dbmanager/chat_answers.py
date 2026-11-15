"""Plain-text rendering of query answers for the workbench chat."""

MAX_TABLE_ROWS = 100


def _table(columns, rows):
    """A plain-text table of the result rows, aligned on the widest cell of each column."""
    cells = [[str(c) for c in columns]] + [['' if v is None else str(v) for v in row]
                                           for row in rows[:MAX_TABLE_ROWS]]
    widths = [max(len(row[i]) for row in cells) for i in range(len(columns))]
    lines = ['  '.join(value.ljust(width) for value, width in zip(row, widths, strict=True)) for row in cells]
    lines.insert(1, '  '.join('-' * width for width in widths))
    return '\n'.join(lines)


def answer_text(result):
    """The assistant message of one answer: clarification, SQL, results or error."""
    if result.get('status') == 'needs_clarification':
        return f"Clarification needed: {result.get('clarification')}"
    parts = []
    if result.get('assumptions'):
        parts.append('Assumptions: ' + '; '.join(str(a) for a in result['assumptions']))
    if result.get('sql'):
        parts.append(result['sql'])
    if result.get('error'):
        parts.append(f"Query error: {result['error']}")
    rows = result.get('result')
    if rows:
        shown = min(len(rows['rows']), MAX_TABLE_ROWS)
        more = ' (truncated)' if rows.get('truncated') or len(rows['rows']) > shown else ''
        parts.append(f'{shown} rows{more}: see Results.')
    return '\n\n'.join(parts) or 'No answer.'


def result_table(result):
    """The rows of an answer as an aligned plain-text table, or an empty string."""
    rows = result.get('result')
    return _table(rows['columns'], rows['rows']) if rows else ''
