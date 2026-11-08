---
name: django-core-architecture
description: Authoritative blueprint for modern, decoupled Django project architecture. Establishes the config/ namespace, apps/ syspath resolution, 12-factor django-environ configuration, and optimal WhiteNoise middleware sequencing.
---

# Django Core Architecture

This skill defines the authoritative layout, decoupled configuration structure, and modular application design for Django backends within `antigravity-django-suite`.

---

## 1. Architectural Layout (`backend/`)

To decouple Django from brittle project-naming conventions and eliminate prefix pollution, the backend directory is partitioned into a dedicated `config/` orchestration folder and an `apps/` domain logic package:

```
backend/
├── manage.py                   # Root management utility bound to 'config.settings'
├── requirements.txt            # Python dependencies (django-environ, whitenoise, etc.)
├── .env                        # Local secret overrides (never committed to VCS)
├── config/                     # Core project configuration namespace
│   ├── __init__.py             # Namespace initializer
│   ├── settings.py             # 12-factor settings powered by django-environ
│   ├── urls.py                 # Root routing table & healthcheck probe
│   ├── wsgi.py                 # Production WSGI entrypoint for Gunicorn
│   └── asgi.py                 # Production ASGI entrypoint for Uvicorn / Channels
└── apps/                       # Modular domain business applications (injected into sys.path)
    ├── __init__.py             # apps namespace marker
    ├── users/                  # Example domain application
    │   ├── __init__.py
    │   ├── admin.py
    │   ├── apps.py             # Name: 'users' (canonical name, NOT 'apps.users')
    │   ├── models.py
    │   ├── serializers.py
    │   ├── views.py
    │   ├── urls.py
    │   └── migrations/
    └── catalog/                # Example domain application
        ├── ...
```

---

## 2. Dynamic Syspath Injection & Clean Scaffolding

### 2.1 Syspath Mechanism
In `config/settings.py`, the `apps/` directory is prepended to `sys.path`:
```python
sys.path.insert(0, os.path.join(BASE_DIR, "apps"))
```
For full architectural rationale, consult the technical reference: [`syspath-resolution.md`](./references/syspath-resolution.md).

### 2.2 Scaffolding an Application inside `apps/`
When adding a new domain app to `apps/`, adhere strictly to these rules:

1. **Generation Command**:
   Execute `startapp` targeting the destination subdirectory:
   ```bash
   python manage.py startapp <app_name> apps/<app_name>
   ```

2. **Canonical `AppConfig`**:
   Verify `apps/<app_name>/apps.py` declares the direct, un-prefixed name:
   ```python
   from django.apps import AppConfig

   class CatalogConfig(AppConfig):
       default_auto_field = "django.db.models.BigAutoField"
       name = "catalog"  # DO NOT use 'apps.catalog'
       verbose_name = "Product Catalog"
   ```

3. **Settings Registration**:
   Register in `config/settings.py` under `LOCAL_APPS`:
   ```python
   LOCAL_APPS = [
       "catalog.apps.CatalogConfig",
   ]
   ```

4. **Direct Import Syntax**:
   Always import models, serializers, and services directly without prefix:
   ```python
   # Correct:
   from catalog.models import Product
   from users.services import UserService

   # Strictly Prohibited:
   from apps.catalog.models import Product
   ```

---

## 3. AI Guardrails & Anti-Patterns

- **Anti-Pattern 1: Placing WhiteNoise below Session or Auth Middleware**
  - *Rule*: `whitenoise.middleware.WhiteNoiseMiddleware` MUST sit immediately below `django.middleware.security.SecurityMiddleware`.
  - *Risk*: Placing WhiteNoise after `SessionMiddleware` or `AuthenticationMiddleware` forces Django to initialize sessions and authenticate database users for every static asset request (CSS, JS, images), degrading throughput and leaking session cookies.

- **Anti-Pattern 2: Hardcoding `SECRET_KEY` or Insecure Production Fallbacks**
  - *Rule*: In production (`DEBUG=False`), missing `SECRET_KEY` MUST raise a fatal exception during startup.
  - *Risk*: A hardcoded or deterministic `SECRET_KEY` completely compromises cryptographic signing, CSRF protection, and password reset tokens.

- **Anti-Pattern 3: Omitting `sys.path` Injection for `apps/`**
  - *Rule*: Never create applications inside `apps/` without injecting `apps/` into `sys.path`.
  - *Risk*: Causes model registry duplicate collision (`RuntimeError: Conflicting 'model' in application`), fragmented migration graphs, and serialization bugs.

- **Anti-Pattern 4: Blindly appending non-existent folders to `STATICFILES_DIRS`**
  - *Rule*: Always verify folder existence before appending (`if (BASE_DIR / 'assets').is_dir(): ...`).
  - *Risk*: Django crashes on startup during `collectstatic` or `runserver` if a configured directory in `STATICFILES_DIRS` does not physically exist on disk.

---

## 4. Bundled Resource Templates

The following production-ready templates are available in [`resources/`](./resources):

- [`settings.py`](./resources/settings.py): Decoupled 12-factor configuration with typed `django-environ`, WhiteNoise storage, secure cookie flags, and dynamic origin handling.
- [`manage.py`](./resources/manage.py): Standard management script bound to `config.settings`.
- [`wsgi.py`](./resources/wsgi.py): Production WSGI handler bound to `config.settings`.
- [`asgi.py`](./resources/asgi.py): Production ASGI handler bound to `config.settings`.
- [`urls.py`](./resources/urls.py): Root URL dispatcher including the `/api/health/` probe endpoint.
- [`apps_init.py`](./resources/apps_init.py): Apps package marker documentation.

---

## 5. Agent Scaffolding Procedure

When setting up or restructuring a Django project using this architecture:

1. **Create Base Structure**:
   ```bash
   mkdir -p backend/config backend/apps
   ```
2. **Deploy Configuration**:
   - Copy [`resources/manage.py`](./resources/manage.py) to `backend/manage.py`.
   - Copy [`resources/settings.py`](./resources/settings.py) to `backend/config/settings.py`.
   - Copy [`resources/urls.py`](./resources/urls.py) to `backend/config/urls.py`.
   - Copy [`resources/wsgi.py`](./resources/wsgi.py) to `backend/config/wsgi.py`.
   - Copy [`resources/asgi.py`](./resources/asgi.py) to `backend/config/asgi.py`.
   - Copy [`resources/apps_init.py`](./resources/apps_init.py) to `backend/apps/__init__.py`.
   - Create empty `backend/config/__init__.py`.

3. **Verify Dependencies**:
   Ensure `backend/requirements.txt` contains:
   ```
   Django>=5.0,<5.2
   django-environ>=0.11.2
   whitenoise[brotli]>=6.6.0
   djangorestframework>=3.15.1
   django-cors-headers>=4.3.1
   ```

4. **Verify Health Endpoint**:
   Confirm `/api/health/` returns `{"status": "healthy", "environment": ...}` with HTTP 200.
