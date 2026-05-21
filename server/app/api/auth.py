from fastapi import APIRouter, Depends
from app.core.security import verify_api_key

router = APIRouter()


@router.post("/validate")
async def validate_key(api_key: str = Depends(verify_api_key)):
    """Проверка валидности API ключа"""
    return {"valid": True, "message": "Ключ действителен"}
