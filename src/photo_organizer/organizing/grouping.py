"""Composable deterministic grouping levels; explicit overlap and unknown handling."""

from photo_organizer.search.predicates import predicate
from photo_organizer.storage.filesystem import relative_parts

FIELDS = {"year", "month", "category", "orientation", "none"}


def compile_levels(c, spec):
    if "levels" in spec:
        if "group_by" in spec or "groups" in spec:
            raise ValueError("levels cannot be mixed with legacy grouping")
        levels = spec["levels"]
        if not isinstance(levels, list) or not 1 <= len(levels) <= 8:
            raise ValueError("levels must contain 1..8 grouping levels")
    else:
        group_by = spec.get("group_by", "none")
        levels = (
            [{"rules": spec.get("groups"), "overlap": spec.get("overlap", "error")}]
            if group_by == "rules"
            else [{"field": group_by}]
        )
    compiled = []
    for level in levels:
        if not isinstance(level, dict) or set(level) - {"field", "rules", "overlap"}:
            raise ValueError("invalid grouping level")
        if "field" in level:
            if set(level) != {"field"} or level["field"] not in FIELDS:
                raise ValueError("unsupported grouping field")
            compiled.append(level)
            continue
        groups = level.get("rules")
        overlap = level.get("overlap", "error")
        if (
            not isinstance(groups, list)
            or not 1 <= len(groups) <= 50
            or overlap not in ("error", "first", "multi")
        ):
            raise ValueError("invalid rules/overlap policy")
        compiled_rules = []
        names = set()
        for group in groups:
            if not isinstance(group, dict) or set(group) != {"name", "where"}:
                raise ValueError("invalid group")
            name = group["name"]
            if (
                not isinstance(name, str)
                or len(relative_parts(name)) != 1
                or name.casefold() in names
                or name in ("unclassified", "needs-review")
            ):
                raise ValueError("invalid/duplicate/reserved group name")
            names.add(name.casefold())
            sql, args = predicate(group["where"])
            rows = c.execute(
                "SELECT f.id,("
                + sql
                + ") AS verdict FROM files f LEFT JOIN assets a ON a.hash=f.hash WHERE f.present=1",
                args,
            ).fetchall()
            compiled_rules.append(
                (
                    name,
                    {r["id"] for r in rows if r["verdict"] == 1},
                    {r["id"] for r in rows if r["verdict"] is None},
                )
            )
        compiled.append({"rules": compiled_rules, "overlap": overlap})
    return compiled


def paths(row, levels):
    paths = [""]
    for level in levels:
        if "field" in level:
            field = level["field"]
            if field == "year":
                names = [row["taken"][:4] if row["taken"] else "date-unknown"]
            elif field == "month":
                names = [row["taken"][:7].replace("-", "/") if row["taken"] else "date-unknown"]
            elif field == "category":
                names = [
                    row["category"]
                    if row["vision_state"] == "complete" and row["category"]
                    else "needs-review"
                ]
            elif field == "orientation":
                names = [
                    "landscape"
                    if row["width"] > row["height"]
                    else "portrait"
                    if row["width"] < row["height"]
                    else "square"
                ]
            else:
                names = ["selected"]
        else:
            names = [name for name, yes, unknown in level["rules"] if row["id"] in yes]
            if len(names) > 1 and level["overlap"] == "error":
                raise ValueError("overlapping categories require clarification; no plan created")
            if level["overlap"] == "first":
                names = names[:1]
            if not names:
                names = [
                    "needs-review"
                    if any(row["id"] in unknown for _, yes, unknown in level["rules"])
                    else "unclassified"
                ]
        paths = [p + "/" + name if p else name for p in paths for name in names]
        if len(paths) > 100:
            raise ValueError("overlap expansion exceeds 100 memberships per image")
    return paths
