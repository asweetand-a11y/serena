"""Enable BSL tests in this package.

Upstream disables BSL globally because the JAR-based server is slow and flaky.
This fork uses a local parser, so the package-level tests should run.
"""

from solidlsp.ls_config import LanguageServerId
from test.conftest import _disabled_language_servers

if LanguageServerId.BSL in _disabled_language_servers:
    _disabled_language_servers.remove(LanguageServerId.BSL)
