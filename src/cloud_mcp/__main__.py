import os

from .server import main

os.environ.setdefault("PYTHONUNBUFFERED", "1")

if __name__ == "__main__":
    main()
