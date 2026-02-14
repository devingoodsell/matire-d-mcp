from src.server import initialize

if __name__ == "__main__":  # pragma: no cover
    app = initialize()

    from src.config import get_settings

    settings = get_settings()

    if settings.mcp_transport == "streamable-http":
        app.run(
            transport="streamable-http",
            host=settings.mcp_host,
            port=settings.mcp_port,
        )
    else:
        app.run()
