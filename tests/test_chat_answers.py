"""The chat page renders query answers as plain text without sending rows to the model."""

from kajenn_dbmanager.chat_answers import MAX_TABLE_ROWS, answer_text, result_table

RESULT = {'status': 'results', 'sql': 'SELECT city, count(*) FROM customer GROUP BY city',
          'assumptions': ['customers are rows of customer'],
          'result': {'columns': ['city', 'count'], 'rows': [['Milano', 1], ['Roma', None]],
                     'truncated': False}}


def test_answer_lists_assumptions_sql_and_row_count():
    text = answer_text(RESULT)
    assert 'Assumptions: customers are rows of customer' in text
    assert RESULT['sql'] in text and '2 rows: see Results.' in text
    assert 'Milano' not in text


def test_result_table_aligns_columns_and_blanks_nulls():
    lines = result_table(RESULT).splitlines()
    assert lines[0].split() == ['city', 'count'] and set(lines[1]) <= {'-', ' '}
    assert lines[2].split() == ['Milano', '1'] and lines[3].split() == ['Roma']
    assert len({len(line.rstrip()) <= len(lines[1]) for line in lines}) == 1


def test_clarification_and_truncation():
    assert answer_text({'status': 'needs_clarification', 'clarification': 'Which year?'}) == \
        'Clarification needed: Which year?'
    many = {'result': {'columns': ['n'], 'rows': [[i] for i in range(MAX_TABLE_ROWS + 5)],
                       'truncated': True}}
    assert f'{MAX_TABLE_ROWS} rows (truncated)' in answer_text(many)
    assert len(result_table(many).splitlines()) == MAX_TABLE_ROWS + 2
    assert result_table({'status': 'sql_ready'}) == ''
