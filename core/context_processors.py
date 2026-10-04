"""
Template context helpers.

`asset_version` puts a version stamp on the CSS and JS URLs, so a browser that
already has an old copy of style.css is forced to fetch the new one. Without
this, a returning user keeps seeing the previous design until they empty their
cache by hand.
"""

from pathlib import Path

from django.conf import settings

_ASSETS = [
    "core/static/core/style.css",
    "core/static/core/app.js",
    "core/static/core/purchase_form.js",
    "core/static/core/sale_form.js",
]
_cached_version = None


def _compute_version():
    newest = 0
    for relative in _ASSETS:
        path = Path(settings.BASE_DIR) / relative
        try:
            newest = max(newest, int(path.stat().st_mtime))
        except OSError:
            continue
    return str(newest)


def asset_version(request):
    """The newest modification time of our own CSS/JS, as a cache key."""
    global _cached_version

    # While developing, recompute on every request so edits show up at once.
    if settings.DEBUG:
        return {"asset_version": _compute_version()}

    if _cached_version is None:
        _cached_version = _compute_version()

    return {"asset_version": _cached_version}
