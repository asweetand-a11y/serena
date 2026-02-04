"""
Тест для проверки построения кеша и поиска символов через find_symbol.

Тест проверяет:
1. Построение кеша из данных в папке src/cf
2. Вызов find_symbol для поиска данных в кеше
3. Прогон 40 вызовов find_symbol для проверки производительности
"""

import os
import time
from pathlib import Path

import pytest

from serena.agent import SerenaAgent
from serena.project import Project
from serena.tools.symbol_tools import FindSymbolTool


@pytest.mark.bsl
class TestBSLCacheFindSymbol:
    """Тест для проверки построения кеша и поиска символов через find_symbol."""

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
    def project(self, test_project_path: Path) -> Project:
        """Создает проект для тестирования."""
        project = Project.load(str(test_project_path))
        return project

    @pytest.fixture(scope="class")
    def agent(self, project: Project) -> SerenaAgent:
        """Создает агент для тестирования."""
        # Создаем агент без проекта (он загрузит проект сам)
        agent = SerenaAgent()
        # Активируем проект по пути, чтобы запустить индексацию
        agent.activate_project_from_path_or_name(project.project_root)
        # Ждем немного, чтобы индексация началась
        time.sleep(2)
        return agent

    def test_build_cache_from_src_cf(self, agent: SerenaAgent, test_project_path: Path):
        """Тест 1: Построение кеша из данных в папке src/cf."""
        # Проверяем, что папка src/cf существует
        src_cf_path = test_project_path / "src" / "cf"
        assert src_cf_path.exists(), f"Path {src_cf_path} does not exist"
        
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
        
        assert ls_manager is not None, f"Language server manager should be initialized (waited {elapsed}s)"
        
        # Находим BSL language server
        bsl_ls = None
        for ls in ls_manager.iter_language_servers():
            if ls.language.value == "bsl":
                bsl_ls = ls
                break
        
        assert bsl_ls is not None, "BSL language server should be initialized"
        
        # Ждем завершения индексации (если она еще идет)
        # Проверяем наличие кеша
        cache_file = bsl_ls.cache_dir / bsl_ls.DOCUMENT_SYMBOL_CACHE_FILENAME
        max_wait_time = 300  # 5 минут максимум
        wait_interval = 5  # Проверяем каждые 5 секунд
        elapsed = 0
        
        while elapsed < max_wait_time:
            if cache_file.exists():
                # Проверяем, что кеш не пустой
                cache_size = len(bsl_ls._document_symbols_cache)
                if cache_size > 0:
                    print(f"\n[OK] Cache built successfully: {cache_size} entries")
                    break
            time.sleep(wait_interval)
            elapsed += wait_interval
            print(f"Waiting for cache to be built... ({elapsed}s)")
        
        assert cache_file.exists(), f"Cache file should exist at {cache_file}"
        assert len(bsl_ls._document_symbols_cache) > 0, "Cache should not be empty"
        
        print(f"\nCache statistics:")
        print(f"  - Cache file: {cache_file}")
        print(f"  - Cache entries: {len(bsl_ls._document_symbols_cache)}")
        print(f"  - Cache directory: {bsl_ls.cache_dir}")

    def test_find_symbol_40_times(self, agent: SerenaAgent):
        """Тест 2 и 3: Вызов find_symbol 40 раз для поиска данных в кеше."""
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
        
        # Список символов для поиска (можно использовать реальные имена из проекта)
        # Используем разные паттерны для разнообразия
        search_patterns = [
            "УстановитьОграничениеТиповЭлементовАналитикПремирования",
            "МодульПремирования",
            "Премирование",
            "Начисление",
            "Зарплата",
            "Документ",
            "Справочник",
            "Обработка",
            "Отчет",
            "Регистр",
            "Функция",
            "Процедура",
            "Получить",
            "Установить",
            "Создать",
            "Удалить",
            "Заполнить",
            "Рассчитать",
            "Обработать",
            "Выполнить",
            "Проверить",
            "Сохранить",
            "Загрузить",
            "Экспорт",
            "Импорт",
            "Обновить",
            "Найти",
            "Открыть",
            "Закрыть",
            "Печать",
            "Формировать",
            "Записать",
            "Прочитать",
            "Очистить",
            "Инициализировать",
            "Завершить",
            "Начать",
            "Остановить",
            "Запустить",
            "Выполнить",
        ]
        
        # Дополняем до 40 паттернов, повторяя некоторые
        while len(search_patterns) < 40:
            search_patterns.extend(search_patterns[:40 - len(search_patterns)])
        search_patterns = search_patterns[:40]
        
        results = []
        total_time = 0
        
        print(f"\nStarting 40 find_symbol calls...")
        
        for i, pattern in enumerate(search_patterns, 1):
            start_time = time.time()
            try:
                result = find_symbol_tool.apply(
                    name_path_pattern=pattern,
                    depth=0,
                    relative_path="",
                    include_body=False,
                    include_kinds=[],
                    exclude_kinds=[],
                    substring_matching=True,
                    max_answer_chars=-1,
                )
                elapsed = time.time() - start_time
                total_time += elapsed
                
                # Парсим результат (JSON строка)
                import json
                try:
                    symbols = json.loads(result)
                    symbol_count = len(symbols) if isinstance(symbols, list) else 0
                except:
                    symbol_count = 0
                
                results.append({
                    "pattern": pattern,
                    "time": elapsed,
                    "symbols_found": symbol_count,
                    "success": True
                })
                
                print(f"  [{i:2d}/40] Pattern: {pattern[:50]:<50} | Time: {elapsed:.3f}s | Symbols: {symbol_count}")
                
            except Exception as e:
                elapsed = time.time() - start_time
                total_time += elapsed
                results.append({
                    "pattern": pattern,
                    "time": elapsed,
                    "symbols_found": 0,
                    "success": False,
                    "error": str(e)
                })
                print(f"  [{i:2d}/40] Pattern: {pattern[:50]:<50} | Time: {elapsed:.3f}s | ERROR: {e}")
        
        # Статистика
        successful = sum(1 for r in results if r["success"])
        failed = len(results) - successful
        total_symbols = sum(r["symbols_found"] for r in results)
        avg_time = total_time / len(results) if results else 0
        min_time = min((r["time"] for r in results), default=0)
        max_time = max((r["time"] for r in results), default=0)
        
        print(f"\n{'='*80}")
        print(f"Test Results Summary:")
        print(f"  - Total calls: {len(results)}")
        print(f"  - Successful: {successful}")
        print(f"  - Failed: {failed}")
        print(f"  - Total symbols found: {total_symbols}")
        print(f"  - Total time: {total_time:.3f}s")
        print(f"  - Average time per call: {avg_time:.3f}s")
        print(f"  - Min time: {min_time:.3f}s")
        print(f"  - Max time: {max_time:.3f}s")
        print(f"{'='*80}")
        
        # Проверки
        assert len(results) == 40, f"Should have 40 results, got {len(results)}"
        assert successful > 0, "At least some searches should succeed"
        assert avg_time < 5.0, f"Average time should be reasonable (<5s), got {avg_time:.3f}s"
        
        # Проверяем, что кеш используется (время должно быть относительно быстрым)
        # Если среднее время больше 2 секунд, возможно кеш не используется
        if avg_time > 2.0:
            print(f"\n[WARNING] WARNING: Average time is {avg_time:.3f}s, which suggests cache might not be used effectively")
        else:
            print(f"\n[OK] Cache appears to be working effectively (avg time: {avg_time:.3f}s)")

