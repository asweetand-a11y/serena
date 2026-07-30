import os
from pathlib import Path

import pytest

from solidlsp import SolidLanguageServer
from solidlsp.ls_config import LanguageServerId
from solidlsp.ls_utils import SymbolUtils
from test.conftest import language_server_tests_enabled
from test.solidlsp.conftest import format_symbol_for_assert, has_malformed_name, request_all_symbols

pytestmark = pytest.mark.skipif(
    not language_server_tests_enabled(LanguageServerId.BSL), reason="BSL tests are disabled (niche, slow and flaky)"
)


@pytest.mark.bsl
class TestBSLLanguageServer:
    @pytest.mark.parametrize("language_server", [LanguageServerId.BSL], indirect=True)
    @pytest.mark.parametrize("repo_path", [LanguageServerId.BSL], indirect=True)
    def test_ls_is_running(self, language_server: SolidLanguageServer, repo_path: Path) -> None:
        """Language server starts and attaches to the test repository."""
        assert language_server.is_running()
        assert Path(language_server.language_server.repository_root_path).resolve() == repo_path.resolve()

    @pytest.mark.parametrize("language_server", [LanguageServerId.BSL], indirect=True)
    def test_find_symbol(self, language_server: SolidLanguageServer) -> None:
        symbols = language_server.request_full_symbol_tree()
        assert SymbolUtils.symbol_tree_contains_name(symbols, "ВывестиСообщение"), "ВывестиСообщение not found in symbol tree"
        assert SymbolUtils.symbol_tree_contains_name(symbols, "ПолучитьПриветствие"), "ПолучитьПриветствие not found in symbol tree"
        assert SymbolUtils.symbol_tree_contains_name(symbols, "Инициализировать"), "Инициализировать not found in symbol tree"

    @pytest.mark.parametrize("language_server", [LanguageServerId.BSL], indirect=True)
    def test_document_symbols(self, language_server: SolidLanguageServer) -> None:
        doc_symbols = language_server.request_document_symbols("CommonModule.bsl")
        all_symbols, _ = doc_symbols.get_all_symbols_and_roots()
        names = [s.get("name") for s in all_symbols if s.get("name")]
        assert "ВывестиСообщение" in names, f"ВывестиСообщение not found in CommonModule.bsl symbols. Found: {names}"
        assert "ПолучитьПриветствие" in names, f"ПолучитьПриветствие not found in CommonModule.bsl symbols. Found: {names}"
        assert "ВызватьПриветствие" in names, f"ВызватьПриветствие not found in CommonModule.bsl symbols. Found: {names}"

    @pytest.mark.parametrize("language_server", [LanguageServerId.BSL], indirect=True)
    def test_full_symbol_tree_within_file(self, language_server: SolidLanguageServer) -> None:
        """Scoping the full-tree request to a single file returns that file's symbols."""
        symbols = language_server.request_full_symbol_tree(within_relative_path="ObjectModule.bsl")
        assert SymbolUtils.symbol_tree_contains_name(symbols, "Инициализировать"), (
            "Инициализировать not found in ObjectModule.bsl symbol tree"
        )
        assert SymbolUtils.symbol_tree_contains_name(symbols, "ПолучитьСостояние"), (
            "ПолучитьСостояние not found in ObjectModule.bsl symbol tree"
        )

    @pytest.mark.parametrize("language_server", [LanguageServerId.BSL], indirect=True)
    def test_find_references_within_file(self, language_server: SolidLanguageServer) -> None:
        # CommonModule.bsl (0-indexed):
        # line 2: Процедура ВывестиСообщение(Текст) Экспорт  <- declaration (name starts at col 10)
        # line 13: ВывестиСообщение(Сообщение);              <- internal call
        # This test asserts within-file resolution on a bare ``.bsl`` file (no surrounding
        # 1C project metadata). Cross-module resolution is exercised separately via the
        # dedicated ``src/`` fixture in ``test_find_references_across_files`` below.
        refs = language_server.request_references("CommonModule.bsl", line=2, column=10)
        assert refs, "Expected at least one reference to ВывестиСообщение"
        file_names = [ref.get("relativePath", "") for ref in refs]
        assert any("CommonModule.bsl" in f for f in file_names), f"Expected self-reference in CommonModule.bsl, got: {file_names}"
        # the internal call is on line 13
        matching_lines = [ref["range"]["start"]["line"] for ref in refs if "CommonModule.bsl" in ref.get("relativePath", "")]
        assert 12 in matching_lines, f"Expected a reference on line 12 (0-indexed), got lines: {matching_lines}"

    @pytest.mark.parametrize("language_server", [LanguageServerId.BSL], indirect=True)
    def test_find_references_to_function_within_file(self, language_server: SolidLanguageServer) -> None:
        # CommonModule.bsl (0-indexed):
        # line 6: Функция ПолучитьПриветствие(Имя) Экспорт  <- declaration (name starts at col 8)
        # line 12: Сообщение = ПолучитьПриветствие("Мир");  <- internal call at col 16
        refs = language_server.request_references("CommonModule.bsl", line=6, column=8)
        assert refs, "Expected at least one reference to ПолучитьПриветствие"
        matching_lines = [ref["range"]["start"]["line"] for ref in refs if "CommonModule.bsl" in ref.get("relativePath", "")]
        assert 11 in matching_lines, f"Expected a reference on line 11 (0-indexed), got lines: {matching_lines}"

    # --- Cross-file reference resolution ---
    #
    # bsl-language-server links common modules across files only when the fixture ships
    # proper 1C Configuration metadata (``Configuration.xml`` + per-module ``.mdo`` /
    # ``Ext/Module.bsl`` layout). The ``src/`` subtree under the BSL test repo provides
    # a minimal-but-complete Designer-format dump for exactly this purpose. The two
    # tests below request references and the go-to-definition from the cross-module
    # call site ``ОбщийМодуль1.ВывестиСообщение(...)`` in ``ОбщийМодуль2``.

    _CROSS_REF_MODULE1 = os.path.join("src", "CommonModules", "ОбщийМодуль1", "Ext", "Module.bsl")
    _CROSS_REF_MODULE2 = os.path.join("src", "CommonModules", "ОбщийМодуль2", "Ext", "Module.bsl")

    @pytest.mark.parametrize("language_server", [LanguageServerId.BSL], indirect=True)
    def test_find_references_across_files(self, language_server: SolidLanguageServer) -> None:
        """``request_references`` from the declaration must include the cross-module call-site."""
        # ОбщийМодуль1 / Ext / Module.bsl (0-indexed):
        # line 2: Процедура ВывестиСообщение(Текст) Экспорт   <- declaration (name at col 10)
        # ОбщийМодуль2 / Ext / Module.bsl (0-indexed):
        # line 3: ОбщийМодуль1.ВывестиСообщение("Hello from CommonModule2");  <- cross-module call (col 17)
        refs = language_server.request_references(self._CROSS_REF_MODULE1, line=2, column=10)
        assert refs, "Expected at least one reference to ВывестиСообщение across modules"
        call_site_paths = [ref.get("relativePath", "") for ref in refs if "ОбщийМодуль2" in ref.get("relativePath", "")]
        assert call_site_paths, (
            f"Expected a cross-module reference from ОбщийМодуль2, got relativePaths: {[ref.get('relativePath', '') for ref in refs]}"
        )
        call_site_lines = [ref["range"]["start"]["line"] for ref in refs if "ОбщийМодуль2" in ref.get("relativePath", "")]
        assert 3 in call_site_lines, f"Expected a reference at ОбщийМодуль2/Module.bsl line 3, got lines: {call_site_lines}"

    @pytest.mark.parametrize("language_server", [LanguageServerId.BSL], indirect=True)
    def test_find_definition_across_files(self, language_server: SolidLanguageServer) -> None:
        """``request_definition`` from a cross-module call-site must resolve to the other module."""
        # cursor on "ВывестиСообщение" inside
        # ОбщийМодуль1.ВывестиСообщение("Hello from CommonModule2"); (line 3, col 17 — 0-indexed)
        definitions = language_server.request_definition(self._CROSS_REF_MODULE2, line=3, column=17)
        assert definitions, "Expected a cross-module definition for ВывестиСообщение"
        target_paths = [d.get("relativePath", "") for d in definitions]
        assert any("ОбщийМодуль1" in p for p in target_paths), f"Expected definition to resolve to ОбщийМодуль1, got: {target_paths}"
        target_lines = [d["range"]["start"]["line"] for d in definitions if "ОбщийМодуль1" in d.get("relativePath", "")]
        assert 2 in target_lines, f"Expected the definition to point at ОбщийМодуль1/Module.bsl line 2, got: {target_lines}"

    @pytest.mark.parametrize("language_server", [LanguageServerId.BSL], indirect=True)
    def test_bare_symbol_names(self, language_server: SolidLanguageServer) -> None:
        all_symbols = request_all_symbols(language_server)
        malformed = [s for s in all_symbols if has_malformed_name(s)]
        if malformed:
            pytest.fail(
                f"Found malformed symbols: {[format_symbol_for_assert(s) for s in malformed]}",
                pytrace=False,
            )


# ---------------------------------------------------------------------------
# Unit tests — no language server needed, always run regardless of Java
# ---------------------------------------------------------------------------


def test_bsl_filename_matcher() -> None:
    matcher = LanguageServerId.BSL.get_source_fn_matcher()
    assert matcher.is_relevant_filename("module.bsl")
    assert matcher.is_relevant_filename("script.os")
    assert not matcher.is_relevant_filename("module.py")


def test_bsl_enum_registration() -> None:
    assert LanguageServerId.BSL.value == "bsl"
    assert LanguageServerId.BSL.get_ls_class().__name__ == "BSLLanguageServer"


def test_bsl_local_only_interface_registration() -> None:
    """BSL uses LocalOnlyLanguageServerInterface instead of JAR DependencyProvider."""
    from solidlsp.language_servers.bsl_language_server import LocalOnlyLanguageServerInterface

    assert issubclass(LocalOnlyLanguageServerInterface, object)
    # JAR DependencyProvider API is intentionally absent in local-cache-only mode
    assert not hasattr(
        LanguageServerId.BSL.get_ls_class(),
        "DependencyProvider",
    ), "BSL must not expose JAR DependencyProvider in local-cache-only mode"
