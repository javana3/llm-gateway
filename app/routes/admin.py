from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/admin/usage")
async def usage(request: Request) -> dict:
    store = request.app.state.key_store
    return {
        "keys": [
            {
                "name": k.name,
                "requests": k.requests,
                "used_tokens": k.used_tokens,
                "remaining_tokens": k.remaining_tokens,
                "cost": round(k.cost, 6),
            }
            for k in store.all()
        ]
    }
