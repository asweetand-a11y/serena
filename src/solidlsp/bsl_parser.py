"""
Python парсер BSL кода для массовой индексации.
Аналог onec-syntaxparser, но полностью на Python.
"""

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BSLParam:
    """Параметр процедуры или функции."""
    name: str
    byval: bool  # True если "Знач", False если по ссылке
    default: str | None = None


@dataclass
class BSLCallPosition:
    """Позиция вызова процедуры/функции в коде."""
    call: str  # Имя вызываемой процедуры/функции
    line: int  # Номер строки (0-based)
    character: int  # Позиция символа в строке (0-based)


@dataclass
class BSLModuleVar:
    """Переменная модуля."""
    name: str
    is_export: bool
    description: str = ""


@dataclass
class BSLMethod:
    """Процедура или функция BSL."""
    name: str
    line: int  # Номер строки начала (0-based)
    endline: int  # Номер строки конца (0-based)
    isproc: bool  # True для процедуры, False для функции
    is_export: bool
    params: list[BSLParam] = field(default_factory=list)
    description: str = ""
    context: str = ""  # НаСервере, НаКлиенте, НаСервереБезКонтекста, или пусто
    calls_position: list[BSLCallPosition] = field(default_factory=list)


@dataclass
class BSLParseResult:
    """Результат парсинга BSL кода."""
    methods: list[BSLMethod] = field(default_factory=list)
    global_calls: list[BSLCallPosition] = field(default_factory=list)
    module_vars: dict[str, BSLModuleVar] = field(default_factory=dict)


