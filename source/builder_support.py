"""Shared builder text wrapping and least-used choice helpers. No app imports."""
import random

def int_or(v, default=0):
    try: return int(str(v).strip())
    except Exception: return default

def wrap(text, max_width=24):
    """Break a line into BALANCED lines, the way the reference videos do.

    Filling each line up before starting the next one gets this wrong - it turns
    '"bro.. you need to / get a real job' into '"bro.. you need to get / a real job', and it
    strands the emoji on a line of its own. Choosing the split that makes the longest line
    as short as possible reproduces the reference breaks exactly.

    If you put your own breaks in with \\n, yours are left alone."""
    if "\n" in text or "\\n" in text:
        return text.replace("\\n", "\n")
    words = text.split()
    if len(" ".join(words)) <= max_width or len(words) < 2:
        return " ".join(words)

    def score(parts):
        return (max(len(p) for p in parts), max(len(p) for p in parts) - min(len(p) for p in parts))

    two = min(([" ".join(words[:i]), " ".join(words[i:])] for i in range(1, len(words))), key=score)
    if score(two)[0] <= max_width or len(words) < 3:
        return "\n".join(two)

    three = min(([" ".join(words[:i]), " ".join(words[i:j]), " ".join(words[j:])]
                 for i in range(1, len(words) - 1) for j in range(i + 1, len(words))), key=score)
    return "\n".join(three)

def pick_spread(options, used_counts):
    """Pick the least-used option, ties broken at random.

    Used for tutorials and logos. `random.choice` over three tutorials will happily hand out
    the same one five times in a row; this spreads them evenly across a batch, which is the
    whole point of having more than one.
    """
    if not options: return None
    least = min(used_counts.get(o, 0) for o in options)
    return random.choice([o for o in options if used_counts.get(o, 0) == least])
