import pytest

# Diagnostics require bsl-language-server.jar publishDiagnostics.
# This fork runs BSL in local-parser/cache-only mode without the JAR.
pytestmark = pytest.mark.skip(reason="BSL local-cache-only mode: JAR diagnostics not used")
