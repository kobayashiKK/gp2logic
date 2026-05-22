#!/bin/bash
# GP2Logic launcher — uses the project-local virtual environment
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/.venv/bin/python" "$DIR/main.py" "$@"
