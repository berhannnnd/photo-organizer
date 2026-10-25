"""User-authorized reusable rules and preferences, with explicit snapshot or dynamic scope."""

import json
import uuid

from photo_organizer.core.paging import page, validate
from photo_organizer.search import results
from photo_organizer.search.predicates import predicate
from photo_organizer.search.selection import now
from photo_organizer.storage.catalog import connect


def save(
    state, name, rule=None, result_id=None, preference=None, recipe_id=None, expected_version=None
):
    """Persist only on explicit user request to remember; dynamic rules refresh only when materialized."""
    if not isinstance(name, str) or not 1 <= len(name) <= 200:
        raise ValueError("name must be 1..200 characters")
    if (rule is None) == (result_id is None):
        raise ValueError("provide either a dynamic rule or a frozen result_id")
    if rule is not None:
        if len(json.dumps(rule)) > 16000:
            raise ValueError("rule too large")
        predicate(rule)
    if preference is not None and (
        not isinstance(preference, str) or not 1 <= len(preference) <= 4000
    ):
        raise ValueError("preference must be 1..4000 characters")
    with connect(state) as c:
        c.execute("BEGIN IMMEDIATE")
        if result_id:
            results.require(c, result_id)
        identifier = recipe_id or uuid.uuid4().hex
        key = "recipe:" + identifier
        existing = c.execute("SELECT value FROM library_settings WHERE key=?", (key,)).fetchone()
        prior = json.loads(existing[0]) if existing else None
        if recipe_id and not prior:
            raise ValueError("unknown recipe")
        if prior and expected_version != prior["version"]:
            raise ValueError("recipe version conflict; read before editing")
        value = {
            "recipe_id": identifier,
            "version": prior["version"] + 1 if prior else 1,
            "name": name,
            "scope": "dynamic" if rule is not None else "snapshot",
            "rule": rule,
            "result_id": result_id,
            "preference": preference,
            "updated": now(),
        }
        if prior:
            c.execute(
                "INSERT INTO library_settings VALUES(?,?)",
                ("recipe-history:" + identifier + ":" + str(prior["version"]), json.dumps(prior)),
            )
        c.execute(
            "INSERT INTO library_settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )
    return value


def read(state, recipe_id=None, limit=50, offset=0):
    validate(limit, offset)
    with connect(state) as c:
        if recipe_id:
            row = c.execute(
                "SELECT value FROM library_settings WHERE key=?", ("recipe:" + recipe_id,)
            ).fetchone()
            if not row:
                raise ValueError("unknown recipe")
            return json.loads(row[0])
        total = c.execute(
            "SELECT count(*) FROM library_settings WHERE key LIKE 'recipe:%'"
        ).fetchone()[0]
        items = [
            json.loads(r[0])
            for r in c.execute(
                "SELECT value FROM library_settings WHERE key LIKE 'recipe:%' ORDER BY key LIMIT ? OFFSET ?",
                (limit, offset),
            )
        ]
        return page(items, total, limit, offset, "recipes")


def materialize(state, recipe_id):
    recipe = read(state, recipe_id)
    result = (
        results.create(state, recipe["rule"])
        if recipe["scope"] == "dynamic"
        else results.page(state, recipe["result_id"])
    )
    return {
        **result,
        "recipe_id": recipe_id,
        "recipe_version": recipe["version"],
        "preference": recipe["preference"],
        "scope_mode": recipe["scope"],
    }
