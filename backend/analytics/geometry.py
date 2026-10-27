"""Deterministic pitch geometry; ties resolved by player IDs rather than input order."""

def hull(points):
    points = sorted(set(tuple(p) for p in points))
    if len(points) <= 1:
        return points

    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    halves = []
    for ordered in (points, points[::-1]):
        half = []
        for p in ordered:
            while len(half) >= 2 and cross(half[-2], half[-1], p) <= 0:
                half.pop()
            half.append(p)
        halves.append(half[:-1])
    return halves[0] + halves[1]


def area(points):
    return abs(sum(a[0] * b[1] - a[1] * b[0] for a, b in zip(points, points[1:] + points[:1]))) / 2


def formation(points, home, length, margin=.25, min_spread=1):
    """Largest-gap deterministic clustering; four lines must improve separation."""
    ordered = sorted(points, key=lambda p: ((p[1] if home else length - p[1]), p[0]))
    if len(ordered) < 3:
        return None
    depths = [p[1] if home else length - p[1] for p in ordered]

    def split(k):
        cuts = sorted(sorted(range(1, len(ordered)), key=lambda i: (-(depths[i] - depths[i - 1]), i))[:k - 1])
        groups = [ordered[a:b] for a, b in zip([0] + cuts, cuts + [len(ordered)])]
        means = [sum(p[1] if home else length - p[1] for p in g) / len(g) for g in groups]
        spread = sum(max(p[1] for p in g) - min(p[1] for p in g) for g in groups) / k
        gap = min(b - a for a, b in zip(means, means[1:]))
        return {"label": "-".join(str(len(g)) for g in groups), "separation_score": round(gap / max(spread, min_spread), 3),
                "lines": [{"player_ids": [p[0] for p in sorted(g, key=lambda p: (p[2], p[0]))],
                           "mean_depth_m": round(mean, 2)} for g, mean in zip(groups, means)]}

    three = split(3)
    if len(ordered) >= 4:
        four = split(4)
        if four["separation_score"] > three["separation_score"] * (1 + margin):
            return four
    return three
