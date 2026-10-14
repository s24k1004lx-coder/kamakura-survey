"""Render.com 用起動スクリプト — 環境変数から secrets.toml を生成して Streamlit を起動"""
import os
import subprocess

os.makedirs(".streamlit", exist_ok=True)
with open(".streamlit/secrets.toml", "w") as f:
    f.write(f'[supabase]\n')
    f.write(f'url = "{os.environ["SUPABASE_URL"]}"\n')
    f.write(f'key = "{os.environ["SUPABASE_KEY"]}"\n\n')
    f.write(f'[auth]\n')
    f.write(f'password = "{os.environ["APP_PASSWORD"]}"\n')

port = os.environ.get("PORT", "8501")
subprocess.run([
    "streamlit", "run", "app.py",
    "--server.port", port,
    "--server.address", "0.0.0.0",
    "--server.headless", "true",
])
