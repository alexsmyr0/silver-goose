"""Visit ranked ingredient combinations without expanding their Cartesian product."""
import heapq


def ranked_product(options, cost):
    """Yield role/value dictionaries in increasing total cost, using bounded memory.

    The caller stops once its pair allowance is filled. No application state, metadata,
    rendering or compatibility rules live here; those remain in reaction.py.
    """
    if any(not values for _,values in options):return
    options=[(role,sorted(values,key=lambda value:cost(role,value))) for role,values in options]
    def priority(indices):
        costs=[cost(role,values[i]) for i,(role,values) in zip(indices,options)]
        total=tuple(map(sum,zip(*costs))) if isinstance(costs[0],tuple) else sum(costs)
        return total,sum(indices),indices
    first=(0,)*len(options);heap=[priority(first)];seen={first}
    while heap:
        _,_,indices=heapq.heappop(heap)
        yield {role:values[i] for i,(role,values) in zip(indices,options)}
        for axis,(_,values) in enumerate(options):
            nxt=list(indices);nxt[axis]+=1;nxt=tuple(nxt)
            if nxt[axis]<len(values) and nxt not in seen:
                seen.add(nxt);heapq.heappush(heap,priority(nxt))
