"""Configure Kibana authentication and the Elasticsearch snapshot repository on 92."""

import base64
import json
import subprocess
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler


def main():
    subprocess.run(["bash", str(Path(__file__).with_name("ops.sh")), "storage", "exec", "-T", "--user", "root", "elasticsearch", "chown", "1000:0", "/snapshots"], check=True)
    env = dict(line.split("=", 1) for line in Path(__file__).with_name("storage.env").read_text().splitlines() if line and not line.startswith("#"))
    authorization = base64.b64encode(f'elastic:{env["ELASTIC_PASSWORD"]}'.encode()).decode()
    opener = build_opener(ProxyHandler({}))
    for path, payload in (
        ("/_security/user/kibana_system/_password", {"password": env["KIBANA_PASSWORD"]}),
        ("/_snapshot/ragflow_backup", {"type": "fs", "settings": {"location": "/snapshots", "compress": True}}),
    ):
        request = Request(f'http://{env["STORAGE_IP"]}:9200{path}', data=json.dumps(payload).encode(), headers={"Authorization": f"Basic {authorization}", "Content-Type": "application/json"}, method="PUT" if "_snapshot" in path else "POST")
        with opener.open(request, timeout=30) as response:
            print(path, response.status, response.read().decode())


if __name__ == "__main__":
    main()
