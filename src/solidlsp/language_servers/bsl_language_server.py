"""
Provides BSL (1C:Enterprise) specific instantiation of the LanguageServer class using bsl-language-server.
Contains various configurations and settings specific to BSL (1C) development.
"""

import hashlib
import logging
import os
import pathlib
import platform
import shutil
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from overrides import override

from solidlsp import ls_types
from solidlsp.ls import DocumentSymbols, SolidLanguageServer
from solidlsp.ls_config import LanguageServerConfig
from solidlsp.lsp_protocol_handler.lsp_types import InitializeParams
from solidlsp.lsp_protocol_handler.server import ProcessLaunchInfo
from solidlsp.ls_utils import TextUtils
from solidlsp.settings import SolidLSPSettings

log = logging.getLogger(__name__)


class BSLLanguageServer(SolidLanguageServer):
    """
    Provides BSL (1C:Enterprise) specific instantiation of the LanguageServer class using bsl-language-server.
    Contains various configurations and settings specific to BSL development.

    The BSL language server is automatically downloaded and updated from GitHub releases.
    On Windows, it uses a native .exe with embedded Java runtime.
    On Linux/macOS, it prefers native binaries, falling back to JAR with Java.

    All configuration is automatic - no manual setup required.
    """

    def __init__(self, config: LanguageServerConfig, repository_root_path: str, solidlsp_settings: SolidLSPSettings):
        """
        Creates a BSLLanguageServer instance. This class is not meant to be instantiated directly.
        Use LanguageServer.create() instead.
        """
        # Initialize parent class first to set up _custom_settings
        # We need to pass a dummy command initially, will set up properly after
        super().__init__(
            config,
            repository_root_path,
            ProcessLaunchInfo(cmd=["echo", "dummy"], cwd=repository_root_path),
            "bsl",
            solidlsp_settings,
        )
        
        # Теперь можем обратиться к _custom_settings и настроить реальную команду
        bsl_lsp_command = self._setup_runtime_dependencies(config, solidlsp_settings)
        # Важно: обновляем актуальный launch info, который использует хендлер при старте
        self.server.process_launch_info = ProcessLaunchInfo(cmd=bsl_lsp_command, cwd=repository_root_path)
        
        # Таймауты запросов: будет установлен через set_request_timeout(timeout) в SolidLanguageServer.create()
        # timeout берется из tool_timeout конфигурации (ls_timeout = tool_timeout - 5)

        self.server_ready = threading.Event()

        # Настройки локального парсера
        custom_settings = getattr(self, "_custom_settings", {}) or {}
        self.enable_hash_prefiltering = custom_settings.get("enable_hash_prefiltering", True)
        
        # Локальный парсер всегда включен
        self.file_read_parallelism = custom_settings.get("file_read_parallelism", 500)
        
        # In-memory кеш для локального парсера (всегда включен)
        # Результаты сохраняются в стандартный _document_symbols_cache
        from solidlsp.bsl_cache import BSLCache
        self._local_cache: BSLCache = BSLCache()
        # Кеш содержимого файлов для избежания повторного чтения при преобразовании
        self._file_content_cache: dict[str, str] = {}
        # Отслеживание уже преобразованных файлов для инкрементального преобразования
        self._converted_files: set[str] = set()
        
        # Для совместимости с существующим кодом (если используется где-то еще)
        self._processing_files: set[str] = set()
        self._indexing_lock = threading.Lock()
        
        # Статистика ошибок от BSL сервера
        self._error_stats: dict[str, int] = defaultdict(int)
        self._error_lock = threading.Lock()
        # Отслеживание критических ошибок для обработки в инструментах MCP
        self._has_critical_errors = False
        self._last_error_time: float | None = None
        self._error_wait_timeout = 60.0  # 60 секунд ожидания при ошибках

    def is_ignored_dirname(self, dirname: str) -> bool:
        """Define BSL-specific directories to ignore."""
        # Common 1C build and cache directories
        bsl_ignored_dirs = [
            "build",
            ".bsl-language-server",
            ".vscode",
            ".idea",
            "bin",
            "out",
            "oscript_modules",
            ".cursor",
            ".serena",
            ".git",
        ]
        return super().is_ignored_dirname(dirname) or dirname in bsl_ignored_dirs

    def _setup_runtime_dependencies(self, config: LanguageServerConfig, solidlsp_settings: SolidLSPSettings) -> list[str]:
        """
        Setup runtime dependencies for BSL Language Server and return the command to start the server.
        Now returns a fake command - bsl-language-server.exe is not used, we work with local cache only.
        """
        # Фейковый запуск - не запускаем bsl-language-server.exe
        # Используем команду, которая ничего не делает, но позволяет серверу "запуститься"
        log.info("BSL language server: using fake launch (local cache only mode)")
        
        # Возвращаем команду, которая просто завершается успешно
        # На Windows используем cmd /c exit 0, на Linux/macOS - true
        system = platform.system()
        if system == "Windows":
            cmd: list[str] = ["cmd", "/c", "exit", "0"]
        else:
            cmd = ["true"]
        
        return cmd

    @staticmethod
    def _get_initialize_params(repository_absolute_path: str) -> InitializeParams:
        """
        Returns the initialize params for the BSL Language Server.
        """
        root_uri = pathlib.Path(repository_absolute_path).as_uri()
        initialize_params = {
            "locale": "ru",  # BSL is primarily used in Russian-speaking countries
            "capabilities": {
                "textDocument": {
                    "synchronization": {
                        "didSave": True,
                        "dynamicRegistration": True,
                        "willSave": True,
                        "willSaveWaitUntil": True,
                    },
                    "completion": {
                        "dynamicRegistration": True,
                        "completionItem": {
                            "snippetSupport": True,
                            "commitCharactersSupport": True,
                            "documentationFormat": ["markdown", "plaintext"],
                            "deprecatedSupport": True,
                            "preselectSupport": True,
                        },
                    },
                    "definition": {"dynamicRegistration": True, "linkSupport": True},
                    "references": {"dynamicRegistration": True},
                    "documentSymbol": {
                        "dynamicRegistration": True,
                        "hierarchicalDocumentSymbolSupport": True,
                        "symbolKind": {"valueSet": list(range(1, 27))},
                    },
                    "hover": {"dynamicRegistration": True, "contentFormat": ["markdown", "plaintext"]},
                    "signatureHelp": {"dynamicRegistration": True},
                    "codeAction": {
                        "dynamicRegistration": True,
                        "codeActionLiteralSupport": {
                            "codeActionKind": {
                                "valueSet": [
                                    "quickfix",
                                    "refactor",
                                    "refactor.extract",
                                    "refactor.inline",
                                    "refactor.rewrite",
                                    "source",
                                    "source.organizeImports",
                                ]
                            }
                        },
                    },
                    "formatting": {"dynamicRegistration": True},
                    "rangeFormatting": {"dynamicRegistration": True},
                    "rename": {"dynamicRegistration": True, "prepareSupport": True},
                    "publishDiagnostics": {
                        "relatedInformation": True,
                        "versionSupport": False,
                        "tagSupport": {"valueSet": [1, 2]},
                    },
                },
                "workspace": {
                    "workspaceFolders": True,
                    "didChangeConfiguration": {"dynamicRegistration": True},
                    "symbol": {"dynamicRegistration": True, "symbolKind": {"valueSet": list(range(1, 27))}},
                    "executeCommand": {"dynamicRegistration": True},
                    "applyEdit": True,
                    "workspaceEdit": {
                        "documentChanges": True,
                        "resourceOperations": ["create", "rename", "delete"],
                    },
                },
            },
            "processId": os.getpid(),
            "rootPath": repository_absolute_path,
            "rootUri": root_uri,
            "workspaceFolders": [
                {
                    "uri": root_uri,
                    "name": os.path.basename(repository_absolute_path),
                }
            ],
        }
        return initialize_params  # type: ignore

    def _start_server(self) -> None:
        """
        Starts the BSL Language Server in local cache only mode.
        Since we're using only the local cache, we don't need to start a real LSP process.
        Always checks and updates the cache on startup.
        """
        log.info("BSL Language Server: Starting in local cache only mode (no LSP process)")
        
        # Mark server as started (required by base class)
        # We don't actually start a process, but we need to mark it as started
        # to satisfy the base class requirements
        
        # Set completions as available (we can provide completions from local cache if needed)
        self.completions_available.set()
        
        # Always check and update cache on startup (regardless of cache state)
        try:
            log.info("BSL Language Server: Checking and updating cache...")
            
            # 1. Find all BSL files
            all_bsl_files = self._find_all_bsl_files()
            log.info(f"BSL Language Server: Found {len(all_bsl_files)} BSL files in project")
            
            if not all_bsl_files:
                log.info("BSL Language Server: No BSL files found, skipping cache update")
            else:
                # 2. Find files that need indexing (new or changed)
                files_to_index = self._find_files_to_index(all_bsl_files)
                
                if files_to_index:
                    log.info(f"BSL Language Server: Indexing {len(files_to_index)} files (new or changed)")
                    
                    # 3. Index files using existing method
                    def save_cache_callback():
                        try:
                            self.save_cache()
                        except Exception as e:
                            log.warning(f"Failed to save cache during indexing: {e}")
                    
                    results = self._index_files_with_local_parser(files_to_index, save_cache_callback)
                    
                    # Check for errors
                    error_count = sum(1 for r in results.values() if r is not None)
                    if error_count > 0:
                        log.warning(f"BSL Language Server: {error_count} files failed to index")
                    
                    # 4. Convert local cache to DocumentSymbols (only new files)
                    try:
                        self._convert_local_cache_to_document_symbols(only_new_files=True)
                    except Exception as e:
                        log.warning(f"Failed to convert local cache to DocumentSymbols: {e}")
                    
                    log.info(f"BSL Language Server: Successfully indexed {len(files_to_index) - error_count} files")
                else:
                    log.info("BSL Language Server: All files are up to date, no indexing needed")
                
                # 5. Remove deleted files from cache
                try:
                    removed_count = self._remove_deleted_files_from_cache(all_bsl_files)
                    if removed_count > 0:
                        log.info(f"BSL Language Server: Removed {removed_count} deleted files from cache")
                except Exception as e:
                    log.warning(f"Failed to remove deleted files from cache: {e}")
                
                # 6. Save cache
                try:
                    self.save_cache()
                    log.info("BSL Language Server: Cache saved successfully")
                except Exception as e:
                    log.warning(f"Failed to save cache: {e}")
        
        except Exception as e:
            log.error(f"Error during cache update: {e}", exc_info=True)
            # Don't fail server startup if cache update fails
        
        # Mark server as ready immediately since we don't need to wait for LSP initialization
        log.info("BSL Language Server: Local cache mode ready")
        self.server_ready.set()

    def _find_all_bsl_files(self) -> list[str]:
        """
        Рекурсивно собирает все BSL файлы в проекте.
        
        :return: Список относительных путей к .bsl файлам (нормализованных с '/')
        """
        bsl_files: list[str] = []
        
        for root, dirs, files in os.walk(self.repository_root_path):
            # Фильтруем игнорируемые директории
            dirs[:] = [d for d in dirs if not self.is_ignored_dirname(d)]
            
            for file in files:
                # Собираем только .bsl файлы (не .os!)
                if not file.endswith('.bsl'):
                    continue
                
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, self.repository_root_path)
                
                # Нормализуем путь для Windows (заменяем \ на /)
                rel_path = rel_path.replace('\\', '/')
                
                # Проверяем, не игнорируется ли файл
                if self.is_ignored_path(rel_path):
                    continue
                
                bsl_files.append(rel_path)
        
        return bsl_files

    def _find_files_to_index(self, all_files: list[str]) -> list[str]:
        """
        Определяет файлы, которые нужно проиндексировать (новые или измененные).
        
        :param all_files: Список всех BSL файлов в проекте
        :return: Список файлов для индексации
        """
        files_to_index: list[str] = []
        skipped_count = 0
        
        for file_path in all_files:
            try:
                # Вычисляем хеш файла
                file_hash = self._compute_file_hash(file_path)
                
                if not file_hash:
                    # Если не удалось вычислить хеш, считаем файл измененным
                    log.debug(f"Could not compute hash for {file_path}, will index it")
                    files_to_index.append(file_path)
                    continue
                
                # Проверяем, нужно ли индексировать файл
                if self.enable_hash_prefiltering:
                    # Если включена предварительная фильтрация, проверяем кеш
                    if self._is_file_cached(file_path, file_hash):
                        # Файл уже в кеше с правильным хешем, пропускаем
                        skipped_count += 1
                        continue
                
                # Файл новый или измененный, добавляем в список для индексации
                files_to_index.append(file_path)
            
            except Exception as e:
                # При ошибке считаем файл измененным
                log.debug(f"Error checking file {file_path}: {e}, will index it")
                files_to_index.append(file_path)
        
        if skipped_count > 0:
            log.info(f"BSL Language Server: Skipped {skipped_count} unchanged files (hash prefiltering enabled)")
        
        return files_to_index

    def _remove_deleted_files_from_cache(self, existing_files: list[str]) -> int:
        """
        Удаляет из кеша файлы, которых больше нет в файловой системе.
        
        :param existing_files: Список файлов, которые существуют в файловой системе
        :return: Количество удаленных файлов
        """
        existing_files_set = set(existing_files)
        removed_count = 0
        
        # Создаем копию ключей кеша, чтобы не изменять словарь во время итерации
        cache_keys = list(self._document_symbols_cache.keys())
        
        for cache_key in cache_keys:
            # Обрабатываем оба формата ключа: строка или tuple
            if isinstance(cache_key, tuple):
                relative_file_path = cache_key[0]
            else:
                relative_file_path = cache_key
            
            # Проверяем, существует ли файл
            if relative_file_path not in existing_files_set:
                # Файл удален, удаляем из кеша
                try:
                    # Удаляем из document_symbols_cache
                    del self._document_symbols_cache[cache_key]
                    self._document_symbols_cache_is_modified = True
                    
                    # Удаляем из raw_document_symbols_cache
                    if relative_file_path in self._raw_document_symbols_cache:
                        del self._raw_document_symbols_cache[relative_file_path]
                        self._raw_document_symbols_cache_is_modified = True
                    
                    # Удаляем из local_cache
                    if self._local_cache is not None:
                        self._local_cache.remove_file_data(relative_file_path)
                    
                    # Удаляем из converted_files
                    self._converted_files.discard(relative_file_path)
                    
                    # Удаляем из file_content_cache
                    self._file_content_cache.pop(relative_file_path, None)
                    
                    removed_count += 1
                    log.debug(f"Removed deleted file from cache: {relative_file_path}")
                
                except Exception as e:
                    log.warning(f"Failed to remove deleted file {relative_file_path} from cache: {e}")
        
        return removed_count

    @override
    def is_running(self) -> bool:
        """
        Check if the BSL language server is running.
        In local cache only mode, we return True if server_started is True,
        since we don't have a real process to check.
        """
        # In local cache only mode, we don't have a real process,
        # so we check if the server was marked as started
        return self.server_started

    def _classify_error(self, message: str) -> str:
        """
        Классифицирует ошибку по ключевым словам для статистики.
        
        :param message: Текст сообщения об ошибке
        :return: Категория ошибки
        """
        message_lower = message.lower()
        
        if "can't read file" in message_lower or "it's broken" in message_lower:
            return "File read errors"
        elif "can't execute permission request" in message_lower or "permission" in message_lower:
            return "Permission errors"
        elif "can't convert" in message_lower or "conversion" in message_lower:
            return "Conversion errors"
        elif "unknown form element type" in message_lower:
            return "Unknown form element type"
        elif "error" in message_lower:
            return "General errors"
        elif "warning" in message_lower:
            return "Warnings"
        else:
            return "Other errors/warnings"

    def get_error_statistics(self) -> dict[str, int]:
        """
        Возвращает статистику ошибок, собранных от BSL сервера.
        
        :return: Словарь с категориями ошибок и их количеством
        """
        with self._error_lock:
            return dict(self._error_stats)

    def request_document_symbols(self, relative_file_path: str, file_buffer=None):
        """
        Использует стандартную синхронную обработку через базовый класс.
        """
        return super().request_document_symbols(relative_file_path, file_buffer)

    def request_full_symbol_tree(self, within_relative_path: str | None = None) -> list[ls_types.UnifiedSymbolInformation]:
        """
        Оптимизированная версия для BSL: использует кеш напрямую вместо обхода файловой системы.
        Это значительно быстрее, когда кеш уже создан.
        """
        from pathlib import Path
        
        # Если указан конкретный файл, используем стандартную реализацию
        # Пустая строка означает глобальный поиск, обрабатываем как None
        if within_relative_path is not None and within_relative_path != "":
            # Обрабатываем как абсолютный, так и относительный путь
            path_obj = Path(within_relative_path)
            if path_obj.is_absolute():
                # Если передан абсолютный путь, проверяем, что он находится внутри проекта
                try:
                    relative_path = str(path_obj.relative_to(Path(self.repository_root_path)))
                    within_abs_path = str(path_obj.resolve())
                except ValueError:
                    # Если путь не находится внутри проекта, используем как есть
                    within_abs_path = str(path_obj.resolve())
                    relative_path = within_relative_path
            else:
                # Если передан относительный путь, преобразуем в абсолютный
                within_abs_path = os.path.join(self.repository_root_path, within_relative_path)
                relative_path = within_relative_path
            
            if not os.path.exists(within_abs_path):
                raise FileNotFoundError(f"File or directory not found: {within_abs_path}")
            if os.path.isfile(within_abs_path):
                if self.is_ignored_path(relative_path):
                    log.error("You passed a file explicitly, but it is ignored. This is probably an error. File: %s", relative_path)
                    return []
                else:
                    root_nodes = self.request_document_symbols(relative_path).root_symbols
                    return root_nodes
        
        # Используем кеш напрямую для построения дерева символов
        log.debug("BSL: Building symbol tree from cache (optimized path)")
        log.debug(f"BSL: Cache directory: {self.cache_dir}")
        log.debug(f"BSL: Cache file: {self.cache_dir / self.DOCUMENT_SYMBOL_CACHE_FILENAME}")
        log.debug(f"BSL: Cache file exists: {(self.cache_dir / self.DOCUMENT_SYMBOL_CACHE_FILENAME).exists()}")
        log.debug(f"BSL: Number of entries in _document_symbols_cache: {len(self._document_symbols_cache)}")
        
        # Выводим первые несколько ключей для диагностики
        sample_keys = list(self._document_symbols_cache.keys())[:5]
        log.debug(f"BSL: Sample cache keys (first 5): {sample_keys}")
        for key in sample_keys:
            log.debug(f"BSL:   - Key type: {type(key)}, value: {key}")
        
        # Собираем все файлы из кеша
        cached_files: dict[str, tuple[str, DocumentSymbols]] = {}
        ignored_count = 0
        filtered_by_path_count = 0
        
        for cache_key, (file_hash, document_symbols) in self._document_symbols_cache.items():
            # Обрабатываем оба формата ключа: строка или tuple (для обратной совместимости)
            if isinstance(cache_key, tuple):
                # Старый формат: (relative_file_path, None)
                relative_file_path = cache_key[0]
            else:
                # Новый формат: relative_file_path (строка)
                relative_file_path = cache_key
            
            # Проверяем, не игнорируется ли путь
            if self.is_ignored_path(relative_file_path):
                ignored_count += 1
                # Логируем только первые 5 игнорируемых файлов, чтобы не засорять логи
                if ignored_count <= 5:
                    log.debug(f"BSL: Ignoring cached file: {relative_file_path}")
                continue
            
            # Фильтруем по within_relative_path, если указан (для директории)
            # Пустая строка "" означает поиск во всем проекте, не фильтруем
            if within_relative_path is not None and within_relative_path != "":
                try:
                    rel_path = Path(relative_file_path)
                    within_path = Path(within_relative_path)
                    
                    # Если within_path абсолютный, преобразуем его в относительный для сравнения
                    if within_path.is_absolute():
                        try:
                            within_path = within_path.relative_to(Path(self.repository_root_path))
                        except ValueError:
                            # Если путь не находится внутри проекта, пропускаем фильтрацию
                            pass
                    
                    # Проверяем, что файл находится внутри указанной директории
                    if not (str(rel_path).startswith(str(within_path) + os.sep) or 
                            str(rel_path) == str(within_path) or
                            str(rel_path).startswith(str(within_path))):
                        filtered_by_path_count += 1
                        log.debug(f"BSL: Filtered out by within_relative_path: {relative_file_path} (within: {within_relative_path})")
                        continue
                except Exception as e:
                    log.debug(f"BSL: Error filtering path {relative_file_path}: {e}")
                    continue
            
            cached_files[relative_file_path] = (file_hash, document_symbols)
        
        log.debug(f"BSL: Processed {len(self._document_symbols_cache)} cache entries: {len(cached_files)} added, {ignored_count} ignored, {filtered_by_path_count} filtered by path")
        
        if not cached_files:
            log.debug("BSL: No cached files found, falling back to standard implementation")
            return super().request_full_symbol_tree(within_relative_path=within_relative_path)
        
        # Группируем файлы по директориям
        directory_structure: dict[str, list[ls_types.UnifiedSymbolInformation]] = {}
        
        for relative_file_path, (file_hash, document_symbols) in cached_files.items():
            # Получаем директорию файла
            file_path_obj = Path(relative_file_path)
            dir_path = str(file_path_obj.parent) if file_path_obj.parent != Path(".") else "."
            
            # Получаем содержимое файла для создания file_range
            # Используем кеш содержимого, если доступен
            file_content = ""
            if hasattr(self, '_file_content_cache') and relative_file_path in self._file_content_cache:
                file_content = self._file_content_cache[relative_file_path]
            else:
                # Читаем файл, если нет в кеше
                abs_path = os.path.join(self.repository_root_path, relative_file_path)
                try:
                    with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                        file_content = f.read()
                except Exception as e:
                    log.debug(f"Failed to read file {relative_file_path} for symbol tree: {e}")
                    continue
            
            # Создаем file_range
            file_range = self._get_range_from_file_content(file_content)
            
            # Получаем корневые символы из document_symbols
            file_root_nodes = document_symbols.root_symbols
            
            # Создаем символ файла
            file_symbol = ls_types.UnifiedSymbolInformation(  # type: ignore
                name=os.path.splitext(file_path_obj.name)[0],
                kind=ls_types.SymbolKind.File,
                range=file_range,
                selectionRange=file_range,
                location=ls_types.Location(
                    uri=str(pathlib.Path(os.path.join(self.repository_root_path, relative_file_path)).as_uri()),
                    range=file_range,
                    absolutePath=str(os.path.join(self.repository_root_path, relative_file_path)),
                    relativePath=relative_file_path,
                ),
                children=file_root_nodes,
            )
            
            # Устанавливаем parent для дочерних символов
            for child in file_root_nodes:
                child["parent"] = file_symbol
            
            # Добавляем в структуру директорий
            if dir_path not in directory_structure:
                directory_structure[dir_path] = []
            directory_structure[dir_path].append(file_symbol)
        
        # Строим иерархию директорий
        result: list[ls_types.UnifiedSymbolInformation] = []
        
        # Сортируем директории для правильного построения дерева
        sorted_dirs = sorted(directory_structure.keys(), key=lambda x: (x.count(os.sep), x))
        
        # Создаем словарь для быстрого доступа к символам директорий
        dir_symbols: dict[str, ls_types.UnifiedSymbolInformation] = {}
        
        for dir_path in sorted_dirs:
            file_symbols = directory_structure[dir_path]
            
            # Создаем символы для всех родительских директорий, если их еще нет
            current_path = dir_path
            parent_dir_symbol: ls_types.UnifiedSymbolInformation | None = None
            
            while current_path != ".":
                if current_path not in dir_symbols:
                    # Проверяем, не игнорируется ли директория
                    if self.is_ignored_path(current_path):
                        break
                    
                    dir_path_obj = Path(current_path)
                    dir_abs_path = os.path.join(self.repository_root_path, current_path)
                    
                    dir_symbol = ls_types.UnifiedSymbolInformation(  # type: ignore
                        name=dir_path_obj.name if current_path != "." else os.path.basename(self.repository_root_path),
                        kind=ls_types.SymbolKind.Package,
                        location=ls_types.Location(
                            uri=str(pathlib.Path(dir_abs_path).as_uri()),
                            range={"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
                            absolutePath=dir_abs_path,
                            relativePath=current_path,
                        ),
                        children=[],
                    )
                    
                    if parent_dir_symbol is not None:
                        dir_symbol["parent"] = parent_dir_symbol
                        parent_dir_symbol["children"].append(dir_symbol)
                    else:
                        result.append(dir_symbol)
                    
                    dir_symbols[current_path] = dir_symbol
                    parent_dir_symbol = dir_symbol
                else:
                    parent_dir_symbol = dir_symbols[current_path]
                    break
                
                # Переходим к родительской директории
                parent_path = str(Path(current_path).parent) if Path(current_path).parent != Path(".") else "."
                if parent_path == current_path:  # Защита от бесконечного цикла
                    break
                current_path = parent_path
            
            # Добавляем файлы в соответствующую директорию
            if dir_path == ".":
                # Файлы в корне
                result.extend(file_symbols)
            else:
                if dir_path in dir_symbols:
                    dir_symbol = dir_symbols[dir_path]
                    dir_symbol["children"].extend(file_symbols)
                    for file_symbol in file_symbols:
                        file_symbol["parent"] = dir_symbol
                else:
                    # Если директория не была создана (например, игнорируется), добавляем файлы в корень
                    result.extend(file_symbols)
        
        log.debug(f"BSL: Built symbol tree from cache with {len(cached_files)} files in {len(directory_structure)} directories")
        return result

    def _compute_file_hash(self, relative_file_path: str) -> str:
        """
        Быстро вычисляет хеш файла для проверки изменений.
        Используется для предварительной фильтрации файлов перед индексацией.
        Вычисляет хеш от нормализованного текста в UTF-8 (как в LSPFileBuffer.content_hash).
        
        :param relative_file_path: Относительный путь к файлу
        :return: MD5 хеш содержимого файла (нормализованного текста в UTF-8)
        """
        abs_path = os.path.join(self.repository_root_path, relative_file_path)
        try:
            # Читаем файл в текстовом режиме и нормализуем окончания строк
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            # Нормализуем окончания строк (как в LSPFileBuffer)
            content = content.replace("\r\n", "\n").replace("\r", "\n")
            # Вычисляем хеш от нормализованного текста в UTF-8 (как в LSPFileBuffer.content_hash)
            return hashlib.md5(content.encode("utf-8")).hexdigest()
        except Exception as e:
            log.debug(f"Failed to compute hash for {relative_file_path}: {e}")
            return ""

    def _is_file_cached(self, relative_file_path: str, file_hash: str) -> bool:
        """
        Проверяет, закеширован ли файл с данным хешем.
        
        :param relative_file_path: Относительный путь к файлу
        :param file_hash: Хеш содержимого файла
        :return: True если файл уже закеширован с таким хешем
        """
        cache_key = relative_file_path  # Ключ должен быть строкой, не tuple
        if cache_key in self._document_symbols_cache:
            cached_hash, _ = self._document_symbols_cache[cache_key]
            return cached_hash == file_hash
        return False

    def _index_files_batch(self, file_paths: list[str], save_cache_callback=None) -> dict[str, Exception | None]:
        """
        Индексирует список файлов.
        Если включен локальный парсер, использует его для массовой индексации (аналог FileQueue из vsc-language-1c-bsl).
        Иначе использует последовательную индексацию через LSP.
        
        Поддерживает предварительную фильтрацию по хешу для пропуска неизмененных файлов.
        
        :param file_paths: Список относительных путей к файлам для индексации
        :param save_cache_callback: Опциональный callback для сохранения кеша (вызывается периодически)
        :return: Словарь {file_path: Exception | None} с результатами индексации
        """
        # Всегда используем локальный парсер для массовой индексации
        return self._index_files_with_local_parser(file_paths, save_cache_callback)
        
        # Предварительная фильтрация по хешу (если включена)
        files_to_index = file_paths
        if self.enable_hash_prefiltering:
            files_to_index = []
            skipped_count = 0
            for file_path in file_paths:
                try:
                    file_hash = self._compute_file_hash(file_path)
                    if file_hash and self._is_file_cached(file_path, file_hash):
                        skipped_count += 1
                        continue
                    files_to_index.append(file_path)
                except Exception as e:
                    log.debug(f"Hash prefiltering failed for {file_path}: {e}, will index anyway")
                    files_to_index.append(file_path)
            
            if skipped_count > 0:
                log.info(f"Hash prefiltering: skipping {skipped_count} unchanged files, indexing {len(files_to_index)} files")
        
        if not files_to_index:
            log.info("All files are already cached, skipping indexing")
            return {fp: None for fp in file_paths}
        
        # Последовательная обработка через LSP (fallback, если локальный парсер отключен)
        results: dict[str, Exception | None] = {}
        total_files = len(files_to_index)
        total_files_original = len(file_paths)
        log.info(f"Starting sequential LSP indexing: {total_files} files to index (out of {total_files_original} total)")
        
        # Фиксированный размер батча для сохранения кеша (50 файлов)
        batch_size = 50
        
        for idx, file_path in enumerate(files_to_index, 1):
            # Проверяем, не обрабатывается ли файл уже (на случай параллельных вызовов)
            with self._indexing_lock:
                if file_path in self._processing_files:
                    log.debug(f"Skipping {file_path} - already being processed")
                    results[file_path] = None
                    continue
                self._processing_files.add(file_path)
            
            try:
                super().request_document_symbols(file_path)
                results[file_path] = None
                
                # Логируем прогресс каждые 10 файлов или каждые 5%
                percent = (idx * 100) // total_files if total_files > 0 else 0
                if idx % 10 == 0 or percent % 5 == 0 or idx == total_files:
                    log.info(
                        f"Indexing progress: {idx}/{total_files} files scanned ({percent}%) "
                        f"[Total: {idx}/{total_files_original} files]"
                    )
                
                # Сохраняем кеш периодически
                if save_cache_callback and idx % batch_size == 0:
                    try:
                        save_cache_callback()
                        cache_percent = (idx * 100) // total_files if total_files > 0 else 0
                        log.info(
                            f"Cache updated: {cache_percent}% of index filled "
                            f"({idx}/{total_files} files indexed, {idx}/{total_files_original} total)"
                        )
                    except Exception as e:
                        log.warning(f"Failed to save cache: {e}")
                        
            except Exception as e:
                log.error(f"Failed to index {file_path}: {e}")
                results[file_path] = e
            finally:
                # Удаляем файл из множества обрабатываемых
                with self._indexing_lock:
                    self._processing_files.discard(file_path)
        
        # Добавляем пропущенные файлы в результаты
        for file_path in file_paths:
            if file_path not in results:
                results[file_path] = None
        
        final_percent = (len([r for r in results.values() if r is None]) * 100) // total_files if total_files > 0 else 100
        log.info(
            f"Indexing completed: {len([r for r in results.values() if r is None])}/{total_files} files indexed ({final_percent}%) "
            f"[Total: {len(results)}/{total_files_original} files processed]"
        )
        
        # Логируем статистику ошибок от BSL сервера, если они были
        error_stats = self.get_error_statistics()
        if error_stats:
            log.warning(f"BSL server errors/warnings during indexing: {', '.join(f'{category}: {count}' for category, count in error_stats.items())}")
        
        return results

    def _index_single_file(self, relative_file_path: str) -> Exception | None:
        """
        Индексирует один файл через LSP.
        Вызывает базовый метод напрямую, чтобы избежать рекурсии через переопределенный request_document_symbols.
        
        :param relative_file_path: Относительный путь к файлу
        :return: Exception если произошла ошибка, None если успешно
        """
        try:
            # Вызываем базовый метод напрямую, минуя переопределенный request_document_symbols
            SolidLanguageServer.request_document_symbols(self, relative_file_path)
            return None
        except Exception as e:
            log.error(f"Failed to index {relative_file_path}: {e}")
            return e
        finally:
            # Удаляем файл из множества обрабатываемых после завершения (успешного или с ошибкой)
            with self._indexing_lock:
                self._processing_files.discard(relative_file_path)

    def index_via_workspace_symbol(self, file_paths: list[str], save_cache_callback=None) -> dict[str, Exception | None]:
        """
        Индексирует файлы через workspace/symbol запрос для массовой индексации.
        Это может быть значительно быстрее, чем тысячи отдельных documentSymbol запросов.
        
        :param file_paths: Список относительных путей к файлам (для информации, не используется напрямую)
        :param save_cache_callback: Опциональный callback для сохранения кеша
        :return: Словарь {file_path: Exception | None} с результатами индексации
        """
        if not self.server_started:
            log.warning("Cannot use workspace/symbol indexing: server not started")
            return {fp: Exception("Server not started") for fp in file_paths}
        
        total_files = len(file_paths)
        log.info(f"Attempting workspace/symbol indexing for {total_files} files")
        
        try:
            # Пробуем получить все символы через workspace/symbol с пустым query
            # Некоторые LSP серверы возвращают все символы при пустом query
            workspace_symbols = self.request_workspace_symbol("")
            
            if workspace_symbols is None or len(workspace_symbols) == 0:
                log.warning("workspace/symbol returned empty result, falling back to documentSymbol")
                return {}
            
            log.info(f"Received {len(workspace_symbols)} symbols from workspace/symbol")
            
            # Группируем символы по файлам
            symbols_by_file: dict[str, list] = defaultdict(list)
            processed_files = set()
            
            for symbol in workspace_symbols:
                location = symbol.get("location", {})
                if isinstance(location, dict):
                    rel_path = location.get("relativePath")
                    if rel_path:
                        symbols_by_file[rel_path].append(symbol)
                        processed_files.add(rel_path)
            
            files_to_process = len(symbols_by_file)
            log.info(f"Grouped symbols into {files_to_process} files (out of {total_files} total)")
            
            # Преобразуем символы в формат DocumentSymbols и сохраняем в кеш
            results: dict[str, Exception | None] = {}
            processed_count = 0
            
            for rel_path, symbols in symbols_by_file.items():
                try:
                    # Вычисляем хеш файла
                    file_hash = self._compute_file_hash(rel_path)
                    if not file_hash:
                        log.warning(f"Could not compute hash for {rel_path}, skipping cache update")
                        results[rel_path] = Exception("Could not compute file hash")
                        continue
                    
                    # Открываем файл для получения содержимого
                    with self.open_file(rel_path) as file_data:
                        # Создаем DocumentSymbols из unified symbols
                        # workspace/symbol возвращает UnifiedSymbolInformation, которые уже в правильном формате
                        document_symbols = DocumentSymbols(symbols)
                        
                        # Сохраняем в кеш
                        cache_key = rel_path  # Ключ должен быть строкой, не tuple
                        self._document_symbols_cache[cache_key] = (file_hash, document_symbols)
                        self._document_symbols_cache_is_modified = True
                        
                        results[rel_path] = None
                        processed_count += 1
                        
                        # Логируем прогресс каждые 10 файлов или каждые 5%
                        percent = (processed_count * 100) // files_to_process if files_to_process > 0 else 0
                        if processed_count % 10 == 0 or percent % 5 == 0 or processed_count == files_to_process:
                            log.info(
                                f"Workspace/symbol indexing progress: {processed_count}/{files_to_process} files processed ({percent}%) "
                                f"[Total: {processed_count}/{total_files} files]"
                            )
                        
                        log.debug(f"Cached {len(symbols)} symbols for {rel_path}")
                        
                except Exception as e:
                    log.error(f"Failed to process symbols for {rel_path}: {e}")
                    results[rel_path] = e
                    processed_count += 1
            
            # Добавляем файлы, которые не были обработаны через workspace/symbol
            for file_path in file_paths:
                if file_path not in results:
                    results[file_path] = None  # Будет обработан через fallback
            
            # Сохраняем кеш после обработки
            if save_cache_callback:
                try:
                    save_cache_callback()
                    final_percent = (processed_count * 100) // files_to_process if files_to_process > 0 else 100
                    log.info(
                        f"Cache updated: {final_percent}% of index filled via workspace/symbol "
                        f"({processed_count}/{files_to_process} files indexed, {processed_count}/{total_files} total)"
                    )
                except Exception as e:
                    log.warning(f"Failed to save cache: {e}")
            
            final_percent = (processed_count * 100) // files_to_process if files_to_process > 0 else 100
            log.info(
                f"Workspace/symbol indexing completed: {processed_count}/{files_to_process} files processed ({final_percent}%) "
                f"[Total: {processed_count}/{total_files} files]"
            )
            
            # Логируем статистику ошибок от BSL сервера, если они были
            error_stats = self.get_error_statistics()
            if error_stats:
                log.warning(f"BSL server errors/warnings during workspace/symbol indexing: {', '.join(f'{category}: {count}' for category, count in error_stats.items())}")
            
            return results
            
        except Exception as e:
            log.error(f"Workspace/symbol indexing failed: {e}, falling back to documentSymbol")
            return {}

    def _get_module_for_path(self, fullpath: str, root_path: str) -> str:
        """
        Извлекает имя модуля из пути к файлу (аналог getModuleForPath из vsc-language-1c-bsl).
        
        Логика:
        - Для CommonModules: возвращает имя модуля (например, "ИмяМодуля")
        - Для других типов: возвращает "РодительскийТип.ИмяОбъекта" (например, "Документы.ИмяДокумента")
        
        :param fullpath: Полный путь к файлу
        :param root_path: Корневой путь проекта
        :return: Имя модуля (например, "ОбщиеМодули.ИмяМодуля") или пустая строка
        """
        try:
            # Нормализуем пути
            if root_path.endswith(("\\", "/")):
                rel_path = fullpath[len(root_path):]
            else:
                rel_path = fullpath[len(root_path) + 1:]
            
            parts = rel_path.replace("\\", "/").split("/")
            hierarchy = len(parts)
            
            # Нужно минимум 4 части для определения типа модуля
            # Например: CommonModules/ИмяМодуля/Ext/Module.bsl
            if hierarchy > 3:
                parent_type = parts[hierarchy - 4]
                
                # Для CommonModules просто возвращаем имя модуля
                if parent_type.startswith("CommonModules") or parent_type.startswith("ОбщиеМодули"):
                    return parts[hierarchy - 3]
                
                # Для других типов используем маппинг (аналог toreplaced из vsc-language-1c-bsl)
                # Маппинг английских имен на русские
                type_mapping = {
                    "Documents": "Документы",
                    "Catalogs": "Справочники",
                    "InformationRegisters": "РегистрыСведений",
                    "AccumulationRegisters": "РегистрыНакопления",
                    "Enums": "Перечисления",
                    "Constants": "Константы",
                    "CommonCommands": "ОбщиеКоманды",
                    "WebServices": "ВебСервисы",
                    "BusinessProcesses": "БизнесПроцессы",
                    "Tasks": "Задачи"
                }
                
                # Применяем маппинг если есть
                mapped_type = type_mapping.get(parent_type, parent_type)
                
                # Возвращаем "РодительскийТип.ИмяОбъекта"
                return f"{mapped_type}.{parts[hierarchy - 3]}"
            
            return ""
        except Exception:
            return ""
    
    def _parse_file_local(self, relative_file_path: str) -> None:
        """
        Парсит один файл локально и добавляет результаты в кеш.
        Проверяет существующий кеш pickle перед парсингом для избежания повторной обработки.
        Аналог обработки файла в addtocachefiles из vsc-language-1c-bsl.
        
        :param relative_file_path: Относительный путь к файлу
        """
        if self._local_cache is None:
            return
        
        abs_path = os.path.join(self.repository_root_path, relative_file_path)
        if not os.path.exists(abs_path):
            log.debug(f"File not found: {abs_path}")
            return
        
        try:
            # Читаем файл и нормализуем окончания строк (как в LSPFileBuffer)
            log.debug(f"Reading file: {relative_file_path}")
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                source = f.read()
            
            # Нормализуем окончания строк (как в LSPFileBuffer)
            source = source.replace("\r\n", "\n").replace("\r", "\n")
            
            # Вычисляем хеш от нормализованного текста в UTF-8 (как в LSPFileBuffer.content_hash)
            file_hash = hashlib.md5(source.encode("utf-8")).hexdigest()
            
            # Проверяем, есть ли файл уже в кеше с правильным хешем
            cache_key = relative_file_path  # Ключ должен быть строкой, не tuple
            if cache_key in self._document_symbols_cache:
                cached_hash, _ = self._document_symbols_cache[cache_key]
                if cached_hash == file_hash:
                    log.debug(f"File {relative_file_path} already cached with matching hash, skipping")
                    return
            
            if not source.strip():
                log.debug(f"File {relative_file_path} is empty, skipping")
                return
            
            # Парсим файл
            log.debug(f"Parsing file: {relative_file_path} ({len(source)} chars)")
            from solidlsp.bsl_parser import BSLParser
            parser = BSLParser()
            parse_result = parser.parse(source)
            log.info(f"Parsed file: {relative_file_path} - {len(parse_result.methods)} methods, {len(parse_result.module_vars)} vars, {len(parse_result.global_calls)} global calls")
            
            # Извлекаем имя модуля
            module = self._get_module_for_path(abs_path, self.repository_root_path)
            
            # Добавляем методы в локальный кеш для поиска ссылок
            if parse_result.methods:
                log.debug(f"Adding {len(parse_result.methods)} methods to local cache for {relative_file_path}")
                self._local_cache.add_methods_batch(
                    [(method, relative_file_path, module) for method in parse_result.methods]
                )
            
            # Добавляем переменные модуля в локальный кеш
            if parse_result.module_vars:
                log.debug(f"Adding {len(parse_result.module_vars)} module vars to local cache for {relative_file_path}")
                self._local_cache.add_module_vars_batch(
                    [(var, relative_file_path) for var in parse_result.module_vars.values()]
                )
            
            # Добавляем вызовы на уровне модуля
            if parse_result.global_calls:
                log.debug(f"Adding {len(parse_result.global_calls)} global calls to local cache for {relative_file_path}")
                self._local_cache.add_calls_batch(
                    [(call, relative_file_path, "GlobalModuleText", module) for call in parse_result.global_calls]
                )
            
            # Добавляем вызовы внутри методов
            method_calls = []
            for method in parse_result.methods:
                for call in method.calls_position:
                    method_calls.append((call, relative_file_path, method.name, module))
            if method_calls:
                log.debug(f"Adding {len(method_calls)} method calls to local cache for {relative_file_path}")
                self._local_cache.add_calls_batch(method_calls)
            
            # СРАЗУ преобразуем в DocumentSymbols и добавляем в кеш (инкрементально)
            self._convert_single_file_to_document_symbols(
                relative_file_path,
                abs_path,
                source,
                file_hash,
                parse_result.methods,
                module
            )
            
            log.debug(f"Successfully processed file: {relative_file_path}")
        
        except Exception as e:
            log.error(f"Failed to parse file {relative_file_path} locally: {e}", exc_info=True)
            raise
    
    def _index_files_with_local_parser(
        self,
        file_paths: list[str],
        save_cache_callback=None
    ) -> dict[str, Exception | None]:
        """
        Массовая индексация через локальный Python парсер.
        Аналог addtocachefiles из vsc-language-1c-bsl.
        
        :param file_paths: Список относительных путей к файлам для индексации
        :param save_cache_callback: Опциональный callback для сохранения кеша
        :return: Словарь {file_path: Exception | None} с результатами индексации
        """
        if self._local_cache is None:
            log.warning("Local cache not initialized, falling back to LSP indexing")
            return {}
        
        total_files = len(file_paths)
        log.info(f"Starting local parser indexing: {total_files} files with {self.file_read_parallelism} parallel workers")
        log.debug(f"Local parser indexing: total_files={total_files}, file_read_parallelism={self.file_read_parallelism}")
        
        results: dict[str, Exception | None] = {}
        completed_count = 0
        start_time = time.time()
        
        # Параллельное чтение и парсинг файлов
        # Таймаут для обработки одного файла (30 секунд на файл)
        file_timeout = 30.0
        
        with ThreadPoolExecutor(max_workers=self.file_read_parallelism) as executor:
            futures = {}
            for file_path in file_paths:
                future = executor.submit(self._parse_file_local, file_path)
                futures[future] = file_path
            
            last_logged_percent = -1
            last_logged_file = ""
            processed_files = set()  # Отслеживаем обработанные файлы для обнаружения зацикливания
            
            # Используем таймаут для всего цикла as_completed, чтобы не зависнуть
            import threading
            stop_event = threading.Event()
            
            def check_stuck():
                """Проверяет, не застрял ли процесс на одном файле"""
                last_count = completed_count
                time.sleep(60)  # Ждем 60 секунд
                if not stop_event.is_set() and completed_count == last_count:
                    log.warning(
                        f"Possible stuck: no progress in 60 seconds. "
                        f"Completed: {completed_count}/{total_files}, "
                        f"Active futures: {sum(1 for f in futures if not f.done())}"
                    )
            
            stuck_checker = threading.Thread(target=check_stuck, daemon=True)
            stuck_checker.start()
            
            try:
                for future in as_completed(futures):
                    file_path = futures[future]
                    
                    # Проверяем, не обрабатывали ли мы уже этот файл (защита от зацикливания)
                    if file_path in processed_files:
                        log.warning(f"File {file_path} was already processed, skipping duplicate")
                        continue
                    processed_files.add(file_path)
                    
                    try:
                        # Логируем текущий обрабатываемый файл
                        if file_path != last_logged_file:
                            log.debug(f"Processing file ({completed_count + 1}/{total_files}): {file_path}")
                            last_logged_file = file_path
                        
                        # Добавляем таймаут для предотвращения зависания
                        try:
                            future.result(timeout=file_timeout)
                            results[file_path] = None
                            completed_count += 1
                            log.debug(f"Successfully processed file ({completed_count}/{total_files}): {file_path}")
                        except TimeoutError:
                            log.warning(f"Timeout ({file_timeout}s) while parsing {file_path}, skipping")
                            results[file_path] = TimeoutError(f"Timeout after {file_timeout}s")
                            completed_count += 1
                            # Отменяем задачу, если она еще выполняется
                            future.cancel()
                        
                        # Логируем прогресс
                        percent = (completed_count * 100) // total_files if total_files > 0 else 0
                        should_log = (
                            percent >= last_logged_percent + 5 or
                            completed_count % 50 == 0 or
                            completed_count == total_files
                        )
                        
                        if should_log:
                            elapsed = time.time() - start_time
                            files_per_sec = completed_count / elapsed if elapsed > 0 else 0
                            remaining = total_files - completed_count
                            log.info(
                                f"Local parser progress: {completed_count}/{total_files} files processed ({percent}%) "
                                f"[{files_per_sec:.1f} files/sec, {remaining} remaining]"
                            )
                            log.debug(
                                f"Local parser detailed progress: completed={completed_count}, total={total_files}, "
                                f"percent={percent}%, speed={files_per_sec:.2f} files/sec, remaining={remaining}, "
                                f"elapsed={elapsed:.2f}s"
                            )
                            last_logged_percent = percent
                        
                        # Сохраняем кеш периодически (каждые 200 файлов)
                        # Файлы уже добавлены в кеш инкрементально в _parse_file_local
                        if save_cache_callback and completed_count % 200 == 0:
                            try:
                                save_cache_callback()
                                log.debug(f"Cache saved after processing {completed_count} files")
                            except Exception as e:
                                log.warning(f"Failed to save cache: {e}")
                    
                    except Exception as e:
                        log.error(f"Unexpected error processing {file_path}: {e}", exc_info=True)
                        results[file_path] = e
                        completed_count += 1
            finally:
                stop_event.set()
                
                # Проверяем, все ли задачи завершены
                pending = [f for f in futures if not f.done()]
                if pending:
                    log.warning(f"Some tasks did not complete: {len(pending)} pending futures")
                    for future in pending:
                        file_path = futures[future]
                        if file_path not in results:
                            log.warning(f"Marking {file_path} as failed (task did not complete)")
                            results[file_path] = Exception("Task did not complete")
                            completed_count += 1
        
        # Файлы уже добавлены в кеш инкрементально в _parse_file_local
        # Сохраняем финальный кеш через стандартный механизм
        if save_cache_callback:
            try:
                save_cache_callback()
            except Exception as e:
                log.warning(f"Failed to save final cache: {e}")
        
        elapsed = time.time() - start_time
        files_per_sec = completed_count / elapsed if elapsed > 0 else 0
        final_percent = (completed_count * 100) // total_files if total_files > 0 else 100
        stats = self._local_cache.get_stats() if self._local_cache else {}
        
        log.info(
            f"Local parser indexing completed: {completed_count}/{total_files} files processed ({final_percent}%) "
            f"[{files_per_sec:.1f} files/sec, {stats.get('methods', 0)} methods indexed]"
        )
        log.debug(
            f"Local parser indexing final stats: processed={completed_count}/{total_files} ({final_percent}%), "
            f"elapsed={elapsed:.2f}s, speed={files_per_sec:.2f} files/sec, "
            f"methods={stats.get('methods', 0)}, module_vars={stats.get('module_vars', 0)}, "
            f"calls={stats.get('unique_calls', 0)}"
        )
        
        return results
    
    def _convert_local_cache_to_document_symbols(self, only_new_files: bool = True) -> None:
        """
        Преобразует локальный кеш в формат DocumentSymbols для совместимости с существующей системой.
        
        :param only_new_files: Если True, преобразует только новые файлы (инкрементально).
                               Это значительно ускоряет процесс, так как не обрабатывает уже преобразованные файлы.
        """
        if self._local_cache is None:
            return
        
        from solidlsp import ls_types
        import hashlib
        
        # Группируем методы по файлам
        methods_by_file: dict[str, list] = defaultdict(list)
        for method_info in self._local_cache.methods:
            filename = method_info.filename
            # Если only_new_files=True, пропускаем уже преобразованные файлы
            if only_new_files and filename in self._converted_files:
                continue
            methods_by_file[filename].append(method_info)
        
        if not methods_by_file:
            log.debug("No new files to convert to DocumentSymbols")
            return
        
        log.debug(f"Converting {len(methods_by_file)} files to DocumentSymbols format (incremental: {only_new_files})")
        conversion_start = time.time()
        
        # Преобразуем методы каждого файла в DocumentSymbols
        for filename, method_infos in methods_by_file.items():
            try:
                # Вычисляем абсолютный путь один раз
                abs_path = os.path.join(self.repository_root_path, filename)
                
                # Используем кешированное содержимое файла для избежания повторного чтения
                if self._file_content_cache and filename in self._file_content_cache:
                    file_content = self._file_content_cache[filename]
                else:
                    # Если нет в кеше, читаем файл
                    if not os.path.exists(abs_path):
                        continue
                    with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                        file_content = f.read()
                    # Сохраняем в кеш для будущего использования
                    if self._file_content_cache is not None:
                        self._file_content_cache[filename] = file_content
                
                # Вычисляем хеш файла из кешированного содержимого (быстрее чем чтение файла)
                file_hash = hashlib.md5(file_content.encode('utf-8')).hexdigest()
                
                # Создаем UnifiedSymbolInformation для каждого метода
                unified_symbols: list[ls_types.UnifiedSymbolInformation] = []
                
                # Кэшируем разбиение на строки для всех методов файла
                lines = file_content.split('\n')
                
                for method_info in method_infos:
                    method = method_info.method
                    
                    # Определяем kind: 12 для Function, 6 для Method (процедура)
                    kind = 12 if not method.isproc else 6
                    
                    # Создаем range для метода
                    start_line = method.line
                    end_line = min(method.endline, len(lines) - 1) if method.endline < len(lines) else len(lines) - 1
                    
                    start_char = 0
                    if start_line < len(lines):
                        # Находим позицию имени метода в строке
                        method_line = lines[start_line]
                        name_pos = method_line.find(method.name)
                        if name_pos != -1:
                            start_char = name_pos
                    
                    end_char = len(lines[end_line]) if end_line < len(lines) else 0
                    
                    range_obj = ls_types.Range(
                        start=ls_types.Position(line=start_line, character=start_char),
                        end=ls_types.Position(line=end_line, character=end_char)
                    )
                    
                    # Создаем location
                    uri = pathlib.Path(abs_path).as_uri()
                    location = ls_types.Location(
                        uri=uri,
                        range=range_obj,
                        absolutePath=abs_path,
                        relativePath=filename
                    )
                    
                    # Формируем детали символа
                    detail_parts = []
                    if method.context:
                        detail_parts.append(method.context)
                    if method.is_export:
                        detail_parts.append("Экспорт")
                    detail = " | ".join(detail_parts) if detail_parts else None
                    
                    # Создаем UnifiedSymbolInformation
                    symbol: ls_types.UnifiedSymbolInformation = {
                        "name": method.name,
                        "kind": kind,
                        "location": location,
                        "range": range_obj,
                        "selectionRange": range_obj,
                        "children": [],
                        "body": self._extract_method_body(file_content, method),
                        "detail": detail,
                        "description": method.description or None
                    }
                    
                    unified_symbols.append(symbol)
                
                # Создаем DocumentSymbols и сохраняем в кеш
                document_symbols = DocumentSymbols(unified_symbols)
                cache_key = filename  # Ключ должен быть строкой, не tuple
                self._document_symbols_cache[cache_key] = (file_hash, document_symbols)
                self._document_symbols_cache_is_modified = True
                
                # Также обновляем raw cache для консистентности
                raw_cache_key = filename
                self._raw_document_symbols_cache[raw_cache_key] = (file_hash, None)
                self._raw_document_symbols_cache_is_modified = True
                
                # Помечаем файл как преобразованный для инкрементального преобразования
                self._converted_files.add(filename)
                
            except Exception as e:
                log.error(f"Failed to convert local cache to DocumentSymbols for {filename}: {e}", exc_info=True)
        
        conversion_elapsed = time.time() - conversion_start
        log.debug(f"Converted {len(methods_by_file)} files to DocumentSymbols in {conversion_elapsed:.2f}s")
    
    def _convert_single_file_to_document_symbols(
        self,
        relative_file_path: str,
        abs_path: str,
        file_content: str,
        file_hash: str,
        methods: list,
        module: str
    ) -> None:
        """
        Преобразует один файл в DocumentSymbols и добавляет в кеш.
        Вызывается сразу после парсинга для инкрементального обновления кеша.
        
        :param relative_file_path: Относительный путь к файлу
        :param abs_path: Абсолютный путь к файлу
        :param file_content: Содержимое файла
        :param file_hash: MD5 хеш содержимого файла
        :param methods: Список методов (BSLMethod) из результата парсинга
        :param module: Имя модуля
        """
        from solidlsp import ls_types
        
        # ВАЖНО: ключ для document cache должен быть строкой, а не tuple!
        # Это соответствует типу dict[str, tuple[str, DocumentSymbols]]
        document_cache_key = relative_file_path
        raw_cache_key = relative_file_path  # Для raw cache тоже строка
        
        if not methods:
            # Если нет методов, создаем пустой DocumentSymbols
            document_symbols = DocumentSymbols([])
            self._document_symbols_cache[document_cache_key] = (file_hash, document_symbols)
            self._document_symbols_cache_is_modified = True
            
            # Также обновляем raw cache для консистентности
            # Кладем None, так как файл был обработан локальным парсером
            self._raw_document_symbols_cache[raw_cache_key] = (file_hash, None)
            self._raw_document_symbols_cache_is_modified = True
            return
        
        # Создаем UnifiedSymbolInformation для каждого метода
        unified_symbols: list[ls_types.UnifiedSymbolInformation] = []
        lines = file_content.split('\n')
        
        for method in methods:
            kind = 12 if not method.isproc else 6
            
            start_line = method.line
            end_line = min(method.endline, len(lines) - 1) if method.endline < len(lines) else len(lines) - 1
            
            start_char = 0
            if start_line < len(lines):
                method_line = lines[start_line]
                name_pos = method_line.find(method.name)
                if name_pos != -1:
                    start_char = name_pos
            
            end_char = len(lines[end_line]) if end_line < len(lines) else 0
            
            range_obj = ls_types.Range(
                start=ls_types.Position(line=start_line, character=start_char),
                end=ls_types.Position(line=end_line, character=end_char)
            )
            
            uri = pathlib.Path(abs_path).as_uri()
            location = ls_types.Location(
                uri=uri,
                range=range_obj,
                absolutePath=abs_path,
                relativePath=relative_file_path
            )
            
            detail_parts = []
            if method.context:
                detail_parts.append(method.context)
            if method.is_export:
                detail_parts.append("Экспорт")
            detail = " | ".join(detail_parts) if detail_parts else None
            
            symbol: ls_types.UnifiedSymbolInformation = {
                "name": method.name,
                "kind": kind,
                "location": location,
                "range": range_obj,
                "selectionRange": range_obj,
                "children": [],
                "body": self._extract_method_body(file_content, method),
                "detail": detail,
                "description": method.description or None
            }
            
            unified_symbols.append(symbol)
        
        # Создаем DocumentSymbols и сохраняем в кеш
        document_symbols = DocumentSymbols(unified_symbols)
        self._document_symbols_cache[document_cache_key] = (file_hash, document_symbols)
        self._document_symbols_cache_is_modified = True
        
        # Также обновляем raw cache для консистентности
        # Кладем None, так как файл был обработан локальным парсером, а не LSP сервером
        self._raw_document_symbols_cache[raw_cache_key] = (file_hash, None)
        self._raw_document_symbols_cache_is_modified = True
    
    def _extract_method_body(self, file_content: str, method: Any) -> str:
        """
        Извлекает тело метода из содержимого файла.
        
        :param file_content: Содержимое файла
        :param method: Метод для извлечения (BSLMethod)
        :return: Тело метода
        """
        lines = file_content.split('\n')
        start_line = method.line
        end_line = min(method.endline, len(lines) - 1) if method.endline < len(lines) else len(lines) - 1
        
        if start_line > end_line or start_line >= len(lines):
            return ""
        
        return '\n'.join(lines[start_line:end_line + 1])
    
    def request_references(self, relative_file_path: str, line: int, column: int) -> list[ls_types.Location]:
        """
        Находит все ссылки на символ через локальный кеш вызовов.
        Если локальный парсер включен и кеш доступен, использует его вместо LSP запроса.
        
        :param relative_file_path: Относительный путь к файлу с символом
        :param line: Номер строки символа (0-based)
        :param column: Номер колонки символа (0-based)
        :return: Список мест, где используется символ
        """
        # Всегда используем локальный кеш для поиска ссылок
        return self._request_references_from_cache(relative_file_path, line, column)
    
    def _request_references_from_cache(self, relative_file_path: str, line: int, column: int) -> list[ls_types.Location]:
        """
        Находит ссылки на символ через локальный кеш вызовов.
        
        :param relative_file_path: Относительный путь к файлу с символом
        :param line: Номер строки символа (0-based)
        :param column: Номер колонки символа (0-based)
        :return: Список мест, где используется символ
        """
        from solidlsp import ls_types
        
        # Определяем имя символа по позиции
        symbol_name = self._get_symbol_name_at_position(relative_file_path, line, column)
        if not symbol_name:
            log.debug(f"Could not determine symbol name at {relative_file_path}:{line}:{column}, returning empty references")
            return []
        
        log.debug(f"Looking for references to symbol '{symbol_name}' via local cache")
        
        # Находим все вызовы этого символа в кеше
        call_infos = self._local_cache.find_calls(symbol_name)
        
        if not call_infos:
            log.debug(f"No calls found for symbol '{symbol_name}' in local cache")
            return []
        
        # Определяем определение символа, чтобы исключить его из результатов (если нужно)
        symbol_definition: dict[str, Any] | None = None
        try:
            document_symbols = self.request_document_symbols(relative_file_path)
            for symbol in document_symbols.iter_symbols():
                if symbol.get("name") == symbol_name:
                    symbol_range = symbol.get("range")
                    if symbol_range:
                        symbol_start_line = symbol_range["start"]["line"]
                        symbol_start_char = symbol_range["start"]["character"]
                        # Проверяем, находится ли позиция в определении символа
                        if (symbol_start_line == line and 
                            symbol_start_char <= column <= symbol_range["end"]["character"]):
                            symbol_definition = {
                                "filename": relative_file_path,
                                "line": symbol_start_line,
                                "character": symbol_start_char
                            }
                            break
        except Exception as e:
            log.debug(f"Could not determine symbol definition: {e}")
        
        # Преобразуем вызовы в формат Location
        references: list[ls_types.Location] = []
        
        for call_info in call_infos:
            try:
                # Пропускаем игнорируемые пути
                if self.is_ignored_path(call_info.filename):
                    log.debug(f"Ignoring reference in {call_info.filename} (ignored path)")
                    continue
                
                # Пропускаем само определение символа (если это не вызов, а определение)
                if (symbol_definition and 
                    call_info.filename == symbol_definition["filename"] and
                    call_info.line == symbol_definition["line"] and
                    call_info.character == symbol_definition["character"]):
                    log.debug(f"Skipping symbol definition at {call_info.filename}:{call_info.line}:{call_info.character}")
                    continue
                
                # Проверяем существование файла
                abs_path = os.path.join(self.repository_root_path, call_info.filename)
                if not os.path.exists(abs_path):
                    log.debug(f"File not found: {abs_path}, skipping reference")
                    continue
                
                # Читаем файл для определения точной позиции вызова
                with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                    file_lines = f.read().split('\n')
                
                if call_info.line >= len(file_lines):
                    log.debug(f"Line {call_info.line} out of range for {call_info.filename}, skipping")
                    continue
                
                # Находим точную позицию вызова в строке
                call_line = file_lines[call_info.line]
                call_char = call_info.character
                
                # Убеждаемся, что позиция не выходит за границы строки
                if call_char >= len(call_line):
                    call_char = 0
                
                # Ищем имя символа в строке для более точной позиции
                # Ищем первое вхождение имени символа после указанной позиции
                name_pos = call_line.find(symbol_name, call_char)
                if name_pos == -1:
                    # Если не нашли, используем исходную позицию
                    name_pos = call_char
                
                # Создаем Range для вызова
                # Вызов обычно занимает одну позицию, но можем расширить до конца имени
                end_char = name_pos + len(symbol_name)
                if end_char > len(call_line):
                    end_char = len(call_line)
                
                range_obj = ls_types.Range(
                    start=ls_types.Position(line=call_info.line, character=name_pos),
                    end=ls_types.Position(line=call_info.line, character=end_char)
                )
                
                # Создаем Location
                uri = pathlib.Path(abs_path).as_uri()
                location = ls_types.Location(
                    uri=uri,
                    range=range_obj,
                    absolutePath=abs_path,
                    relativePath=call_info.filename
                )
                
                references.append(location)
                
            except Exception as e:
                log.warning(f"Failed to process reference for {call_info.filename}:{call_info.line}:{call_info.character}: {e}")
                continue
        
        log.info(f"Found {len(references)} references to '{symbol_name}' via local cache")
        return references
    
    def _get_symbol_name_at_position(self, relative_file_path: str, line: int, column: int) -> str | None:
        """
        Определяет имя символа по позиции в файле.
        
        :param relative_file_path: Относительный путь к файлу
        :param line: Номер строки (0-based)
        :param column: Номер колонки (0-based)
        :return: Имя символа или None, если не удалось определить
        """
        try:
            # Получаем символы из кеша
            document_symbols = self.request_document_symbols(relative_file_path)
            
            # Ищем символ, который содержит указанную позицию
            for symbol in document_symbols.iter_symbols():
                symbol_range = symbol.get("range")
                if not symbol_range:
                    continue
                
                start_line = symbol_range["start"]["line"]
                start_char = symbol_range["start"]["character"]
                end_line = symbol_range["end"]["line"]
                end_char = symbol_range["end"]["character"]
                
                # Проверяем, находится ли позиция внутри символа
                if start_line <= line <= end_line:
                    if line == start_line and column < start_char:
                        continue
                    if line == end_line and column > end_char:
                        continue
                    
                    # Нашли символ, возвращаем его имя
                    return symbol.get("name")
            
            # Если не нашли символ в кеше, пытаемся определить по тексту файла
            abs_path = os.path.join(self.repository_root_path, relative_file_path)
            if os.path.exists(abs_path):
                with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                    file_lines = f.read().split('\n')
                
                if line < len(file_lines):
                    file_line = file_lines[line]
                    # Пытаемся извлечь имя символа из позиции
                    # Для BSL ищем идентификатор (начинается с буквы, содержит буквы, цифры и подчеркивания)
                    if column < len(file_line):
                        # Ищем начало идентификатора (двигаемся назад от позиции)
                        start = column
                        while start > 0 and (file_line[start - 1].isalnum() or file_line[start - 1] == '_'):
                            start -= 1
                        
                        # Ищем конец идентификатора (двигаемся вперед от позиции)
                        end = column
                        while end < len(file_line) and (file_line[end].isalnum() or file_line[end] == '_'):
                            end += 1
                        
                        if start < end:
                            symbol_name = file_line[start:end]
                            # Проверяем, что это валидный идентификатор (начинается с буквы)
                            if symbol_name and (symbol_name[0].isalpha() or symbol_name[0] in 'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя'):
                                return symbol_name
            
            return None
            
        except Exception as e:
            log.debug(f"Failed to get symbol name at position {relative_file_path}:{line}:{column}: {e}")
            return None
    
    def insert_text_at_position(self, relative_file_path: str, line: int, column: int, text_to_be_inserted: str) -> ls_types.Position:
        """
        Insert text at the given line and column in the given file using direct file editing.
        Updates the local cache after editing.
        
        :param relative_file_path: The relative path of the file to edit.
        :param line: The line number at which text should be inserted.
        :param column: The column number at which text should be inserted.
        :param text_to_be_inserted: The text to insert.
        :return: The updated cursor position after inserting the text.
        """
        # Читаем файл напрямую
        absolute_file_path = os.path.join(self.repository_root_path, relative_file_path)
        with open(absolute_file_path, 'r', encoding=self.encoding) as f:
            file_content = f.read()
        
        # Используем TextUtils для редактирования
        new_contents, new_l, new_c = TextUtils.insert_text_at_position(file_content, line, column, text_to_be_inserted)
        
        # Записываем файл обратно
        with open(absolute_file_path, 'w', encoding=self.encoding) as f:
            f.write(new_contents)
        
        # Обновляем кеш для измененного файла
        self._invalidate_file_cache(relative_file_path)
        
        return ls_types.Position(line=new_l, character=new_c)
    
    def delete_text_between_positions(
        self,
        relative_file_path: str,
        start: ls_types.Position,
        end: ls_types.Position,
    ) -> str:
        """
        Delete text between the given start and end positions in the given file using direct file editing.
        Updates the local cache after editing.
        
        :param relative_file_path: The relative path of the file to edit.
        :param start: The start position.
        :param end: The end position.
        :return: The deleted text.
        """
        # Читаем файл напрямую
        absolute_file_path = os.path.join(self.repository_root_path, relative_file_path)
        with open(absolute_file_path, 'r', encoding=self.encoding) as f:
            file_content = f.read()
        
        # Используем TextUtils для редактирования
        new_contents, deleted_text = TextUtils.delete_text_between_positions(
            file_content, start_line=start["line"], start_col=start["character"], end_line=end["line"], end_col=end["character"]
        )
        
        # Записываем файл обратно
        with open(absolute_file_path, 'w', encoding=self.encoding) as f:
            f.write(new_contents)
        
        # Обновляем кеш для измененного файла
        self._invalidate_file_cache(relative_file_path)
        
        return deleted_text
    
    def request_rename_symbol_edit(
        self,
        relative_file_path: str,
        line: int,
        column: int,
        new_name: str,
    ) -> ls_types.WorkspaceEdit | None:
        """
        Retrieve a WorkspaceEdit for renaming the symbol at the given location to the new name.
        Uses local cache instead of LSP request.
        
        :param relative_file_path: The relative path to the file containing the symbol
        :param line: The 0-indexed line number of the symbol
        :param column: The 0-indexed column number of the symbol
        :param new_name: The new name for the symbol
        :return: A WorkspaceEdit containing the changes needed to rename the symbol, or None if rename is not supported
        """
        from solidlsp import ls_types
        import pathlib
        
        # Определяем имя символа по позиции
        symbol_name = self._get_symbol_name_at_position(relative_file_path, line, column)
        if not symbol_name:
            log.debug(f"Could not determine symbol name at {relative_file_path}:{line}:{column}")
            return None
        
        log.debug(f"Renaming symbol '{symbol_name}' to '{new_name}' via local cache")
        
        # Находим все вызовы этого символа в кеше
        call_infos = self._local_cache.find_calls(symbol_name)
        
        # Получаем определение символа через request_document_symbols
        document_symbols = self.request_document_symbols(relative_file_path)
        symbol_definition: dict[str, Any] | None = None
        for symbol in document_symbols.iter_symbols():
            if symbol.get("name") == symbol_name:
                symbol_range = symbol.get("range")
                if symbol_range:
                    symbol_start_line = symbol_range["start"]["line"]
                    symbol_start_char = symbol_range["start"]["character"]
                    # Проверяем, находится ли позиция в определении символа
                    if (symbol_start_line == line and 
                        symbol_start_char <= column <= symbol_range["end"]["character"]):
                        symbol_definition = {
                            "filename": relative_file_path,
                            "range": symbol_range
                        }
                        break
        
        # Создаем список TextEdit для всех мест использования
        text_edits: list[ls_types.TextEdit] = []
        
        # Добавляем редактирование для определения символа
        if symbol_definition:
            def_range = symbol_definition["range"]
            # Читаем файл для определения точной позиции имени символа в строке
            abs_path = os.path.join(self.repository_root_path, relative_file_path)
            with open(abs_path, 'r', encoding=self.encoding) as f:
                file_lines = f.read().split('\n')
            
            if def_range["start"]["line"] < len(file_lines):
                def_line = file_lines[def_range["start"]["line"]]
                # Ищем начало и конец имени символа в строке
                start_char = def_line.find(symbol_name, def_range["start"]["character"])
                if start_char != -1:
                    end_char = start_char + len(symbol_name)
                    text_edits.append({
                        "range": {
                            "start": {"line": def_range["start"]["line"], "character": start_char},
                            "end": {"line": def_range["start"]["line"], "character": end_char}
                        },
                        "newText": new_name
                    })
        
        # Добавляем редактирования для всех вызовов
        for call_info in call_infos:
            call_file_path = call_info.filename
            call_abs_path = os.path.join(self.repository_root_path, call_file_path)
            
            if not os.path.exists(call_abs_path):
                continue
            
            # Читаем файл для определения точной позиции имени символа в строке
            with open(call_abs_path, 'r', encoding=self.encoding) as f:
                call_file_lines = f.read().split('\n')
            
            if call_info.line < len(call_file_lines):
                call_line = call_file_lines[call_info.line]
                # Ищем начало и конец имени символа в строке
                start_char = call_line.find(symbol_name, call_info.character)
                if start_char != -1:
                    end_char = start_char + len(symbol_name)
                    # Создаем URI для файла
                    call_uri = pathlib.Path(call_abs_path).as_uri()
                    
                    # Добавляем TextEdit (будет использован в changes)
                    text_edits.append({
                        "range": {
                            "start": {"line": call_info.line, "character": start_char},
                            "end": {"line": call_info.line, "character": end_char}
                        },
                        "newText": new_name
                    })
        
        if not text_edits:
            log.debug(f"No edits found for renaming symbol '{symbol_name}'")
            return None
        
        # Группируем редактирования по файлам для WorkspaceEdit
        changes: dict[str, list[ls_types.TextEdit]] = {}
        for edit in text_edits:
            # Определяем файл для редактирования
            # Для определения символа используем relative_file_path
            # Для вызовов используем call_info.filename
            # Но в text_edits нет информации о файле, нужно добавить её
            # Используем другой подход - создаем changes напрямую
            pass
        
        # Пересоздаем text_edits с группировкой по файлам
        changes: dict[str, list[ls_types.TextEdit]] = {}
        
        # Добавляем редактирование для определения символа
        if symbol_definition:
            def_uri = pathlib.Path(os.path.join(self.repository_root_path, relative_file_path)).as_uri()
            def_range = symbol_definition["range"]
            abs_path = os.path.join(self.repository_root_path, relative_file_path)
            with open(abs_path, 'r', encoding=self.encoding) as f:
                file_lines = f.read().split('\n')
            
            if def_range["start"]["line"] < len(file_lines):
                def_line = file_lines[def_range["start"]["line"]]
                start_char = def_line.find(symbol_name, def_range["start"]["character"])
                if start_char != -1:
                    end_char = start_char + len(symbol_name)
                    if def_uri not in changes:
                        changes[def_uri] = []
                    changes[def_uri].append({
                        "range": {
                            "start": {"line": def_range["start"]["line"], "character": start_char},
                            "end": {"line": def_range["start"]["line"], "character": end_char}
                        },
                        "newText": new_name
                    })
        
        # Добавляем редактирования для всех вызовов
        for call_info in call_infos:
            call_abs_path = os.path.join(self.repository_root_path, call_info.filename)
            
            if not os.path.exists(call_abs_path):
                continue
            
            with open(call_abs_path, 'r', encoding=self.encoding) as f:
                call_file_lines = f.read().split('\n')
            
            if call_info.line < len(call_file_lines):
                call_line = call_file_lines[call_info.line]
                start_char = call_line.find(symbol_name, call_info.character)
                if start_char != -1:
                    end_char = start_char + len(symbol_name)
                    call_uri = pathlib.Path(call_abs_path).as_uri()
                    
                    if call_uri not in changes:
                        changes[call_uri] = []
                    changes[call_uri].append({
                        "range": {
                            "start": {"line": call_info.line, "character": start_char},
                            "end": {"line": call_info.line, "character": end_char}
                        },
                        "newText": new_name
                    })
        
        if not changes:
            log.debug(f"No edits found for renaming symbol '{symbol_name}'")
            return None
        
        # Создаем WorkspaceEdit
        workspace_edit: ls_types.WorkspaceEdit = {
            "changes": changes
        }
        
        log.debug(f"Created WorkspaceEdit with {len(changes)} files and {sum(len(edits) for edits in changes.values())} edits")
        return workspace_edit
    
    def apply_text_edits_to_file(self, relative_path: str, edits: list[ls_types.TextEdit]) -> None:
        """
        Apply a list of text edits to a file using direct file editing.
        Updates the local cache after editing.
        
        :param relative_path: The relative path of the file to edit.
        :param edits: List of TextEdit dictionaries to apply.
        """
        # Читаем файл напрямую
        absolute_file_path = os.path.join(self.repository_root_path, relative_path)
        with open(absolute_file_path, 'r', encoding=self.encoding) as f:
            file_content = f.read()
        
        # Сортируем редактирования по позиции (с конца к началу, чтобы не сломать позиции)
        sorted_edits = sorted(edits, key=lambda e: (e["range"]["start"]["line"], e["range"]["start"]["character"]), reverse=True)
        
        # Применяем редактирования
        for edit in sorted_edits:
            start_pos = edit["range"]["start"]
            end_pos = edit["range"]["end"]
            
            # Удаляем текст между позициями
            file_content, _ = TextUtils.delete_text_between_positions(
                file_content, start_line=start_pos["line"], start_col=start_pos["character"], 
                end_line=end_pos["line"], end_col=end_pos["character"]
            )
            
            # Вставляем новый текст
            file_content, _, _ = TextUtils.insert_text_at_position(
                file_content, start_pos["line"], start_pos["character"], edit["newText"]
            )
        
        # Записываем файл обратно
        with open(absolute_file_path, 'w', encoding=self.encoding) as f:
            f.write(file_content)
        
        # Обновляем кеш для измененного файла
        self._invalidate_file_cache(relative_path)
    
    def _invalidate_file_cache(self, relative_file_path: str) -> None:
        """
        Инвалидирует кеш для конкретного файла и переиндексирует его.
        Используется после редактирования файла для точечного обновления кеша.
        
        :param relative_file_path: Относительный путь к файлу
        """
        log.debug(f"Invalidating cache for file: {relative_file_path}")
        
        # 1. Удаление из кешей DocumentSymbols
        cache_key = relative_file_path
        self._document_symbols_cache.pop(cache_key, None)
        if hasattr(self, '_raw_document_symbols_cache'):
            self._raw_document_symbols_cache.pop(cache_key, None)
        
        # 2. Удаление данных файла из локального кеша
        if self._local_cache is not None:
            self._local_cache.remove_file_data(relative_file_path)
        
        # 3. Удаление из кеша содержимого файлов
        self._file_content_cache.pop(relative_file_path, None)
        
        # 4. Удаление из списка преобразованных файлов
        self._converted_files.discard(relative_file_path)
        
        # 5. Переиндексация файла
        # _parse_file_local уже вызывает _convert_single_file_to_document_symbols внутри
        self._parse_file_local(relative_file_path)
        
        log.debug(f"Cache invalidated and file reindexed: {relative_file_path}")
    
    def stop(self, shutdown_timeout: float = 2.0) -> None:
        """
        Останавливает BSL Language Server.
        """
        # Вызываем родительский метод для остановки сервера
        super().stop(shutdown_timeout=shutdown_timeout)

