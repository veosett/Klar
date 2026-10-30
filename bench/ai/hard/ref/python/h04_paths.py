import heapq


def paths(n: int, edges: list[list[int]], src: int) -> list[int]:
    adj: list[list[tuple[int, int]]] = [[] for _ in range(n)]
    for u, v, w in edges:
        adj[u].append((v, w))
    dist = [-1] * n
    heap = [(0, src)]
    while heap:
        d, u = heapq.heappop(heap)
        if dist[u] != -1:
            continue
        dist[u] = d
        for v, w in adj[u]:
            if dist[v] == -1:
                heapq.heappush(heap, (d + w, v))
    return dist
