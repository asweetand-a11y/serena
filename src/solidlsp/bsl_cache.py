"""
In-memory кеш для BSL символов (аналог LokiJS).
Предоставляет быстрый поиск и индексацию символов.
"""

import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any, TypeVar

_R = TypeVar("_R")


def _with_cache_lock(method: Callable[..., _R]) -> Callable[..., _R]:
    """Serialize access to in-memory cache structures across indexer threads."""

    @wraps(method)
    def wrapper(self: "BSLCache", *args: Any, **kwargs: Any) -> _R:
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper

from solidlsp.bsl_parser import BSLCallPosition, BSLMethod, BSLModuleVar


@dataclass
class BSLCallInfo:
    """Информация о вызове процедуры/функции."""

    filename: str
    call: str
    line: int
    character: int
    method_name: str  # Имя метода, в котором находится вызов
    module: str = ""  # Модуль, к которому относится файл


@dataclass
class BSLModuleInfo:
    """Метаданные модуля."""

    filename: str
    module: str  # Имя модуля (например, "ОбщиеМодули.ИмяМодуля")
    type: str = ""  # Тип модуля (ObjectModule, ManagerModule, CommonModule и т.д.)
    parenttype: str = ""  # Родительский тип (CommonModules, Documents и т.д.)
    project: str = ""  # Путь к проекту


@dataclass(eq=False, unsafe_hash=True)
class BSLMethodInfo:
    """Информация о методе с контекстом файла."""

    method: BSLMethod
    filename: str
    module: str = ""  # Модуль, к которому относится метод


