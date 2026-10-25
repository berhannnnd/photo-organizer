"""Shared bounded pagination contract."""


def validate(limit, offset, maximum=200):
    if type(limit) is not int or not 1 <= limit <= maximum or type(offset) is not int or offset < 0:
        raise ValueError("invalid pagination")


def page(items, total, limit, offset, key="items"):
    return {
        key: items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "next_offset": offset + limit if offset + limit < total else None,
    }
