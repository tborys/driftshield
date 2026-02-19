import uvicorn

from driftshield.api.app import create_app

app = create_app()


def main():
    uvicorn.run(
        "driftshield.api.server:app",
        host="0.0.0.0",
        port=8080,
        reload=False,
    )


if __name__ == "__main__":
    main()
