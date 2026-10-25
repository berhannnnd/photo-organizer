"""Bounded, parameterized three-valued predicates; absent labels are unknown."""
import datetime
import hashlib

ALIASES = {'猫': 'cat', '猫咪': 'cat', '狗': 'dog', '人': 'person', '人物': 'person'}
FIELDS = {'all_tags', 'any_tags', 'not_tags', 'caption_text', 'date_from',
          'date_to', 'orientation', 'semantic', 'category', 'and', 'or', 'not'}


def condition_key(text):
    return hashlib.sha256(text.strip().encode()).hexdigest()


def predicate(rule, depth=0):
    if depth > 12 or not isinstance(rule, dict) or set(rule) - FIELDS:
        raise ValueError('invalid query fields or nesting exceeds 12')
    clauses, args = [], []
    for key in ('and', 'or'):
        if key in rule:
            children = rule[key]
            if not isinstance(children, list) or not 1 <= len(children) <= 50:
                raise ValueError('boolean groups require 1..50 conditions')
            parts = []
            for child in children:
                sql, params = predicate(child, depth + 1)
                parts.append('(' + sql + ')'); args.extend(params)
            clauses.append('(' + (' AND ' if key == 'and' else ' OR ').join(parts) + ')')
    if 'not' in rule:
        sql, params = predicate(rule['not'], depth + 1)
        clauses.append('NOT (' + sql + ')'); args.extend(params)
    for key in ('all_tags', 'any_tags', 'not_tags'):
        values = rule.get(key, [])
        if not isinstance(values, list) or len(values) > 100 or any(not isinstance(t, str) or not t.strip() or len(t) > 200 for t in values):
            raise ValueError('invalid tags')
        parts = []
        for term in values:
            term = term.strip().casefold()
            # Positive observation proves presence; a partial description cannot prove absence.
            expr = "CASE WHEN a.vision_state='complete' AND EXISTS(SELECT 1 FROM tags t WHERE t.hash=a.hash AND t.tag=?) THEN 1 ELSE NULL END"
            parts.append(('NOT (' + expr + ')') if key == 'not_tags' else expr)
            args.append(ALIASES.get(term, term))
        if parts:
            clauses.append('(' + (' OR ' if key == 'any_tags' else ' AND ').join(parts) + ')')
    for key, op in [('date_from', '>='), ('date_to', '<=')]:
        if key in rule:
            value = rule[key]
            if not isinstance(value, str): raise ValueError('date must be YYYY-MM-DD')
            datetime.date.fromisoformat(value)
            clauses.append('substr(a.taken,1,10) ' + op + ' ?'); args.append(value)
    if rule.get('date_from') and rule.get('date_to') and rule['date_from'] > rule['date_to']:
        raise ValueError('inverted date range')
    for key, expr in [('caption_text', 'instr(lower(a.caption),lower(?))>0'), ('category', 'a.category=?')]:
        if key in rule:
            if not isinstance(rule[key], str) or not rule[key].strip(): raise ValueError('invalid ' + key)
            if key == 'category':
                clauses.append("CASE WHEN a.vision_state='complete' THEN (" + expr + ') ELSE NULL END')
            else:
                clauses.append("CASE WHEN a.vision_state='complete' AND (" + expr + ') THEN 1 ELSE NULL END')
            args.append(rule[key])
    if 'orientation' in rule:
        op = {'landscape': '>', 'portrait': '<', 'square': '='}.get(rule['orientation'])
        if not op: raise ValueError('invalid orientation')
        clauses.append('a.width ' + op + ' a.height')
    if 'semantic' in rule:
        text = rule['semantic']
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 2000:
            raise ValueError('semantic criterion required (1..2000 chars)')
        clauses.append("(SELECT CASE j.verdict WHEN 'yes' THEN 1 WHEN 'no' THEN 0 ELSE NULL END FROM judgments j JOIN conditions d ON d.id=j.condition_id AND d.version=j.version WHERE j.hash=a.hash AND j.condition_id=?)")
        args.append(condition_key(text))
    return ' AND '.join('(' + p + ')' for p in clauses) or '1', args
