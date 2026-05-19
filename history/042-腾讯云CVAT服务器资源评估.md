# 腾讯云 CVAT 服务器资源评估

Updated: 2026-05-06

## Server

- Target IP: `62.234.222.63`
- Login user: `ubuntu`
- SSH access: local private-key login was available; key content was not read or recorded.
- Hostname: `VM-0-5-ubuntu`
- OS: `Ubuntu 24.04.4 LTS`
- Kernel: `Linux 6.8.0-101-generic x86_64`

## Resources

- CPU: `4 vCPU`
- CPU model: `Intel(R) Xeon(R) Platinum 8255C CPU @ 2.50GHz`
- Memory: `3.6GiB` total, about `2.2GiB` available during the check.
- Swap: `1.9GiB` total, `1.4GiB` already used, about `567MiB` free.
- System disk: `/dev/vda2 ext4 40G`, about `31G` used and about `7.0G` available.
- Independent data disk: not found.
- COS: user reported `100G` COS object storage, but no COS/s3fs/goofys/rclone mount was found on the server.

## Runtime State

- Docker: installed, `Docker version 29.1.3`.
- Docker Compose: not installed; `docker compose` was unavailable and `docker-compose` was not found.
- Web service: `nginx 1.24.0 (Ubuntu)` was running.
- Ports: `80` and `443` were occupied by nginx.
- `8080`, `8081`, and `8090` were not listening during the check.
- DNS: `cvat.aiourstory.cn` currently resolved to `198.18.1.23`, not `62.234.222.63`.

## Engineering Judgment

This server is not suitable for direct formal CVAT multi-user annotation deployment in its current state.

Main blockers:

- The system disk has only about `7G` free. CVAT images, PostgreSQL data, Redis/cache data, task chunks, exports, and Docker layers can exceed this quickly.
- Memory is below the recommended practical floor for CVAT. The host already uses most of its `1.9GiB` swap, which suggests memory pressure before adding the CVAT stack.
- COS object storage is not a replacement for a local Docker/PostgreSQL/CVAT primary data volume. CVAT's database and task/chunk/cache storage need stable low-latency POSIX/block-device semantics.
- Docker Compose is missing.
- nginx already owns ports `80` and `443`, so reverse proxy routing must be planned before exposing CVAT.
- `cvat.aiourstory.cn` DNS is not pointed at the Tencent Cloud host yet.

## Recommendation

- Add and mount a Tencent CBS cloud disk before deployment.
- Minimum data disk: `100G`; more comfortable for ongoing multi-user annotation: `200G+`.
- Mount the data disk at `/data`.
- Move Docker and CVAT persistent data under `/data`, for example Docker data root and CVAT volumes.
- Upgrade memory to at least `8G`; `16G` is safer for multi-user annotation and larger dataset import/export.
- Use COS for import/export exchange, archive, and backup, not as the main CVAT database or Docker volume storage.
- Install Docker Compose v2 after disk and memory are corrected.
- Point `cvat.aiourstory.cn` to `62.234.222.63`, then use nginx as the HTTPS reverse proxy.
