import uvicorn
from bridge.config import settings

def main():
    uvicorn.run(
        "bridge.api.app:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )

if __name__ == "__main__":
    main()
