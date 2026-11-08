# Security Hardening & Container Architecture Reference

This reference document outlines the architectural decisions, security standards, and operational guidelines embedded into the `django-docker-scaffold` infrastructure.

---

## 1. Debian-slim vs. Alpine Linux Runtime

### 1.1 The glibc vs. musl Dilemma
While Alpine Linux produces smaller initial base images, it utilizes `musl libc` instead of GNU C Library (`glibc`). Most pre-compiled Python binary wheels distributed on PyPI (such as `psycopg2-binary`, `Pillow`, `cryptography`, `numpy`, and `cffi`) target the `manylinux` platform standard, which relies on `glibc`.

When using Alpine:
- Pre-built binary wheels fail or are rejected by `pip`, forcing local compilation from C source.
- Building from source requires heavy build dependencies (`gcc`, `g++`, `musl-dev`, `python3-dev`, `libpq-dev`, `libjpeg-turbo-dev`, `zlib-dev`), slowing CI/CD pipeline builds by orders of magnitude.
- Alpine's musl memory allocator exhibits documented performance bottlenecks under high-concurrency multi-threaded and multi-worker Python workloads (Gunicorn / Uvicorn).

### 1.2 Decision: `python:3.12-slim-bookworm`
The `debian-slim` base image (`python:3.12-slim-bookworm`) is chosen for production Django deployments:
- Provides native `glibc` wheel compatibility, drastically speeding up container builds.
- Maintains a tightly stripped package footprint, minimizing CVE vulnerability surfaces.
- Avoids compiler tools in runtime production stages.

---

## 2. Unprivileged User & Filesystem Permissions

### 2.1 Principle of Least Privilege
Containers must never execute the web application or background workers as `root` (UID 0). A container breakout from a root-owned process gives the attacker root privileges on the underlying host kernel.

### 2.2 System User Provisioning
The Dockerfile provisions a dedicated, non-interactive system group and user:
```dockerfile
RUN groupadd --system --gid 1001 appgroup && \
    useradd --system --uid 1001 --gid appgroup --no-create-home --shell /bin/false appuser
```
- UID/GID `1001:1001` avoids standard host desktop UID `1000` collisions while remaining unprivileged.
- `--no-create-home` and `--shell /bin/false` prevent interactive terminal access or persistent home directory attack vectors.

### 2.3 Volume and Directory Ownership
Static asset generation and user media uploads require explicit folder permissions:
- `/src/static` and `/src/media` are created during image build time and assigned to `appuser:appgroup`.
- Permissions are fixed before dropping root:
```dockerfile
RUN mkdir -p /src/static /src/media && \
    chown -R appuser:appgroup /src
```
- By handling ownership during the build layer, the container entrypoint never requires `sudo` or root permissions at runtime.

---

## 3. Signal Handling & PID 1 Process Handoff

### 3.1 The Shell Wrapper Trap
When an entrypoint script executes a command directly (e.g., `python manage.py runserver` or `gunicorn ...`), the shell process (`/bin/sh` or `/bin/bash`) retains PID 1.
- Default POSIX shells do not forward system signals (`SIGTERM`, `SIGINT`) to child processes.
- When an orchestrator (Docker, Kubernetes, AWS ECS) stops a container, it sends `SIGTERM`.
- Because the shell swallows the signal, the application keeps running unaware until Docker issues a forced `SIGKILL` (typically after a 10-second grace timeout).
- Result: Dropped active database transactions, aborted file writes, corrupted cache keys, and incomplete worker jobs.

### 3.2 Process Replacement with `exec`
The `exec` shell built-in command replaces the current shell process image with the target command without creating a new process:
```bash
exec "$@"
```
By terminating the entrypoint script with `exec "$@"`, the application server (e.g. Gunicorn) inherits PID 1 directly, registers Linux signal handlers properly, and achieves graceful, zero-downtime draining upon receiving `SIGTERM`.

---

## 4. Container Log Rotation

### 4.1 Disk Exhaustion Mitigation
By default, Docker's `json-file` logging driver retains all container stdout and stderr indefinitely in `/var/lib/docker/containers/<id>/<id>-json.log`. In high-traffic Django environments, unthrottled access logs can quickly consume the host disk, leading to database failure or node crashes.

### 4.2 Logging Configuration Standard
All production Compose services must include structured log rotation constraints:
```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"
```
This guarantees that no container log ever exceeds 30 MB on disk (3 rotated files of 10 MB each).
