"""Site Health API route composition.

The route modules attach their paths to the single shared ``router`` at import
time, so the import order below IS the route-registration order. It must stay
``mutations -> pages -> projections -> events_exports`` to reproduce the
original single-module registration order: FastAPI matches first-registered
first, so the literal ``/site-crawls/url-preview`` has to precede
``/site-crawls/{crawl_id}``, and the published OpenAPI path order must not
move. The ``# isort: split`` markers stop ruff from alphabetising these four
statements into a different (behaviour-changing) order; the ``as`` aliases mark
them as intentional re-exports so no blanket ``noqa`` is needed.
"""

from .common import router as router

# isort: split
from . import mutations as mutations

# isort: split
from . import pages as pages

# isort: split
from . import projections as projections

# isort: split
from . import events_exports as events_exports
