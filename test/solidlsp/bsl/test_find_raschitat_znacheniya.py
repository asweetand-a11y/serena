"""Тест поиска процедуры РассчитатьЗначенияПоказателей из кеша."""

import os
import time
from pathlib import Path
import pytest
import json
from serena.agent import SerenaAgent
from serena.tools.symbol_tools import FindSymbolTool

@pytest.mark.bsl
class TestFindRaschitatZnacheniya:
    @pytest.fixture(scope="class")
    def test_project_path(self) -> Path:
        project_paths = [
            Path(r"D:\1C\RZDZUP"),
            Path("/workspaces/serena/1C/RZDZUP"),
        ]
        for project_path in project_paths:
            if project_path.exists():
                print(f"\nИспользуется путь к проекту: {project_path}")
                return project_path
        pytest.fail(f"Путь к проекту не найден. Пробовали: {project_paths}")

    @pytest.fixture(scope="class")
    def agent(self, test_project_path: Path) -> SerenaAgent:
        agent = SerenaAgent()
        agent.activate_project_from_path_or_name(str(test_project_path))
        
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
        
        assert ls_manager is not None, f"Менеджер языкового сервера не инициализирован после {elapsed}s"
        
        bsl_ls = None
        for ls in ls_manager.iter_language_servers():
            if ls.language.value == "bsl":
                bsl_ls = ls
                break
        assert bsl_ls is not None, "BSL языковой сервер должен быть инициализирован"

        # Проверяем наличие кеша
        cache_file = bsl_ls.cache_dir / bsl_ls.DOCUMENT_SYMBOL_CACHE_FILENAME
        max_wait_time = 60
        wait_interval = 2
        elapsed = 0
        
        while elapsed < max_wait_time:
            if cache_file.exists():
                # Загружаем кеш
                bsl_ls._load_document_symbols_cache()
                cache_size = len(bsl_ls._document_symbols_cache)
                if cache_size > 0:
                    print(f"\n[OK] Кеш загружен: {cache_size} записей")
                    break
            time.sleep(wait_interval)
            elapsed += wait_interval
            print(f"Ожидание загрузки кеша... ({elapsed}s, текущий размер кеша: {len(bsl_ls._document_symbols_cache)})")
        
        if not cache_file.exists() or len(bsl_ls._document_symbols_cache) == 0:
            pytest.fail("Кеш не найден или пуст после ожидания.")

        print("\nСтатистика кеша:")
        print(f"  - Файл кеша: {cache_file}")
        print(f"  - Записей в кеше: {len(bsl_ls._document_symbols_cache)}")
        print(f"  - Директория кеша: {bsl_ls.cache_dir}")
        
        return agent

    def test_find_procedure_raschitat_znacheniya(self, agent: SerenaAgent):
        procedure_name = "РассчитатьЗначенияПоказателей"
        find_symbol_tool = FindSymbolTool(agent=agent)
        
        print(f"\n{'='*80}")
        print(f"Поиск процедуры: {procedure_name}")
        print(f"{'='*80}")
        
        start_time = time.time()
        symbols = []
        try:
            # Пробуем сначала точный поиск
            result_json = find_symbol_tool.apply(procedure_name, include_body=True, substring_matching=False)
            symbols = json.loads(result_json)
            
            # Если не найдено, пробуем поиск по подстроке
            if len(symbols) == 0:
                print(f"Точный поиск не дал результатов, пробуем поиск по подстроке...")
                result_json = find_symbol_tool.apply(procedure_name, include_body=True, substring_matching=True)
                symbols = json.loads(result_json)
        except Exception as e:
            print(f"Ошибка при вызове find_symbol: {e}")
            import traceback
            traceback.print_exc()
        
        end_time = time.time()
        duration = end_time - start_time
        
        print(f"\n{'='*80}")
        print(f"Результаты поиска:")
        print(f"{'='*80}")
        print(f"  - Время поиска: {duration:.3f}s")
        print(f"  - Найдено символов: {len(symbols)}")
        
        if len(symbols) == 0:
            print(f"\n[ERROR] Процедура '{procedure_name}' не найдена!")
            
            bsl_ls = None
            ls_manager = agent.get_language_server_manager()
            if ls_manager:
                for ls in ls_manager.iter_language_servers():
                    if ls.language.value == "bsl":
                        bsl_ls = ls
                        break
            
            if bsl_ls:
                print(f"\nПроверяем кеш напрямую...")
                print(f"  - Записей в кеше: {len(bsl_ls._document_symbols_cache)}")
                
                # Ищем файлы, которые могут содержать эту процедуру
                found_files = []
                for cache_key, (file_hash, doc_symbols) in bsl_ls._document_symbols_cache.items():
                    relative_file_path = cache_key[0] if isinstance(cache_key, tuple) else cache_key
                    if doc_symbols and doc_symbols.root_symbols:
                        for symbol in doc_symbols.root_symbols:
                            symbol_name = symbol.get('name', 'Unknown')
                            if procedure_name.lower() in symbol_name.lower():
                                found_files.append((relative_file_path, symbol_name))
                                print(f"\n  [OK] Найдено совпадение в файле: {relative_file_path}")
                                print(f"      Символ: {symbol_name}")
                
                if not found_files:
                    print(f"\n  [ERROR] Процедура '{procedure_name}' не найдена в кеше!")
                    print(f"\n  Первые 10 файлов в кеше:")
                    for i, (cache_key, (file_hash, doc_symbols)) in enumerate(list(bsl_ls._document_symbols_cache.items())[:10]):
                        relative_file_path = cache_key[0] if isinstance(cache_key, tuple) else cache_key
                        symbol_count = len(doc_symbols.root_symbols) if doc_symbols and doc_symbols.root_symbols else 0
                        print(f"    {i+1}. {relative_file_path} ({symbol_count} символов)")
            
            pytest.fail(f"Процедура '{procedure_name}' не найдена")
        
        print(f"\nНайденные символы:")
        print(f"Всего символов: {len(symbols)}")
        found_exact_match = False
        for i, symbol in enumerate(symbols, 1):
            # Получаем имя символа (теперь поле name должно быть доступно)
            symbol_name = symbol.get('name', 'Unknown')
            name_path = symbol.get('name_path', 'Unknown')
            print(f"\n  [{i}] Имя: {symbol_name}")
            print(f"      Путь: {name_path}")
            print(f"      Тип: {symbol.get('kind_name', symbol.get('kind', 'Unknown'))}")
            print(f"      Файл: {symbol.get('relative_path', 'Unknown')}")
            if 'body' in symbol:
                body_preview = symbol['body'][:200] if len(symbol['body']) > 200 else symbol['body']
                print(f"      Тело (первые 200 символов): {body_preview}...")
            
            # Проверяем точное совпадение или совпадение по подстроке
            if symbol_name and symbol_name.lower() == procedure_name.lower():
                found_exact_match = True
                print(f"      [MATCH] Точное совпадение найдено!")
            elif symbol_name and procedure_name.lower() in symbol_name.lower():
                found_exact_match = True
                print(f"      [MATCH] Совпадение по подстроке найдено!")
            elif name_path and procedure_name.lower() in name_path.lower():
                found_exact_match = True
                print(f"      [MATCH] Совпадение в name_path найдено!")
        
        assert len(symbols) > 0, f"Процедура '{procedure_name}' должна быть найдена"
        assert found_exact_match or any(
            procedure_name.lower() in (s.get('name', '') or s.get('name_path', '')).lower() 
            for s in symbols
        ), f"Процедура '{procedure_name}' не найдена среди результатов поиска. Найдено символов: {len(symbols)}"

