"""
In-memory кеш для BSL символов (аналог LokiJS).
Предоставляет быстрый поиск и индексацию символов.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from solidlsp.bsl_parser import BSLMethod, BSLModuleVar, BSLCallPosition


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


@dataclass
class BSLMethodInfo:
    """Информация о методе с контекстом файла."""
    method: BSLMethod
    filename: str
    module: str = ""  # Модуль, к которому относится метод


class BSLCache:
    """
    In-memory база данных для кеша BSL символов.
    Аналог LokiJS из vsc-language-1c-bsl.
    """
    
    def __init__(self):
        self.methods: list[BSLMethodInfo] = []
        self.module_vars: dict[str, list[BSLModuleVar]] = {}  # filename -> list of vars
        self.calls: dict[str, list[BSLCallInfo]] = {}  # call_name -> list of calls
        self.modules: list[BSLModuleInfo] = []
        
        # Индексы для быстрого поиска
        self._method_name_index: dict[str, list[int]] = {}  # name -> list of indices
        self._method_module_index: dict[str, list[int]] = {}  # module -> list of indices
        self._method_export_index: list[int] = []  # indices of exported methods
    
    def add_method(self, method: BSLMethod, filename: str, module: str = "") -> None:
        """
        Добавить метод в кеш.
        
        :param method: Метод для добавления
        :param filename: Путь к файлу
        :param module: Имя модуля (опционально)
        """
        method_info = BSLMethodInfo(method=method, filename=filename, module=module)
        index = len(self.methods)
        self.methods.append(method_info)
        
        # Обновляем индексы
        method_name_lower = method.name.lower()
        if method_name_lower not in self._method_name_index:
            self._method_name_index[method_name_lower] = []
        self._method_name_index[method_name_lower].append(index)
        
        if module:
            module_lower = module.lower()
            if module_lower not in self._method_module_index:
                self._method_module_index[module_lower] = []
            self._method_module_index[module_lower].append(index)
        
        if method.is_export:
            self._method_export_index.append(index)
    
    def add_module_var(self, var: BSLModuleVar, filename: str) -> None:
        """
        Добавить переменную модуля в кеш.
        
        :param var: Переменная для добавления
        :param filename: Путь к файлу
        """
        if filename not in self.module_vars:
            self.module_vars[filename] = []
        self.module_vars[filename].append(var)
    
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
            filename=filename,
            call=call_name,
            line=call.line,
            character=call.character,
            method_name=method_name,
            module=module
        )
        self.calls[call_name].append(call_info)
    
    def add_methods_batch(self, methods_data: list[tuple[BSLMethod, str, str]]) -> None:
        """
        Добавить несколько методов в кеш пакетно (оптимизация производительности).
        
        :param methods_data: Список кортежей (method, filename, module)
        """
        for method, filename, module in methods_data:
            self.add_method(method, filename, module)
    
    def add_module_vars_batch(self, vars_data: list[tuple[BSLModuleVar, str]]) -> None:
        """
        Добавить несколько переменных модуля в кеш пакетно (оптимизация производительности).
        
        :param vars_data: Список кортежей (var, filename)
        """
        for var, filename in vars_data:
            self.add_module_var(var, filename)
    
    def add_calls_batch(self, calls_data: list[tuple[BSLCallPosition, str, str, str]]) -> None:
        """
        Добавить несколько вызовов в кеш пакетно (оптимизация производительности).
        
        :param calls_data: Список кортежей (call, filename, method_name, module)
        """
        for call, filename, method_name, module in calls_data:
            self.add_call(call, filename, method_name, module)
    
    def add_module(self, module_info: BSLModuleInfo) -> None:
        """
        Добавить метаданные модуля в кеш.
        
        :param module_info: Информация о модуле
        """
        self.modules.append(module_info)
    
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
            return self.methods.copy()
        
        # Начинаем с полного списка индексов
        candidate_indices: set[int] | None = None
        
        # Фильтр по имени
        if 'name' in query:
            name_pattern = query['name']
            if isinstance(name_pattern, dict) and '$regex' in name_pattern:
                # Regex поиск
                pattern = re.compile(name_pattern['$regex'], re.IGNORECASE)
                name_indices = set()
                for name, indices in self._method_name_index.items():
                    if pattern.search(name):
                        name_indices.update(indices)
                candidate_indices = name_indices if candidate_indices is None else candidate_indices & name_indices
            else:
                # Точное совпадение
                name_lower = str(name_pattern).lower()
                name_indices = set(self._method_name_index.get(name_lower, []))
                candidate_indices = name_indices if candidate_indices is None else candidate_indices & name_indices
        
        # Фильтр по модулю
        if 'module' in query:
            module_pattern = query['module']
            if isinstance(module_pattern, dict) and '$regex' in module_pattern:
                # Regex поиск
                pattern = re.compile(module_pattern['$regex'], re.IGNORECASE)
                module_indices = set()
                for module, indices in self._method_module_index.items():
                    if pattern.search(module):
                        module_indices.update(indices)
                if candidate_indices is not None:
                    candidate_indices &= module_indices
                else:
                    candidate_indices = module_indices
            else:
                # Точное совпадение
                module_lower = str(module_pattern).lower()
                module_indices = set(self._method_module_index.get(module_lower, []))
                if candidate_indices is not None:
                    candidate_indices &= module_indices
                else:
                    candidate_indices = module_indices
        
        # Фильтр по экспорту
        if 'is_export' in query or 'isExport' in query:
            is_export = query.get('is_export', query.get('isExport', False))
            export_indices = set(self._method_export_index)
            if candidate_indices is not None:
                if is_export:
                    candidate_indices &= export_indices
                else:
                    candidate_indices -= export_indices
            else:
                if is_export:
                    candidate_indices = export_indices
                else:
                    candidate_indices = set(range(len(self.methods))) - export_indices
        
        # Если нет кандидатов по индексам, используем все методы
        if candidate_indices is None:
            candidate_indices = set(range(len(self.methods)))
        
        # Применяем остальные фильтры (которые требуют проверки самих методов)
        results: list[BSLMethodInfo] = []
        for idx in candidate_indices:
            if idx >= len(self.methods):
                continue
            
            method_info = self.methods[idx]
            method = method_info.method
            
            # Фильтр по контексту
            if 'context' in query:
                if method.context != query['context']:
                    continue
            
            # Фильтр по типу (процедура/функция)
            if 'isproc' in query:
                if method.isproc != query['isproc']:
                    continue
            
            results.append(method_info)
        
        return results
    
    def find_calls(self, call_name: str) -> list[BSLCallInfo]:
        """
        Найти все вызовы процедуры/функции.
        
        :param call_name: Имя вызываемой процедуры/функции
        :return: Список информации о вызовах
        """
        return self.calls.get(call_name, []).copy()
    
    def find_methods_by_module(self, module: str) -> list[BSLMethodInfo]:
        """
        Найти все методы в указанном модуле.
        
        :param module: Имя модуля
        :return: Список методов модуля
        """
        return self.find_methods({'module': module})
    
    def find_exported_methods(self, module: str | None = None) -> list[BSLMethodInfo]:
        """
        Найти все экспортированные методы.
        
        :param module: Опциональное имя модуля для фильтрации
        :return: Список экспортированных методов
        """
        query: dict[str, Any] = {'is_export': True}
        if module:
            query['module'] = module
        return self.find_methods(query)
    
    def clear(self) -> None:
        """Очистить весь кеш."""
        self.methods.clear()
        self.module_vars.clear()
        self.calls.clear()
        self.modules.clear()
        self._method_name_index.clear()
        self._method_module_index.clear()
        self._method_export_index.clear()
    
    def remove_file_data(self, filename: str) -> None:
        """
        Удалить все данные конкретного файла из кеша.
        
        :param filename: Относительный путь к файлу
        """
        # 1. Удаление методов
        # Собираем индексы методов для данного файла (начиная с конца, чтобы не сломать индексы)
        indices_to_remove: list[int] = []
        for idx in range(len(self.methods) - 1, -1, -1):
            if self.methods[idx].filename == filename:
                indices_to_remove.append(idx)
        
        # Удаляем методы начиная с конца списка
        for idx in indices_to_remove:
            self.methods.pop(idx)
        
        # Перестраиваем все индексы после удаления
        self._rebuild_indices()
        
        # 2. Удаление переменных модуля
        self.module_vars.pop(filename, None)
        
        # 3. Удаление вызовов
        # Проходим по всем ключам в calls и удаляем вызовы для данного файла
        calls_to_remove: list[str] = []
        for call_name, call_list in self.calls.items():
            # Фильтруем вызовы, оставляя только те, что не относятся к удаляемому файлу
            filtered_calls = [call for call in call_list if call.filename != filename]
            if not filtered_calls:
                # Если список стал пустым, помечаем ключ для удаления
                calls_to_remove.append(call_name)
            else:
                # Обновляем список вызовов
                self.calls[call_name] = filtered_calls
        
        # Удаляем ключи с пустыми списками
        for call_name in calls_to_remove:
            self.calls.pop(call_name, None)
        
        # 4. Удаление модулей
        self.modules = [module for module in self.modules if module.filename != filename]
    
    def _rebuild_indices(self) -> None:
        """
        Перестроить все индексы после изменения списка methods.
        """
        self._method_name_index.clear()
        self._method_module_index.clear()
        self._method_export_index.clear()
        
        for idx, method_info in enumerate(self.methods):
            method = method_info.method
            
            # Индекс по имени метода
            method_name_lower = method.name.lower()
            if method_name_lower not in self._method_name_index:
                self._method_name_index[method_name_lower] = []
            self._method_name_index[method_name_lower].append(idx)
            
            # Индекс по модулю
            if method_info.module:
                module_lower = method_info.module.lower()
                if module_lower not in self._method_module_index:
                    self._method_module_index[module_lower] = []
                self._method_module_index[module_lower].append(idx)
            
            # Индекс экспортированных методов
            if method.is_export:
                self._method_export_index.append(idx)
    
    def get_stats(self) -> dict[str, int]:
        """
        Получить статистику по кешу.
        
        :return: Словарь со статистикой
        """
        return {
            'methods': len(self.methods),
            'exported_methods': len(self._method_export_index),
            'module_vars': sum(len(vars_list) for vars_list in self.module_vars.values()),
            'calls': sum(len(calls_list) for calls_list in self.calls.values()),
            'unique_calls': len(self.calls),
            'modules': len(self.modules)
        }

