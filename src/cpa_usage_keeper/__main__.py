"""Entry point: python -m cpa_usage_keeper"""
import sys
import uvicorn
from .app import create_app


import argparse

def main():
    parser = argparse.ArgumentParser(description="CPA Usage Keeper Backend")
    parser.add_argument("-c", "--config", default="config.toml", help="Path to config.toml")
    args = parser.parse_args()

    app = create_app(config_file=args.config)
    port = int(app.state.cfg.app_port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
