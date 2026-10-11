import uvicorn
from bridge.config import settings

def main():
    uvicorn.run(
        "bridge.api.app:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        # Behind Dokploy/Traefik: trust X-Forwarded-Proto/Host so generated URLs are https.
        proxy_headers=True,
        forwarded_allow_ips="*",
    )

if __name__ == "__main__":
    main()