class BSLParser:
    """Парсер BSL кода на Python."""
    
    # Регулярные выражения для парсинга
    PROC_PATTERN = re.compile(
        r'^\s*(?:&НаСервере|&НаКлиенте|&НаСервереБезКонтекста)?\s*(?:Экспорт\s+)?Процедура\s+([а-яёА-ЯЁ\w]+)\s*\(',
        re.IGNORECASE | re.MULTILINE
    )
    
    FUNC_PATTERN = re.compile(
        r'^\s*(?:&НаСервере|&НаКлиенте|&НаСервереБезКонтекста)?\s*(?:Экспорт\s+)?Функция\s+([а-яёА-ЯЁ\w]+)\s*\(',
        re.IGNORECASE | re.MULTILINE
    )
    
    PROC_END_PATTERN = re.compile(r'^\s*КонецПроцедуры', re.IGNORECASE | re.MULTILINE)
    FUNC_END_PATTERN = re.compile(r'^\s*КонецФункции', re.IGNORECASE | re.MULTILINE)
    
    CONTEXT_PATTERN = re.compile(r'&(НаСервере|НаКлиенте|НаСервереБезКонтекста)', re.IGNORECASE)
    EXPORT_PATTERN = re.compile(r'\bЭкспорт\b', re.IGNORECASE)
    
    # Параметры: (Знач)? ИмяПараметра (= значение)?
    PARAM_PATTERN = re.compile(
        r'(?:Знач\s+)?([а-яёА-ЯЁ\w]+)(?:\s*=\s*([^,)]+))?',
        re.IGNORECASE
    )
    
    # Переменные модуля: Перем Имя [Экспорт];
    MODULE_VAR_PATTERN = re.compile(
        r'^\s*Перем\s+([а-яёА-ЯЁ\w]+)(?:\s+Экспорт)?\s*;',
        re.IGNORECASE | re.MULTILINE
    )
    
    # Вызовы процедур/функций: ИмяПроцедуры( или ИмяПроцедуры()
    CALL_PATTERN = re.compile(
        r'\b([а-яёА-ЯЁ\w]+)\s*\(',
        re.IGNORECASE
    )
    
    # Ключевые слова, которые не являются вызовами
    KEYWORDS = {
        'если', 'иначе', 'иначеесли', 'конецесли', 'пока', 'конеццикла',
        'для', 'каждого', 'из', 'цикл', 'процедура', 'функция',
        'конецпроцедуры', 'конецфункции', 'возврат', 'прервать',
        'продолжить', 'попытка', 'исключение', 'вызватьисключение',
        'новый', 'тип', 'типзнч', 'неопределено', 'истина', 'ложь',
        'сообщить', 'сообщениепользователю', 'пустаястрока', 'стршаблон',
        'насервере', 'наклиенте', 'насерверебезконтекста', 'экспорт',
        'знач', 'перем', 'конецобласти', 'область'
    }
    
    def parse(self, source: str) -> BSLParseResult:
        """
        Парсит BSL код и возвращает структурированный результат.
        
        :param source: Исходный код BSL
        :return: BSLParseResult с извлеченными данными
        """
        result = BSLParseResult()
        lines = source.split('\n')
        
        # Извлекаем переменные модуля
        result.module_vars = self._parse_module_vars(source, lines)
        
        # Извлекаем методы (процедуры и функции)
        result.methods = self._parse_methods(source, lines)
        
        # Извлекаем вызовы на уровне модуля (вне методов)
        result.global_calls = self._parse_global_calls(source, lines, result.methods)
        
        # Извлекаем вызовы внутри методов
        for method in result.methods:
            method.calls_position = self._parse_method_calls(source, lines, method)
        
        return result
    
    def _parse_module_vars(self, source: str, lines: list[str]) -> dict[str, BSLModuleVar]:
        """Извлекает переменные модуля."""
        vars_dict: dict[str, BSLModuleVar] = {}
        
        for match in self.MODULE_VAR_PATTERN.finditer(source):
            var_name = match.group(1)
            var_line = source[:match.start()].count('\n')
            var_text = match.group(0)
            is_export = 'Экспорт' in var_text or 'экспорт' in var_text
            
            # Ищем описание перед переменной
            description = self._extract_description_before(lines, var_line)
            
            vars_dict[var_name] = BSLModuleVar(
                name=var_name,
                is_export=is_export,
                description=description
            )
        
        return vars_dict
    
    def _parse_methods(self, source: str, lines: list[str]) -> list[BSLMethod]:
        """Извлекает процедуры и функции."""
        methods: list[BSLMethod] = []
        
        # Находим все процедуры
        for match in self.PROC_PATTERN.finditer(source):
            method = self._parse_method_from_match(source, lines, match, is_proc=True)
            if method:
                methods.append(method)
        
        # Находим все функции
        for match in self.FUNC_PATTERN.finditer(source):
            method = self._parse_method_from_match(source, lines, match, is_proc=False)
            if method:
                methods.append(method)
        
        # Сортируем по номеру строки
        methods.sort(key=lambda m: m.line)
        
        return methods
    
    def _parse_method_from_match(
        self,
        source: str,
        lines: list[str],
        match: re.Match[str],
        is_proc: bool
    ) -> BSLMethod | None:
        """Создает BSLMethod из найденного совпадения."""
        method_name = match.group(1)
        start_pos = match.start()
        # Вычисляем номер строки: количество \n до позиции совпадения
        start_line = source[:start_pos].count('\n')
        
        # Убеждаемся, что start_line указывает на строку, содержащую совпадение
        # Если совпадение находится сразу после \n, то start_line уже правильный
        # Но если строка start_line не содержит совпадение, ищем его в следующих строках
        # Используем имя процедуры/функции для проверки, так как оно точно есть в строке
        found_in_line = False
        for offset in range(3):  # Проверяем текущую и следующие 2 строки
            check_line = start_line + offset
            if check_line < len(lines) and method_name in lines[check_line]:
                # Дополнительная проверка: убеждаемся, что это действительно объявление процедуры/функции
                line_text = lines[check_line]
                if ('Процедура' in line_text or 'Функция' in line_text) and method_name in line_text:
                    start_line = check_line
                    found_in_line = True
                    break
        
        # Извлекаем контекст и экспорт из строки объявления
        declaration_line = lines[start_line] if start_line < len(lines) else ""
        context = self._extract_context(declaration_line)
        is_export = bool(self.EXPORT_PATTERN.search(declaration_line))
        
        # Извлекаем параметры
        params = self._extract_params(source, start_pos, lines, start_line)
        
        # Находим конец процедуры/функции
        end_line = self._find_method_end(source, start_line, is_proc)
        if end_line is None:
            return None
        
        # Извлекаем описание (комментарии перед методом)
        description = self._extract_description_before(lines, start_line)
        
        return BSLMethod(
            name=method_name,
            line=start_line,
            endline=end_line,
            isproc=is_proc,
            is_export=is_export,
            params=params,
            description=description,
            context=context
        )
    
    def _extract_context(self, line: str) -> str:
        """Извлекает контекст из строки (НаСервере, НаКлиенте и т.д.)."""
        match = self.CONTEXT_PATTERN.search(line)
        if match:
            context = match.group(1)
            # Нормализуем регистр
            if context.lower() == 'насервере':
                return 'НаСервере'
            elif context.lower() == 'наклиенте':
                return 'НаКлиенте'
            elif context.lower() == 'насерверебезконтекста':
                return 'НаСервереБезКонтекста'
        return ""
    
    def _extract_params(
        self,
        source: str,
        start_pos: int,
        lines: list[str],
        start_line: int
    ) -> list[BSLParam]:
        """Извлекает параметры процедуры/функции."""
        params: list[BSLParam] = []
        
        # Находим строку с объявлением
        declaration_line = lines[start_line] if start_line < len(lines) else ""
        
        # Находим открывающую скобку
        paren_start = declaration_line.find('(')
        if paren_start == -1:
            return params
        
        # Находим закрывающую скобку (может быть на следующей строке)
        paren_end = declaration_line.find(')', paren_start + 1)
        if paren_end == -1:
            # Ищем закрывающую скобку в следующих строках
            search_start = start_pos + paren_start + 1
            paren_end_pos = source.find(')', search_start)
            if paren_end_pos == -1:
                return params
            params_text = source[search_start:paren_end_pos]
        else:
            params_text = declaration_line[paren_start + 1:paren_end]
        
        # Парсим параметры
        if params_text.strip():
            for param_match in self.PARAM_PATTERN.finditer(params_text):
                param_name = param_match.group(1)
                byval = 'Знач' in param_match.group(0) or 'знач' in param_match.group(0)
                default = param_match.group(2) if param_match.lastindex >= 2 and param_match.group(2) else None
                
                params.append(BSLParam(
                    name=param_name,
                    byval=byval,
                    default=default.strip() if default else None
                ))
        
        return params
    
    def _find_method_end(self, source: str, start_line: int, is_proc: bool) -> int | None:
        """Находит строку с концом процедуры/функции."""
        lines = source.split('\n')
        end_pattern = self.PROC_END_PATTERN if is_proc else self.FUNC_END_PATTERN
        
        # Ищем соответствующий конец, учитывая вложенность
        depth = 1
        for i in range(start_line + 1, len(lines)):
            line = lines[i]
            
            # Проверяем начало новых процедур/функций
            # Используем search, но проверяем, что совпадение в начале строки (после пробелов)
            proc_match = self.PROC_PATTERN.search(line)
            func_match = self.FUNC_PATTERN.search(line)
            if proc_match or func_match:
                # Проверяем, что совпадение действительно в начале строки (после пробелов)
                match_pos = proc_match.start() if proc_match else func_match.start()
                if match_pos == len(line) - len(line.lstrip()):
                    depth += 1
            # Проверяем конец процедур/функций
            elif end_pattern.search(line):
                depth -= 1
                if depth == 0:
                    return i
        
        return None
    
    def _extract_description_before(self, lines: list[str], line_num: int) -> str:
        """Извлекает описание (комментарии) перед методом/переменной."""
        description_lines: list[str] = []
        
        # Ищем комментарии перед объявлением (максимум 20 строк назад)
        for i in range(max(0, line_num - 20), line_num):
            line = lines[i].strip()
            
            # Пропускаем пустые строки в начале
            if not description_lines and not line:
                continue
            
            # Если нашли комментарий
            if line.startswith('//'):
                description_lines.append(line[2:].strip())
            # Если нашли начало блока комментариев
            elif '/*' in line:
                # Извлекаем многострочные комментарии (упрощенно)
                if '*/' in line:
                    comment = line[line.find('/*') + 2:line.find('*/')].strip()
                    if comment:
                        description_lines.append(comment)
            # Если строка не пустая и не комментарий, прекращаем сбор
            elif line:
                break
        
        # Обращаем порядок и объединяем
        description_lines.reverse()
        return '\n'.join(description_lines).strip()
    
    def _parse_global_calls(
        self,
        source: str,
        lines: list[str],
        methods: list[BSLMethod]
    ) -> list[BSLCallPosition]:
        """Извлекает вызовы процедур/функций на уровне модуля (вне методов)."""
        calls: list[BSLCallPosition] = []
        
        # Определяем диапазоны строк, занятые методами
        method_ranges: set[int] = set()
        for method in methods:
            for line_num in range(method.line, method.endline + 1):
                method_ranges.add(line_num)
        
        # Ищем вызовы вне методов
        for line_num, line in enumerate(lines):
            if line_num in method_ranges:
                continue
            
            for match in self.CALL_PATTERN.finditer(line):
                call_name = match.group(1)
                
                # Пропускаем ключевые слова
                if call_name.lower() in self.KEYWORDS:
                    continue
                
                calls.append(BSLCallPosition(
                    call=call_name,
                    line=line_num,
                    character=match.start()
                ))
        
        return calls
    
    def _parse_method_calls(
        self,
        source: str,
        lines: list[str],
        method: BSLMethod
    ) -> list[BSLCallPosition]:
        """Извлекает вызовы процедур/функций внутри метода."""
        calls: list[BSLCallPosition] = []
        
        # Извлекаем код метода
        method_lines = lines[method.line:method.endline + 1]
        method_text = '\n'.join(method_lines)
        
        # Ищем вызовы в коде метода
        for line_offset, line in enumerate(method_lines):
            line_num = method.line + line_offset
            
            for match in self.CALL_PATTERN.finditer(line):
                call_name = match.group(1)
                
                # Пропускаем ключевые слова
                if call_name.lower() in self.KEYWORDS:
                    continue
                
                # Пропускаем вызов самого метода (рекурсия)
                if call_name == method.name:
                    continue
                
                calls.append(BSLCallPosition(
                    call=call_name,
                    line=line_num,
                    character=match.start()
                ))
        
        return calls

