import os


def load_local_env():
    """Load local env files without extra dependencies."""
    backend_dir = os.path.dirname(os.path.dirname(__file__))
    root_dir = os.path.dirname(backend_dir)
    for env_path in (
        os.path.join(root_dir, ".env.local"),
        os.path.join(backend_dir, ".env.local"),
    ):
        if not os.path.exists(env_path):
            continue
        with open(env_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
