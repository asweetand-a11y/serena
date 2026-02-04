"""
Тест для поиска конкретной процедуры УстановитьОграничениеТиповЭлементовАналитикПремирования.
"""

import os
import time
from pathlib import Path

import pytest

from serena.agent import SerenaAgent
from serena.project import Project
from serena.tools.symbol_tools import FindSymbolTool


@pytest.mark.bsl
class TestFindSpecificProcedure:
    """Тест для поиска конкретной процедуры."""

    @pytest.fixture(scope="class")
    def test_project_path(self) -> Path:
        """Возвращает путь к тестовому проекту."""
        # Путь к проекту 1C (проверяем оба варианта: Windows и Docker)
        project_paths = [
            Path(r"D:\1C\BASE"),  # Windows путь
            Path("/workspaces/serena/1C/BASE"),  # Docker путь
        ]
        
        for project_path in project_paths:
            if project_path.exists():
                return project_path
        
        # Если ни один путь не найден, пропускаем тест
        pytest.skip(f"Test project not found at any of: {[str(p) for p in project_paths]}")

    @pytest.fixture(scope="class")
    def agent(self, test_project_path: Path) -> SerenaAgent:
        """Создает агент для тестирования."""
        # Создаем агент без проекта (он загрузит проект сам)
        agent = SerenaAgent()
        # Активируем проект по пути, чтобы запустить индексацию
        agent.activate_project_from_path_or_name(str(test_project_path))
        # Ждем немного, чтобы индексация началась
        time.sleep(2)
        return agent

    def test_find_procedure(self, agent: SerenaAgent, test_project_path: Path):
        """Тест поиска процедуры УстановитьОграничениеТиповЭлементовАналитикПремирования."""
        procedure_name = "УстановитьОграничениеТиповЭлементовАналитикПремирования"
        
        print(f"\n{'='*80}")
        print(f"Поиск процедуры: {procedure_name}")
        print(f"{'='*80}")
        
        # Ждем инициализации менеджера языковых серверов (инициализируется асинхронно)
        max_wait = 60  # Максимум 60 секунд
        wait_interval = 1  # Проверяем каждую секунду
        elapsed = 0
        ls_manager = None
        
        while elapsed < max_wait:
            ls_manager = agent.get_language_server_manager()
            if ls_manager is not None:
                break
            time.sleep(wait_interval)
            elapsed += wait_interval
        
        if ls_manager is None:
            pytest.fail(f"Language server manager not initialized after {elapsed}s")
        
        # Создаем инструмент find_symbol
        find_symbol_tool = FindSymbolTool(agent=agent)
        
        # Ищем процедуру
        print(f"\nВыполняем поиск процедуры '{procedure_name}'...")
        start_time = time.time()
        
        try:
            result = find_symbol_tool.apply(
                name_path_pattern=procedure_name,
                depth=0,
                relative_path="",
                include_body=True,  # Включаем тело процедуры
                include_kinds=[],
                exclude_kinds=[],
                substring_matching=True,
                max_answer_chars=-1,
            )
            elapsed_time = time.time() - start_time
            
            # Парсим результат (JSON строка)
            import json
            symbols = json.loads(result)
            
            print(f"\n{'='*80}")
            print(f"Результаты поиска:")
            print(f"{'='*80}")
            print(f"  - Время поиска: {elapsed_time:.3f}s")
            print(f"  - Найдено символов: {len(symbols)}")
            
            if len(symbols) == 0:
                print(f"\n[ERROR] Процедура '{procedure_name}' не найдена!")
                print(f"\nПроверяем кеш...")
                
                # Проверяем кеш напрямую
                bsl_ls = None
                for ls in ls_manager.iter_language_servers():
                    if ls.language.value == "bsl":
                        bsl_ls = ls
                        break
                
                if bsl_ls:
                    cache_size = len(bsl_ls._document_symbols_cache)
                    print(f"  - Записей в кеше: {cache_size}")
                    
                    # Проверяем, есть ли файл с процедурой в кеше
                    target_file = "src/cf/CommonModules/ibs_МодульПремированияКлиентСервер/Ext/Module.bsl"
                    found_in_cache = False
                    for cache_key, (file_hash, doc_symbols) in bsl_ls._document_symbols_cache.items():
                        if isinstance(cache_key, tuple):
                            file_path = cache_key[0]
                        else:
                            file_path = cache_key
                        
                        # Проверяем, содержит ли путь нужный файл
                        if "МодульПремирования" in file_path or "ibs_МодульПремирования" in file_path:
                            found_in_cache = True
                            print(f"\n  [OK] Файл найден в кеше: {file_path}")
                            
                            # Проверяем символы в этом файле
                            if doc_symbols and doc_symbols.root_symbols:
                                print(f"  - Символов в файле: {len(doc_symbols.root_symbols)}")
                                for symbol in doc_symbols.root_symbols:
                                    symbol_name = getattr(symbol, 'name', 'Unknown')
                                    print(f"    - {symbol_name}")
                                    if procedure_name.lower() in symbol_name.lower():
                                        print(f"      [MATCH] Найдено совпадение!")
                            
                            # Также проверяем дочерние символы
                            def check_children(symbol, depth=0):
                                indent = "  " * (depth + 1)
                                if hasattr(symbol, 'children') and symbol.children:
                                    for child in symbol.children:
                                        child_name = getattr(child, 'name', 'Unknown')
                                        print(f"{indent}- {child_name}")
                                        if procedure_name.lower() in child_name.lower():
                                            print(f"{indent}  [MATCH] Найдено совпадение!")
                                        check_children(child, depth + 1)
                            
                            for symbol in doc_symbols.root_symbols:
                                check_children(symbol)
                            
                            if target_file.replace("\\", "/") in file_path.replace("\\", "/"):
                                break
                    
                    if not found_in_cache:
                        print(f"\n  [ERROR] Файл {target_file} не найден в кеше!")
                        print(f"\n  Файлы в кеше (все):")
                        for i, (cache_key, (file_hash, doc_symbols)) in enumerate(bsl_ls._document_symbols_cache.items()):
                            if isinstance(cache_key, tuple):
                                file_path = cache_key[0]
                            else:
                                file_path = cache_key
                            print(f"    {i+1}. {file_path}")
                
                pytest.fail(f"Процедура '{procedure_name}' не найдена")
            
            # Выводим информацию о найденных символах
            print(f"\nНайденные символы:")
            for i, symbol in enumerate(symbols, 1):
                print(f"\n  [{i}] {symbol.get('name', 'Unknown')}")
                print(f"      Тип: {symbol.get('kind', 'Unknown')}")
                print(f"      Файл: {symbol.get('relative_path', 'Unknown')}")
                if 'start_line' in symbol:
                    print(f"      Строка: {symbol.get('start_line', 'Unknown')}")
                if 'body' in symbol and symbol['body']:
                    body_preview = symbol['body'][:200].replace('\n', ' ')
                    print(f"      Тело (первые 200 символов): {body_preview}...")
            
            # Проверяем, что нашли именно нужную процедуру
            found_procedure = False
            for symbol in symbols:
                if symbol.get('name') == procedure_name:
                    found_procedure = True
                    print(f"\n[OK] Процедура '{procedure_name}' найдена!")
                    print(f"     Файл: {symbol.get('relative_path', 'Unknown')}")
                    if 'start_line' in symbol:
                        print(f"     Строка: {symbol.get('start_line', 'Unknown')}")
                    break
            
            if not found_procedure:
                print(f"\n[WARNING] Процедура с точным именем '{procedure_name}' не найдена, но найдены похожие:")
                for symbol in symbols:
                    print(f"  - {symbol.get('name', 'Unknown')}")
            
            assert len(symbols) > 0, f"Процедура '{procedure_name}' не найдена"
            
        except Exception as e:
            elapsed_time = time.time() - start_time
            print(f"\n[ERROR] Ошибка при поиске: {e}")
            print(f"        Время до ошибки: {elapsed_time:.3f}s")
            raise

