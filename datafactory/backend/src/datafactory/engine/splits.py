"""Deterministic connected components for leakage-safe dataset partitioning."""

import re
import unicodedata
from collections import defaultdict


def components(rows: list[dict]) -> list[str]:
    """Union families, shared positives and queries with token Jaccard >= 0.8.

    An inverted token index finds candidates; exact similarity confirms each
    edge. Component names depend on content keys, never input order.
    """
    parents = list(range(len(rows)))

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left, right):
        parents[root(right)] = root(left)

    families, positives, exact = {}, {}, {}
    postings = defaultdict(list)
    tokens = []
    for index, row in enumerate(rows):
        family = row.get("group_key")
        if family:
            union(index, families.setdefault(family, index))
        for positive in row.get("positives", []):
            union(index, positives.setdefault(positive, index))
        query = unicodedata.normalize("NFKC", str(row.get("query") or "")).casefold()
        words = set(re.findall(r"[\u3400-\u9fff]|[^\W_]+", query))
        tokens.append(words)
        if not words:
            continue
        normalized = " ".join(sorted(words))
        if normalized in exact:
            union(index, exact[normalized])
            continue
        exact[normalized] = index
        overlaps = defaultdict(int)
        for token in words:
            for prior in postings[token]:
                if min(len(words), len(tokens[prior])) >= 0.8 * max(len(words), len(tokens[prior])):
                    overlaps[prior] += 1
        for prior, overlap in overlaps.items():
            if overlap / (len(words) + len(tokens[prior]) - overlap) >= 0.8:
                union(index, prior)
        for token in words:
            postings[token].append(index)
    names = {}
    for index, row in enumerate(rows):
        name = str(row.get("group_key") or row.get("row_key") or index)
        component = root(index)
        names[component] = min(names.get(component, name), name)
    return [names[root(index)] for index in range(len(rows))]
