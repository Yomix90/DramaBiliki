import os
import tempfile

# Configure an isolated environment BEFORE the bridge modules are imported:
# tests must never touch the real database, media folder or source site.
_tmp = tempfile.mkdtemp(prefix="dramabiliki-tests-")
os.environ.update({
    "APP_ENV": "test",
    "DATA_DIR": _tmp,
    "DATABASE_URL": f"sqlite:///{os.path.join(_tmp, 'test.db')}",
    "MEDIA_DIR": os.path.join(_tmp, "media"),
    "COVERS_DIR": os.path.join(_tmp, "media", "covers"),
    "ENABLE_SCHEDULER": "false",
    "ADMIN_USERNAME": "admin",
    "ADMIN_PASSWORD": "test-admin-password",
    "PUBLIC_BASE_URL": "",
})
