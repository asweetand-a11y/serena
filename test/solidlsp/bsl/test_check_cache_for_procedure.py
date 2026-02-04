"""
Тест для проверки наличия процедуры в кеше.
"""

import time
from pathlib import Path

import pytest

from serena.agent import SerenaAgent


@pytest.mark.bsl
def test_check_procedure_in_cache():
    """Проверяет, есть ли процедура УстановитьОграничениеТиповЭлементовАналитикПремирования в кеше."""
    procedure_name = "УстановитьОграничениеТиповЭлементовАналитикПремирования"
    target_file = "src/cf/CommonModules/ibs_МодульПремированияКлиентСервер/Ext/Module.bsl"
    
    # Путь к проекту
    project_path = Path(r"D:\1C\BASE")
    if not project_path.exists():
        pytest.skip(f"Test project not found at {project_path}")
    
    # Создаем агент
    agent = SerenaAgent()
    agent.activate_project_from_path_or_name(str(project_path))
    
    # Ждем инициализации менеджера языковых серверов
    max_wait = 60
    wait_interval = 1
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
    
    # Находим BSL language server
    bsl_ls = None
    for ls in ls_manager.iter_language_servers():
        if ls.language.value == "bsl":
            bsl_ls = ls
            break
    
    if bsl_ls is None:
        pytest.fail("BSL language server not found")
    
    # Ждем завершения индексации (если она еще идет)
    print(f"\nОжидание завершения индексации...")
    cache_file = bsl_ls.cache_dir / bsl_ls.DOCUMENT_SYMBOL_CACHE_FILENAME
    max_wait_time = 300  # 5 минут максимум
    wait_interval = 5  # Проверяем каждые 5 секунд
    elapsed = 0
    
    while elapsed < max_wait_time:
        if cache_file.exists():
            cache_size = len(bsl_ls._document_symbols_cache)
            if cache_size > 0:
                # Проверяем, увеличивается ли размер кеша (индексация идет)
                time.sleep(wait_interval)
                new_cache_size = len(bsl_ls._document_symbols_cache)
                if new_cache_size == cache_size:
                    # Размер не изменился, индексация завершена
                    print(f"Индексация завершена. Размер кеша: {cache_size}")
                    break
        time.sleep(wait_interval)
        elapsed += wait_interval
        print(f"  Ожидание... ({elapsed}s, размер кеша: {len(bsl_ls._document_symbols_cache)})")
    
    print(f"\n{'='*80}")
    print(f"Проверка кеша для процедуры: {procedure_name}")
    print(f"{'='*80}")
    print(f"Размер кеша: {len(bsl_ls._document_symbols_cache)} записей")
    
    # Ищем файл в кеше
    found_file = False
    found_procedure = False
    
    for cache_key, (file_hash, doc_symbols) in bsl_ls._document_symbols_cache.items():
        if isinstance(cache_key, tuple):
            file_path = cache_key[0]
        else:
            file_path = cache_key
        
        # Проверяем, это ли нужный файл
        if "МодульПремирования" in file_path or "ibs_МодульПремирования" in file_path:
            found_file = True
            print(f"\n[OK] Файл найден в кеше: {file_path}")
            print(f"     Hash: {file_hash[:16]}...")
            
            if doc_symbols and doc_symbols.root_symbols:
                print(f"     Символов в файле: {len(doc_symbols.root_symbols)}")
                
                # Функция для рекурсивного поиска символов
                def search_symbols(symbols, depth=0):
                    nonlocal found_procedure
                    indent = "  " * depth
                    for symbol in symbols:
                        symbol_name = getattr(symbol, 'name', 'Unknown')
                        symbol_kind = getattr(symbol, 'kind', 'Unknown')
                        
                        # Проверяем, это ли нужная процедура
                        if procedure_name.lower() in symbol_name.lower() or symbol_name == procedure_name:
                            found_procedure = True
                            print(f"{indent}[MATCH] {symbol_name} (kind: {symbol_kind})")
                            if hasattr(symbol, 'start_line'):
                                print(f"{indent}       Строка: {symbol.start_line}")
                            if hasattr(symbol, 'children') and symbol.children:
                                print(f"{indent}       Дочерних символов: {len(symbol.children)}")
                        else:
                            print(f"{indent}- {symbol_name} (kind: {symbol_kind})")
                        
                        # Рекурсивно проверяем дочерние символы
                        if hasattr(symbol, 'children') and symbol.children:
                            search_symbols(symbol.children, depth + 1)
                
                search_symbols(doc_symbols.root_symbols)
                
                if not found_procedure:
                    print(f"\n[WARNING] Процедура '{procedure_name}' не найдена в символах файла!")
                    print(f"          Но файл присутствует в кеше.")
            else:
                print(f"     [WARNING] Файл в кеше, но символы отсутствуют!")
            
            break
    
    if not found_file:
        print(f"\n[ERROR] Файл {target_file} не найден в кеше!")
        print(f"\nВсе файлы в кеше:")
        for i, (cache_key, (file_hash, doc_symbols)) in enumerate(bsl_ls._document_symbols_cache.items(), 1):
            if isinstance(cache_key, tuple):
                file_path = cache_key[0]
            else:
                file_path = cache_key
            print(f"  {i}. {file_path}")
    
    print(f"\n{'='*80}")
    print(f"Итоги:")
    print(f"  - Файл в кеше: {'Да' if found_file else 'Нет'}")
    print(f"  - Процедура в кеше: {'Да' if found_procedure else 'Нет'}")
    print(f"{'='*80}")
    
    assert found_file, f"Файл {target_file} должен быть в кеше"
    assert found_procedure, f"Процедура {procedure_name} должна быть в кеше"

