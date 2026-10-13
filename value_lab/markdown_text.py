"""Literal Markdown text and structured evidence tables; no HTML encoding."""


def literal(value):
    if value is None:
        return '未知'
    if isinstance(value, dict):
        return '；'.join(literal(k) + ': ' + literal(v) for k, v in value.items()) or '（空对象）'
    if isinstance(value, (list, tuple)):
        return '；'.join(literal(v) for v in value) or '（空列表）'
    text = str(value)
    for char in ('\\', '`', '*', '_', '[', ']', '(', ')', '!', '|', '#', '~', '+', '-', '<', '>', '&'):
        text = text.replace(char, '\\' + char)
    return ' / '.join(text.splitlines())


def key_value_table(value):
    """Flatten nested keys/indexes without losing false, zero or missing values."""
    rows = ['| 字段 | 值 |', '| --- | --- |']

    def visit(item, path):
        if isinstance(item, dict) and item:
            for key, child in item.items():
                visit(child, path + [str(key)])
        elif isinstance(item, (list, tuple)) and item:
            for index, child in enumerate(item):
                visit(child, path + [str(index)])
        else:
            rows.append('| ' + literal(' / '.join(path) or '值') + ' | ' + literal(item) + ' |')

    visit(value, [])
    return '\n'.join(rows)