class BSLCache:
    """
    In-memory база данных для кеша BSL символов.
    Аналог LokiJS из vsc-language-1c-bsl.
    Public methods are thread-safe for concurrent local-parser indexing.
    """

    def __init__(self):
        self.module_vars: dict[str, list[BSLModuleVar]] = {}  # filename -> list of vars
        self.calls: dict[str, list[BSLCallInfo]] = {}  # call_name -> list of calls
        self.modules: list[BSLModuleInfo] = []

        self._methods_by_file: dict[str, list[BSLMethodInfo]] = {}
        self._calls_by_file: dict[str, list[BSLCallInfo]] = {}
        self._method_name_index: dict[str, list[BSLMethodInfo]] = {}
        self._method_module_index: dict[str, list[BSLMethodInfo]] = {}
        self._method_export_index: list[BSLMethodInfo] = []
        self._indexed_files: set[str] = set()
        self._lock = threading.RLock()

    @property
    def methods(self) -> list[BSLMethodInfo]:
        """All indexed methods. Built from the per-file map; not a stored flat list."""
        with self._lock:
            return self._all_methods()

    def _all_methods(self) -> list[BSLMethodInfo]:
        methods: list[BSLMethodInfo] = []
        for file_methods in self._methods_by_file.values():
            methods.extend(file_methods)
        return methods

    def _add_method_info(self, method_info: BSLMethodInfo) -> None:
        filename = method_info.filename
        self._methods_by_file.setdefault(filename, []).append(method_info)
        self._indexed_files.add(filename)

        method = method_info.method
        name_lower = method.name.lower()
        self._method_name_index.setdefault(name_lower, []).append(method_info)

        if method_info.module:
            module_lower = method_info.module.lower()
            self._method_module_index.setdefault(module_lower, []).append(method_info)

        if method.is_export:
            self._method_export_index.append(method_info)

    def _discard_index_item(self, index: dict[str, list[BSLMethodInfo]], key: str, item: BSLMethodInfo) -> None:
        items = index.get(key)
        if items is None:
            return
        try:
            items.remove(item)
        except ValueError:
            return
        if not items:
            del index[key]

    def _unindex_method(self, method_info: BSLMethodInfo) -> None:
        method = method_info.method
        self._discard_index_item(self._method_name_index, method.name.lower(), method_info)
        if method_info.module:
            self._discard_index_item(self._method_module_index, method_info.module.lower(), method_info)
        if method.is_export:
            try:
                self._method_export_index.remove(method_info)
            except ValueError:
                pass

    def _rebuild_calls_by_file(self) -> None:
        self._calls_by_file.clear()
        for call_list in self.calls.values():
            for call_info in call_list:
                self._calls_by_file.setdefault(call_info.filename, []).append(call_info)

    @_with_cache_lock
    def add_method(self, method: BSLMethod, filename: str, module: str = "") -> None:
        """
        Добавить метод в кеш.

        :param method: Метод для добавления
        :param filename: Путь к файлу
        :param module: Имя модуля (опционально)
        """
        self._add_method_info(BSLMethodInfo(method=method, filename=filename, module=module))

    @_with_cache_lock
    def add_module_var(self, var: BSLModuleVar, filename: str) -> None:
        """
        Добавить переменную модуля в кеш.

        :param var: Переменная для добавления
        :param filename: Путь к файлу
        """
        if filename not in self.module_vars:
            self.module_vars[filename] = []
        self.module_vars[filename].append(var)
        self._indexed_files.add(filename)

    @_with_cache_lock
    def add_call(self, call: BSLCallPosition, filename: str, method_name: str, module: str = "") -> None:
        """
        Добавить информацию о вызове в кеш.

        :param call: Позиция вызова
        :param filename: Путь к файлу
        :param method_name: Имя метода, в котором находится вызов
        :param module: Имя модуля (опционально)
        """
        call_name = call.call
        if call_name not in self.calls:
            self.calls[call_name] = []

        call_info = BSLCallInfo(
            filename=filename, call=call_name, line=call.line, character=call.character, method_name=method_name, module=module
        )
        self.calls[call_name].append(call_info)
        self._calls_by_file.setdefault(filename, []).append(call_info)
        self._indexed_files.add(filename)

    @_with_cache_lock
    def add_methods_batch(self, methods_data: list[tuple[BSLMethod, str, str]]) -> None:
        """
        Добавить несколько методов в кеш пакетно (оптимизация производительности).

        :param methods_data: Список кортежей (method, filename, module)
        """
        for method, filename, module in methods_data:
            self.add_method(method, filename, module)

    @_with_cache_lock
    def add_module_vars_batch(self, vars_data: list[tuple[BSLModuleVar, str]]) -> None:
        """
        Добавить несколько переменных модуля в кеш пакетно (оптимизация производительности).

        :param vars_data: Список кортежей (var, filename)
        """
        for var, filename in vars_data:
            self.add_module_var(var, filename)

    @_with_cache_lock
    def add_calls_batch(self, calls_data: list[tuple[BSLCallPosition, str, str, str]]) -> None:
        """
        Добавить несколько вызовов в кеш пакетно (оптимизация производительности).

        :param calls_data: Список кортежей (call, filename, method_name, module)
        """
        for call, filename, method_name, module in calls_data:
            self.add_call(call, filename, method_name, module)

    @_with_cache_lock
    def add_module(self, module_info: BSLModuleInfo) -> None:
        """
        Добавить метаданные модуля в кеш.

        :param module_info: Информация о модуле
        """
        self.modules.append(module_info)

    @_with_cache_lock
    def find_methods(self, query: dict[str, Any] | None = None) -> list[BSLMethodInfo]:
        """
        Поиск методов по запросу (аналог LokiJS .find()).

        Поддерживаемые поля запроса:
        - name: точное имя или regex паттерн
        - module: имя модуля или regex паттерн
        - is_export: True/False для экспортированных методов
        - context: контекст (НаСервере, НаКлиенте и т.д.)
        - isproc: True для процедур, False для функций

        :param query: Словарь с условиями поиска
        :return: Список найденных методов
        """
        if query is None or not query:
            return self._all_methods()

        candidates: set[BSLMethodInfo] | None = None

        if "name" in query:
            name_pattern = query["name"]
            if isinstance(name_pattern, dict) and "$regex" in name_pattern:
                pattern = re.compile(name_pattern["$regex"], re.IGNORECASE)
                name_matches: set[BSLMethodInfo] = set()
                for name, infos in self._method_name_index.items():
                    if pattern.search(name):
                        name_matches.update(infos)
                candidates = name_matches if candidates is None else candidates & name_matches
            else:
                name_lower = str(name_pattern).lower()
                name_matches = set(self._method_name_index.get(name_lower, []))
                candidates = name_matches if candidates is None else candidates & name_matches

        if "module" in query:
            module_pattern = query["module"]
            if isinstance(module_pattern, dict) and "$regex" in module_pattern:
                pattern = re.compile(module_pattern["$regex"], re.IGNORECASE)
                module_matches: set[BSLMethodInfo] = set()
                for module, infos in self._method_module_index.items():
                    if pattern.search(module):
                        module_matches.update(infos)
                candidates = module_matches if candidates is None else candidates & module_matches
            else:
                module_lower = str(module_pattern).lower()
                module_matches = set(self._method_module_index.get(module_lower, []))
                candidates = module_matches if candidates is None else candidates & module_matches

        if "is_export" in query or "isExport" in query:
            is_export = query.get("is_export", query.get("isExport", False))
            export_matches = set(self._method_export_index)
            if candidates is not None:
                candidates = candidates & export_matches if is_export else candidates - export_matches
            else:
                candidates = export_matches if is_export else set(self._all_methods()) - export_matches

        if candidates is None:
            candidates = set(self._all_methods())

        results: list[BSLMethodInfo] = []
        for method_info in candidates:
            method = method_info.method
            if "context" in query and method.context != query["context"]:
                continue
            if "isproc" in query and method.isproc != query["isproc"]:
                continue
            results.append(method_info)

        return results

    @_with_cache_lock
    def find_calls(self, call_name: str) -> list[BSLCallInfo]:
        """
        Найти все вызовы процедуры/функции.

        :param call_name: Имя вызываемой процедуры/функции
        :return: Список информации о вызовах
        """
        return self.calls.get(call_name, []).copy()

    @_with_cache_lock
    def find_methods_by_module(self, module: str) -> list[BSLMethodInfo]:
        """
        Найти все методы в указанном модуле.

        :param module: Имя модуля
        :return: Список методов модуля
        """
        return self.find_methods({"module": module})

    @_with_cache_lock
    def find_exported_methods(self, module: str | None = None) -> list[BSLMethodInfo]:
        """
        Найти все экспортированные методы.

        :param module: Опциональное имя модуля для фильтрации
        :return: Список экспортированных методов
        """
        query: dict[str, Any] = {"is_export": True}
        if module:
            query["module"] = module
        return self.find_methods(query)

    @_with_cache_lock
    def clear(self) -> None:
        """Очистить весь кеш."""
        self.module_vars.clear()
        self.calls.clear()
        self.modules.clear()
        self._methods_by_file.clear()
        self._calls_by_file.clear()
        self._method_name_index.clear()
        self._method_module_index.clear()
        self._method_export_index.clear()
        self._indexed_files.clear()

    @_with_cache_lock
    def has_file(self, filename: str) -> bool:
        """
        Whether any data for ``filename`` is present in the cache.

        :param filename: relative path to the file
        :return: True if the file was indexed into this cache
        """
        return filename in self._indexed_files

    @_with_cache_lock
    def remove_file_data(self, filename: str) -> None:
        """
        Удалить все данные конкретного файла из кеша.

        :param filename: Относительный путь к файлу
        """
        for method_info in self._methods_by_file.pop(filename, []):
            self._unindex_method(method_info)

        self.module_vars.pop(filename, None)

        affected_call_names = {call.call for call in self._calls_by_file.pop(filename, [])}
        for call_name in affected_call_names:
            remaining = [call for call in self.calls.get(call_name, []) if call.filename != filename]
            if remaining:
                self.calls[call_name] = remaining
            else:
                self.calls.pop(call_name, None)

        self.modules = [module for module in self.modules if module.filename != filename]
        self._indexed_files.discard(filename)

    @_with_cache_lock
    def replace_file_index(
        self,
        filename: str,
        methods_data: list[tuple[BSLMethod, str, str]] | None = None,
        vars_data: list[tuple[BSLModuleVar, str]] | None = None,
        calls_data: list[tuple[BSLCallPosition, str, str, str]] | None = None,
    ) -> None:
        """
        Atomically replace all cached data for one file.

        :param filename: relative path to the file
        :param methods_data: methods to index, as (method, filename, module)
        :param vars_data: module variables, as (var, filename)
        :param calls_data: calls, as (call, filename, method_name, module)
        """
        if filename in self._indexed_files:
            self.remove_file_data(filename)
        if methods_data:
            self.add_methods_batch(methods_data)
        if vars_data:
            self.add_module_vars_batch(vars_data)
        if calls_data:
            self.add_calls_batch(calls_data)

    def _rebuild_indices(self) -> None:
        """Rebuild name/module/export indexes from ``_methods_by_file``."""
        self._method_name_index.clear()
        self._method_module_index.clear()
        self._method_export_index.clear()

        for file_methods in self._methods_by_file.values():
            for method_info in file_methods:
                method = method_info.method
                name_lower = method.name.lower()
                self._method_name_index.setdefault(name_lower, []).append(method_info)
                if method_info.module:
                    module_lower = method_info.module.lower()
                    self._method_module_index.setdefault(module_lower, []).append(method_info)
                if method.is_export:
                    self._method_export_index.append(method_info)

    @_with_cache_lock
    def get_stats(self) -> dict[str, int]:
        """
        Получить статистику по кешу.

        :return: Словарь со статистикой
        """
        return {
            "methods": sum(len(file_methods) for file_methods in self._methods_by_file.values()),
            "exported_methods": len(self._method_export_index),
            "module_vars": sum(len(vars_list) for vars_list in self.module_vars.values()),
            "calls": sum(len(calls_list) for calls_list in self.calls.values()),
            "unique_calls": len(self.calls),
            "modules": len(self.modules),
            "indexed_files": len(self._indexed_files),
        }

    @_with_cache_lock
    def to_persistable_state(self) -> dict[str, Any]:
        """
        Snapshot suitable for pickling (indices are rebuilt on load).

        :return: serializable state dict
        """
        return {
            "methods": self._all_methods(),
            "module_vars": dict(self.module_vars),
            "calls": dict(self.calls),
            "modules": list(self.modules),
        }

    @_with_cache_lock
    def load_persistable_state(self, state: dict[str, Any]) -> None:
        """
        Restore cache contents from a previously persisted snapshot.

        :param state: state produced by ``to_persistable_state``
        """
        self.clear()
        self.module_vars = dict(state.get("module_vars", {}))
        self.calls = dict(state.get("calls", {}))
        self.modules = list(state.get("modules", []))
        for method_info in state.get("methods", []):
            self._methods_by_file.setdefault(method_info.filename, []).append(method_info)
        self._rebuild_indices()
        self._rebuild_calls_by_file()
        self._rebuild_indexed_files()

    def _rebuild_indexed_files(self) -> None:
        """Rebuild ``_indexed_files`` from methods, vars and calls."""
        self._indexed_files.clear()
        self._indexed_files.update(self._methods_by_file.keys())
        self._indexed_files.update(self.module_vars.keys())
        self._indexed_files.update(self._calls_by_file.keys())
