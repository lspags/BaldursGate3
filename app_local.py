"""Local development launcher for the BG3 character builder."""

import os

os.environ["BG3_AUTH_ENABLED"] = "0"

from app import app


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8050, debug=True)
