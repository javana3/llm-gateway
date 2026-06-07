from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/cache/stats")
async def cache_stats(request: Request) -> dict:
    cache = request.app.state.semantic_cache
    s = cache.stats
    return {
        "hits": s.hits,
        "misses": s.misses,
        "l1_hits": s.l1_hits,
        "l2_hits": s.l2_hits,
        "hit_ratio": round(s.hit_ratio, 4),
    }
