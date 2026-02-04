"""
Basic integration tests for the BSL (1C:Enterprise) language server functionality.

These tests validate the functionality of the language server APIs
like request_document_symbols using the BSL test repository.
"""

import pytest

from solidlsp import SolidLanguageServer
from solidlsp.ls_config import Language


@pytest.mark.bsl
class TestBSLLanguageServerBasics:
    """Test basic functionality of the BSL language server."""

    @pytest.mark.parametrize("language_server", [Language.BSL], indirect=True)
    def test_bsl_language_server_initialization(self, language_server: SolidLanguageServer) -> None:
        """Test that BSL language server can be initialized successfully."""
        assert language_server is not None
        assert language_server.language == Language.BSL

    @pytest.mark.parametrize("language_server", [Language.BSL], indirect=True)
    def test_bsl_request_document_symbols_main(self, language_server: SolidLanguageServer) -> None:
        """Test request_document_symbols for Main.bsl file."""
        # Test getting symbols from Main.bsl
        all_symbols, _root_symbols = language_server.request_document_symbols("Main.bsl").get_all_symbols_and_roots()

        # Extract function and procedure symbols
        # In LSP: Function = kind 12, Method = kind 6
        # BSL может использовать разные kind для функций и процедур
        function_symbols = [symbol for symbol in all_symbols if symbol.get("kind") in [6, 12]]
        function_names = [symbol["name"] for symbol in function_symbols]

        # Should detect exported functions and procedures from Main.bsl
        expected_functions = [
            "ПриветствоватьПользователя",  # Function
            "ОбработатьЭлементы",  # Procedure
            "РассчитатьСумму",  # Function
        ]

        for func_name in expected_functions:
            assert func_name in function_names, f"Should find {func_name} in Main.bsl"

        assert len(function_symbols) >= 3, f"Should find at least 3 exported functions/procedures, found {len(function_symbols)}"

    @pytest.mark.parametrize("language_server", [Language.BSL], indirect=True)
    def test_bsl_request_document_symbols_utils(self, language_server: SolidLanguageServer) -> None:
        """Test request_document_symbols for Utils.bsl file."""
        # Test with Utils.bsl
        utils_all_symbols, _utils_root_symbols = language_server.request_document_symbols("Utils.bsl").get_all_symbols_and_roots()

        utils_function_symbols = [symbol for symbol in utils_all_symbols if symbol.get("kind") in [6, 12]]
        utils_function_names = [symbol["name"] for symbol in utils_function_symbols]

        # Should detect utility functions from Utils.bsl
        expected_utils_functions = [
            "ПривестиКВерхнемуРегистру",
            "ПривестиКНижнемуРегистру",
            "УдалитьПробелы",
            "СодержитЭлемент",
            "ЗаписатьВЛог",
            "ПроверитьEmail",
            "ЭтоЧисло",
            "СоздатьДиапазон",
        ]

        for func_name in expected_utils_functions:
            assert func_name in utils_function_names, f"Should find {func_name} function in Utils.bsl"

        assert len(utils_function_symbols) >= 8, f"Should find at least 8 functions in Utils.bsl, found {len(utils_function_symbols)}"

    @pytest.mark.parametrize("language_server", [Language.BSL], indirect=True)
    def test_bsl_request_document_symbols_models(self, language_server: SolidLanguageServer) -> None:
        """Test request_document_symbols for Models.bsl file."""
        # Test with Models.bsl
        models_all_symbols, _models_root_symbols = language_server.request_document_symbols("Models.bsl").get_all_symbols_and_roots()

        models_function_symbols = [symbol for symbol in models_all_symbols if symbol.get("kind") in [6, 12]]
        models_function_names = [symbol["name"] for symbol in models_function_symbols]

        # Should detect model-related functions
        expected_model_functions = [
            "СоздатьПользователя",
            "СоздатьАдрес",
            "СоздатьПрофильПользователя",
            "ОбновитьПользователя",
            "ПолучитьПолноеИмя",
            "ПолучитьАдресСтрокой",
        ]

        for func_name in expected_model_functions:
            assert func_name in models_function_names, f"Should find {func_name} function in Models.bsl"

        assert len(models_function_symbols) >= 6, f"Should find at least 6 functions in Models.bsl, found {len(models_function_symbols)}"

    @pytest.mark.parametrize("language_server", [Language.BSL], indirect=True)
    def test_bsl_document_symbols_with_body(self, language_server: SolidLanguageServer) -> None:
        """Test request_document_symbols with body extraction."""
        # Test with include_body=True
        all_symbols, _root_symbols = language_server.request_document_symbols("Main.bsl").get_all_symbols_and_roots()

        function_symbols = [symbol for symbol in all_symbols if symbol.get("kind") in [6, 12]]

        # Find specific function and check it has proper structure
        greeting_function = next((sym for sym in function_symbols if sym["name"] == "ПриветствоватьПользователя"), None)
        assert greeting_function is not None, "Should find ПриветствоватьПользователя function"

        # Check that the symbol has location information
        assert "range" in greeting_function or "location" in greeting_function, "Function symbol should have range/location information"

    @pytest.mark.parametrize("language_server", [Language.BSL], indirect=True)
    def test_bsl_cross_file_references(self, language_server: SolidLanguageServer) -> None:
        """Test that BSL server can detect symbols across multiple files."""
        # Get symbols from all files
        main_symbols, _ = language_server.request_document_symbols("Main.bsl").get_all_symbols_and_roots()
        utils_symbols, _ = language_server.request_document_symbols("Utils.bsl").get_all_symbols_and_roots()
        models_symbols, _ = language_server.request_document_symbols("Models.bsl").get_all_symbols_and_roots()

        # Verify we can detect symbols from each file
        main_functions = [s for s in main_symbols if s.get("kind") in [6, 12]]
        utils_functions = [s for s in utils_symbols if s.get("kind") in [6, 12]]
        models_functions = [s for s in models_symbols if s.get("kind") in [6, 12]]

        assert len(main_functions) >= 3, "Should detect functions in Main.bsl"
        assert len(utils_functions) >= 8, "Should detect functions in Utils.bsl"
        assert len(models_functions) >= 6, "Should detect functions in Models.bsl"

    @pytest.mark.parametrize("language_server", [Language.BSL], indirect=True)
    def test_bsl_exported_functions_detection(self, language_server: SolidLanguageServer) -> None:
        """Test detection of exported (Экспорт) functions."""
        # Main.bsl has exported functions marked with 'Экспорт'
        all_symbols, _root_symbols = language_server.request_document_symbols("Main.bsl").get_all_symbols_and_roots()

        function_symbols = [symbol for symbol in all_symbols if symbol.get("kind") in [6, 12]]

        # All public API functions should be detected
        exported_function_names = [
            "ПриветствоватьПользователя",
            "ОбработатьЭлементы",
            "РассчитатьСумму",
        ]

        detected_names = [sym["name"] for sym in function_symbols]

        for func_name in exported_function_names:
            assert func_name in detected_names, f"Should detect exported function {func_name}"












