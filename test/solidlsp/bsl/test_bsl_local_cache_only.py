"""
Local-cache-only BSL tests (no bsl-language-server.jar).

These construct BSLLanguageServer directly and exercise the local parser/cache path.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from solidlsp.bsl_cache import BSLCache
from solidlsp.bsl_parser import BSLParser
from solidlsp.language_servers.bsl_language_server import BSLLanguageServer, LocalOnlyLanguageServerInterface
from solidlsp.ls_config import LanguageServerConfig, LanguageServerId
from solidlsp.ls_utils import SymbolUtils
from solidlsp.settings import SolidLSPSettings

REPO = Path(__file__).resolve().parents[2] / "resources" / "repos" / "bsl" / "test_repo"


@pytest.fixture()
def bsl_ls(tmp_path: Path) -> BSLLanguageServer:
    """Copy the BSL fixture repo and start a local-only language server."""
    repo = tmp_path / "repo"
    shutil.copytree(REPO, repo, ignore=shutil.ignore_patterns("__pycache__", ".git"))
    project_data = tmp_path / "project_data"
    project_data.mkdir()
    config = LanguageServerConfig(ls_id=LanguageServerId.BSL, ignored_paths=[])
    settings = SolidLSPSettings(
        project_data_path=str(project_data),
        ls_specific_settings={"bsl": {"cache_update_start_delay_seconds": 0}},
    )
    ls = BSLLanguageServer(config, str(repo), settings)
    ls.start()
    # Background cache update must finish before assertions (indexing is async).
    if ls._cache_update_thread is not None:
        ls._cache_update_thread.join(timeout=120)
        assert not ls._cache_update_thread.is_alive(), "BSL cache update did not finish in time"
    try:
        yield ls
    finally:
        ls.stop()


@pytest.mark.bsl
class TestBSLLocalCacheOnly:
    def test_uses_local_only_interface(self, bsl_ls: BSLLanguageServer) -> None:
        assert isinstance(bsl_ls.server, LocalOnlyLanguageServerInterface)
        assert bsl_ls.is_running()

    def test_parser_finds_common_module_symbols(self) -> None:
        parser = BSLParser()
        source = (REPO / "CommonModule.bsl").read_text(encoding="utf-8")
        result = parser.parse(source)
        names = {m.name for m in result.methods}
        assert "ВывестиСообщение" in names
        assert "ПолучитьПриветствие" in names

    def test_cache_indexes_methods(self, bsl_ls: BSLLanguageServer) -> None:
        assert isinstance(bsl_ls._local_cache, BSLCache)
        assert len(bsl_ls._local_cache.methods) > 0
        assert len(bsl_ls._document_symbols_cache) > 0

    def test_symbol_tree_contains_expected_names(self, bsl_ls: BSLLanguageServer) -> None:
        symbols = bsl_ls.request_full_symbol_tree()
        assert SymbolUtils.symbol_tree_contains_name(symbols, "ВывестиСообщение")
        assert SymbolUtils.symbol_tree_contains_name(symbols, "Инициализировать")

    def test_document_symbols_common_module(self, bsl_ls: BSLLanguageServer) -> None:
        doc_symbols = bsl_ls.request_document_symbols("CommonModule.bsl")
        all_symbols, _ = doc_symbols.get_all_symbols_and_roots()
        names = [s.get("name") for s in all_symbols if s.get("name")]
        assert "ВывестиСообщение" in names
        assert "ПолучитьПриветствие" in names

    def test_main_bsl_symbols_if_present(self, bsl_ls: BSLLanguageServer) -> None:
        if not (Path(bsl_ls.repository_root_path) / "Main.bsl").exists():
            pytest.skip("Main.bsl fixture not present")
        doc_symbols = bsl_ls.request_document_symbols("Main.bsl")
        all_symbols, _ = doc_symbols.get_all_symbols_and_roots()
        names = [s.get("name") for s in all_symbols if s.get("name")]
        assert names, "Expected at least one symbol in Main.bsl"

    def test_no_jar_download_attempted(self, bsl_ls: BSLLanguageServer, tmp_path: Path) -> None:
        """Resources dir should not contain a downloaded bsl-language-server JAR after start."""
        resources = Path(bsl_ls._ls_resources_dir)
        jars = list(resources.rglob("bsl-language-server*.jar")) if resources.exists() else []
        assert jars == [], f"Unexpected JAR downloads: {jars}"
