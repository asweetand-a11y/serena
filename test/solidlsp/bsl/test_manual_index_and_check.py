"""
Тест для ручного запуска индексации и проверки кеша.
"""

import os
import time
from pathlib import Path

import pytest

from serena.agent import SerenaAgent


@pytest.mark.bsl
def test_manual_index_and_check_procedure():
    """Ручной запуск индексации и проверка наличия процедуры в кеше."""
    procedure_name = "УстановитьОграничениеТиповЭлементовАналитикПремирования"
    target_file = "src/cf/CommonModules/ibs_МодульПремированияКлиентСервер/Ext/Module.bsl"
    
    # Путь к проекту
    project_path = Path(r"D:\1C\BASE")
    if not project_path.exists():
        pytest.skip(f"Test project not found at {project_path}")
    
    print(f"\n{'='*80}")
    print(f"Ручной запуск индексации и проверка кеша")
    print(f"{'='*80}")
    
    # Создаем агент
    agent = SerenaAgent()
    agent.activate_project_from_path_or_name(str(project_path))
    
    # Ждем инициализации менеджера языковых серверов
    print("\nОжидание инициализации language server manager...")
    max_wait = 60
    wait_interval = 1
    elapsed = 0
    ls_manager = None
    
    while elapsed < max_wait:
        ls_manager = agent.get_language_server_manager()
        if ls_manager is not None:
            print(f"[OK] Language server manager инициализирован")
            break
        time.sleep(wait_interval)
        elapsed += wait_interval
        print(f"  Ожидание... ({elapsed}s)")
    
    if ls_manager is None:
        pytest.fail(f"Language server manager not initialized after {elapsed}s")
    
    # Находим BSL language server
    from solidlsp.language_servers.bsl_language_server import BSLLanguageServer
    bsl_ls: BSLLanguageServer | None = None
    for ls in ls_manager.iter_language_servers():
        if isinstance(ls, BSLLanguageServer):
            bsl_ls = ls
            break
    
    if bsl_ls is None:
        pytest.fail("BSL language server not found")
    
    print(f"\n[OK] BSL language server найден")
    print(f"  - enable_local_parser: {bsl_ls.enable_local_parser}")
    print(f"  - _local_cache: {bsl_ls._local_cache is not None}")
    print(f"  - Размер кеша до индексации: {len(bsl_ls._document_symbols_cache)}")
    
    # Проверяем, нужно ли запускать индексацию
    if not bsl_ls.enable_local_parser:
        print(f"\n[WARNING] enable_local_parser выключен! Включаем...")
        bsl_ls.enable_local_parser = True
        if bsl_ls._local_cache is None:
            from solidlsp.bsl_cache import BSLCache
            bsl_ls._local_cache = BSLCache()
            bsl_ls._file_content_cache = {}
            bsl_ls._converted_files = set()
    
    # Запускаем индексацию вручную
    print(f"\n{'='*80}")
    print(f"Запуск индексации...")
    print(f"{'='*80}")
    
    # Получаем все BSL файлы из проекта
    project = agent.get_active_project()
    if project is None:
        pytest.fail("Active project not found")
    
    print(f"Проект: {project.project_name}")
    print(f"Корень проекта: {project.project_root}")
    
    # Собираем BSL файлы напрямую из директории src/cf
    print(f"\nСбор BSL файлов из src/cf...")
    src_cf_dir = os.path.join(project.project_root, "src", "cf")
    bsl_files = []
    
    if os.path.exists(src_cf_dir):
        for root, dirs, files in os.walk(src_cf_dir):
            # Пропускаем игнорируемые директории
            dirs[:] = [d for d in dirs if not bsl_ls.is_ignored_dirname(d)]
            
            for file in files:
                if file.endswith('.bsl'):
                    abs_path = os.path.join(root, file)
                    rel_path = os.path.relpath(abs_path, project.project_root)
                    # Нормализуем путь для Windows
                    rel_path = rel_path.replace('\\', '/')
                    bsl_files.append((rel_path, abs_path))
    
    print(f"Найдено BSL файлов в src/cf: {len(bsl_files)}")
    
    # Запускаем индексацию через метод BSL language server
    if bsl_ls.enable_local_parser and bsl_ls._local_cache is not None:
        print(f"\nЗапуск индексации через локальный парсер...")
        
        if bsl_files:
            # Используем все файлы из src/cf
            print(f"  Индексируем {len(bsl_files)} файлов из src/cf...")
            
            try:
                # Используем внутренний метод индексации
                # Метод принимает относительные пути
                rel_paths = [rel for rel, _ in bsl_files]
                results = bsl_ls._index_files_with_local_parser(
                    file_paths=rel_paths,
                    save_cache_callback=lambda: ls_manager.save_all_caches()
                )
                
                success_count = sum(1 for r in results.values() if r is None)
                error_count = len(results) - success_count
                print(f"\n[OK] Индексация завершена: {success_count} успешно, {error_count} ошибок")
            except Exception as e:
                print(f"\n[ERROR] Ошибка при индексации: {e}")
                import traceback
                traceback.print_exc()
        else:
            print(f"\n[WARNING] Файлы в src/cf не найдены")
    else:
        print(f"\n[ERROR] Локальный парсер не доступен для индексации")
        print(f"  enable_local_parser: {bsl_ls.enable_local_parser}")
        print(f"  _local_cache: {bsl_ls._local_cache is not None}")
    
    # Сохраняем кеш
    print(f"\nСохранение кеша...")
    try:
        ls_manager.save_all_caches()
        print(f"[OK] Кеш сохранен")
    except Exception as e:
        print(f"[WARNING] Ошибка при сохранении кеша: {e}")
    
    # Проверяем кеш
    print(f"\n{'='*80}")
    print(f"Проверка кеша после индексации")
    print(f"{'='*80}")
    print(f"Размер кеша: {len(bsl_ls._document_symbols_cache)} записей")
    
    # Ищем файл в кеше
    found_file = False
    found_procedure = False
    
    print(f"\nПроверка всех файлов в кеше:")
    for cache_key, (file_hash, doc_symbols) in bsl_ls._document_symbols_cache.items():
        if isinstance(cache_key, tuple):
            file_path = cache_key[0]
        else:
            file_path = cache_key
        
        # Проверяем все файлы, содержащие "МодульПремирования"
        if "МодульПремирования" in file_path or "ibs_МодульПремирования" in file_path or "Премирования" in file_path:
            found_file = True
            print(f"\n[OK] Файл найден в кеше: {file_path}")
            
            if doc_symbols and doc_symbols.root_symbols:
                print(f"  - Символов в файле: {len(doc_symbols.root_symbols)}")
                
                def search_symbols(symbols, depth=0):
                    nonlocal found_procedure
                    indent = "  " * (depth + 1)
                    for symbol in symbols:
                        symbol_name = getattr(symbol, 'name', 'Unknown')
                        symbol_kind = getattr(symbol, 'kind', 'Unknown')
                        
                        # Более гибкий поиск
                        if (procedure_name.lower() in symbol_name.lower() or 
                            symbol_name.lower() in procedure_name.lower() or
                            "ОграничениеТипов" in symbol_name or
                            "АналитикПремирования" in symbol_name):
                            found_procedure = True
                            print(f"{indent}[MATCH] {symbol_name} (kind: {symbol_kind})")
                            if hasattr(symbol, 'start_line'):
                                print(f"{indent}       Строка: {symbol.start_line}")
                            if hasattr(symbol, 'children') and symbol.children:
                                print(f"{indent}       Дочерних символов: {len(symbol.children)}")
                        else:
                            # Показываем все символы для диагностики
                            print(f"{indent}- {symbol_name} (kind: {symbol_kind})")
                        
                        if hasattr(symbol, 'children') and symbol.children:
                            search_symbols(symbol.children, depth + 1)
                
                search_symbols(doc_symbols.root_symbols)
            else:
                print(f"  [WARNING] Символы отсутствуют в файле")
    
    # Если не нашли, показываем все файлы в кеше
    if not found_file:
        print(f"\n[WARNING] Файл с 'МодульПремирования' не найден в кеше")
        print(f"\nВсе файлы в кеше ({len(bsl_ls._document_symbols_cache)}):")
        for i, (cache_key, (file_hash, doc_symbols)) in enumerate(bsl_ls._document_symbols_cache.items(), 1):
            if isinstance(cache_key, tuple):
                file_path = cache_key[0]
            else:
                file_path = cache_key
            symbol_count = len(doc_symbols.root_symbols) if doc_symbols and doc_symbols.root_symbols else 0
            print(f"  {i}. {file_path} ({symbol_count} символов)")
    
    print(f"\n{'='*80}")
    print(f"Итоги:")
    print(f"  - Файл в кеше: {'Да' if found_file else 'Нет'}")
    print(f"  - Процедура в кеше: {'Да' if found_procedure else 'Нет'}")
    print(f"{'='*80}")
    
    assert found_file, f"Файл {target_file} должен быть в кеше"
    assert found_procedure, f"Процедура {procedure_name} должна быть в кеше"

