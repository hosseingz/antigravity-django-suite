# Technical Reference: Dynamic Syspath Injection & Modular Apps Architecture

This reference outlines the architectural rationale for injecting `apps/` into `sys.path`, avoiding nested app imports, and decoupling Django's root configuration into a generic `config/` namespace.

---

## 1. Dynamic `sys.path` Injection

### 1.1 The Mechanism
In `backend/config/settings.py`:
```python
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Inject apps/ directory at the front of the Python module search path
sys.path.insert(0, os.path.join(BASE_DIR, 'apps'))
```

By placing `os.path.join(BASE_DIR, 'apps')` at index `0`, Python searches the `apps/` directory first before falling back to system-level site-packages or top-level project folders.

---

## 2. Rationale: Direct Imports vs. Prefix Pollution

### 2.1 The Prefix Pollution Trap (`apps.<app_name>`)
When developers store domain apps inside a subfolder (such as `apps/`) without adjusting `sys.path`, they are forced to reference the application with a prefix:
- In `INSTALLED_APPS`: `'apps.blog'`, `'apps.users'`, `'apps.orders'`
- In Python code: `from apps.blog.models import Post`
- In ForeignKeys: `models.ForeignKey('apps_blog.Post', ...)` or `models.ForeignKey('blog.Post', ...)`
- In migrations: Dependencies recorded as `('apps_blog', '0001_initial')` or varying inconsistently depending on whether an import accessed `apps.blog` or `blog`.

### 2.2 Critical Failure Modes of Nested Imports
1. **Serializer Model Registry Conflicts**:
   Django's `apps.get_model()` and DRF's serializer model mapping expect canonical application labels (`blog.Post`). When referenced as `apps.blog.Post`, Django can register duplicate application instances under both `apps.blog` and `blog`, causing model registry conflicts (`RuntimeError: Conflicting 'post' models in application 'blog'`).
2. **AppLabel Resolution in Foreign Keys & Migrations**:
   When `apps.blog` is declared in `INSTALLED_APPS`, the default `app_label` may become `apps_blog` unless overridden in every `AppConfig`. If an engineer later renames or relocates the directory or uses `blog` directly, migration dependency graphs fracture, leading to unresolvable `NodeNotFoundError` errors during `migrate`.
3. **Circular Import Rigidity**:
   Direct imports (`from blog.models import Post`, `from users.services import UserService`) decouple the module logic from its physical location in the filesystem. Moving an app or extracting it into an isolated reusable package requires zero internal code refactoring.

### 2.3 Scaffolding Rules for Apps inside `apps/`
When generating a new application inside `apps/`:
```bash
cd backend
python manage.py startapp catalog apps/catalog
```
In `apps/catalog/apps.py`:
```python
from django.apps import AppConfig


class CatalogConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'catalog'  # Canonical name, NOT 'apps.catalog'
    verbose_name = 'Product Catalog'
```
In `config/settings.py`:
```python
INSTALLED_APPS = [
    # Core Django apps...
    # Third-party apps...
    # Local apps:
    'catalog.apps.CatalogConfig',  # Or simply 'catalog'
]
```

---

## 3. Generic `config/` Namespace Decoupling

### 3.1 The Problem with Project-Named Directories
Standard Django generators execute `django-admin startproject myproject .`, creating a configuration folder named `myproject/`.
- If the project is renamed, repository refactoring touches `manage.py`, `wsgi.py`, `asgi.py`, `Dockerfile`, Gunicorn commands, Celery definitions, and test suites.
- Containerized workflows, CI scripts, and automation templates become coupled to arbitrary client or product names.

### 3.2 Standardization on `config/`
All templates in `antigravity-django-suite` decouple configuration from the project name by standardizing on `config/`:
- `manage.py` sets:
  ```python
  os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
  ```
- `wsgi.py` sets:
  ```python
  os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
  ```
- `asgi.py` sets:
  ```python
  os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
  ```
- Container execution (`Dockerfile` / Gunicorn):
  ```bash
  gunicorn config.wsgi:application --bind 0.0.0.0:8000
  ```
- Asynchronous Celery runner:
  ```bash
  celery -A config worker -l info
  ```

This standardization enables zero-modification reuse of all deployment, orchestration, and Docker tooling across diverse domain applications.
