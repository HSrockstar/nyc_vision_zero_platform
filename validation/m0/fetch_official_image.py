"""M0 专用：经本机 HTTP 代理下载官方 Docker Hub OCI 镜像，逐对象验 SHA-256。"""
from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
import urllib.request
from urllib.parse import urlsplit
from pathlib import Path


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        if urlsplit(new_url).scheme != "https":
            raise ValueError("官方镜像下载拒绝非HTTPS重定向")
        redirected = super().redirect_request(request, response, code, message, headers, new_url)
        if redirected and urlsplit(request.full_url).netloc != urlsplit(new_url).netloc:
            redirected.remove_header("Authorization")
        return redirected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--index-digest", required=True)
    parser.add_argument("--proxy", required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": args.proxy, "https": args.proxy}), SafeRedirect())
    token_url = f"https://auth.docker.io/token?service=registry.docker.io&scope=repository:{args.repository}:pull"
    with opener.open(token_url, timeout=30) as response:
        token = json.load(response)["token"]
    base = f"https://registry.hub.docker.com/v2/{args.repository}"
    root = args.archive.parent / (args.repository.replace("/", "-") + "-oci")
    blobs = root / "blobs" / "sha256"
    blobs.mkdir(parents=True, exist_ok=True)
    args.evidence.mkdir(parents=True, exist_ok=True)
    records = []

    def fetch(kind, reference, expected, size=None):
        digest = expected.removeprefix("sha256:")
        path = blobs / digest
        if path.exists():
            with path.open("rb") as cached:
                valid = hashlib.file_digest(cached, "sha256").hexdigest() == digest
            if valid and (size is None or path.stat().st_size == size):
                return path
        request = urllib.request.Request(f"{base}/{kind}/{reference}", headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json",
        })
        partial = path.with_suffix(".partial")
        hasher = hashlib.sha256()
        length = 0
        # 令牌只存在于内存；不保存重定向签名 URL、认证头或响应凭据。
        with opener.open(request, timeout=60) as response, partial.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                hasher.update(chunk)
                length += len(chunk)
        if hasher.hexdigest() != digest or (size is not None and length != size):
            raise ValueError(f"官方镜像对象校验失败：{expected}")
        partial.replace(path)
        records.append({"url": request.full_url, "status": 200, "digest": expected, "bytes": length, "sha256_verified": True})
        (args.evidence / "image-download.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
        print(f"已校验 {kind} {expected} ({length} bytes)", flush=True)
        return path

    index_path = fetch("manifests", args.tag, args.index_digest)
    index = json.loads(index_path.read_bytes())
    descriptor = next(item for item in index["manifests"] if item.get("platform") == {"architecture": "amd64", "os": "linux"})
    manifest_path = fetch("manifests", descriptor["digest"], descriptor["digest"], descriptor["size"])
    manifest = json.loads(manifest_path.read_bytes())
    for item in [manifest["config"], *manifest["layers"]]:
        fetch("blobs", item["digest"], item["digest"], item["size"])
    config = json.loads((blobs / manifest["config"]["digest"].split(":")[1]).read_bytes())
    descriptor["annotations"] = {"org.opencontainers.image.ref.name": f"docker.io/{args.repository}:{args.tag}"}
    (root / "index.json").write_text(json.dumps({"schemaVersion": 2, "mediaType": "application/vnd.oci.image.index.v1+json", "manifests": [descriptor]}), encoding="utf-8")
    (root / "oci-layout").write_text('{"imageLayoutVersion":"1.0.0"}', encoding="utf-8")
    with tarfile.open(args.archive, "w") as archive:
        for path in root.rglob("*"):
            if path.is_file() and path.suffix != ".partial":
                archive.add(path, arcname=path.relative_to(root).as_posix())
    # 只保存版本环境变量；不输出官方 config 的其他环境信息。
    versions = [value for value in config["config"].get("Env", []) if value.startswith(("PG_VERSION=", "POSTGIS_VERSION=", "PYTHON_VERSION="))]
    report = {"source": f"docker.io/{args.repository}:{args.tag}", "index_digest": args.index_digest,
              "manifest_digest": descriptor["digest"], "config_digest": manifest["config"]["digest"],
              "platform": descriptor["platform"], "versions_from_config": versions,
              "archive_sha256": hashlib.file_digest(args.archive.open("rb"), "sha256").hexdigest(),
              "archive_bytes": args.archive.stat().st_size, "tls_verification": True}
    (args.evidence / "image-verified.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
