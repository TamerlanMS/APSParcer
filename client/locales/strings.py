"""Все строки интерфейса на двух языках."""

STRINGS = {
    "ru": {
        # App
        "app_title": "APS Parser — Обработка спецификаций",
        "app_subtitle": "GQ Group",
        "lang_switch": "ҚАЗ",

        # Nav
        "nav_upload": "📄  Загрузка PDF",
        "nav_preview": "📊  Предпросмотр",
        "nav_database": "🗄️   База данных",
        "nav_key_info": "Ключ: ",
        "nav_change_key": "🔑  Сменить ключ",

        # Auth dialog
        "auth_title": "Авторизация",
        "auth_subtitle": "Введите данные для подключения к серверу",
        "auth_server": "Адрес сервера:",
        "auth_server_ph": "http://your-server.com:8000",
        "auth_key": "API ключ доступа:",
        "auth_key_ph": "APS-K1-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
        "auth_show_key": "👁  Показать ключ",
        "auth_hide_key": "🙈  Скрыть ключ",
        "auth_connect": "🔗  Подключиться",
        "auth_checking": "🔄 Проверка подключения...",
        "auth_success": "✅ Подключение успешно!",
        "auth_no_server": "⚠️ Введите адрес сервера",
        "auth_no_key": "⚠️ Введите API ключ",
        "auth_invalid": "❌ Недействительный ключ",
        "auth_no_conn": "❌ Нет соединения с сервером",

        # Upload page
        "upload_title": "Загрузка PDF спецификации",
        "upload_desc": "Загрузите PDF рабочего проекта АПС. Система извлечёт спецификацию и найдёт позиции в базе данных.",
        "upload_drop_title": "Перетащите PDF файл сюда",
        "upload_drop_sub": "или нажмите кнопку «Выбрать файл»\nПоддерживается формат PDF",
        "upload_browse": "📂  Выбрать файл",
        "upload_send": "🚀  Обработать на сервере",
        "upload_no_file": "Файл не выбран",
        "upload_sending": "Отправка файла на сервер...",
        "upload_done": "Готово! Позиций: ",
        "upload_error_title": "Ошибка обработки",
        "upload_error_msg": "Не удалось обработать PDF:\n\n",
        "upload_wrong_type": "Файл должен быть в формате PDF",

        # Preview page
        "preview_title": "📊  Предпросмотр результатов",
        "preview_save": "💾  Сохранить Excel",
        "preview_no_data": "Загрузите PDF для отображения результатов",
        "preview_stat": "Всего: {total}  |  ✅ {exact}  |  ⚠️ {warn}  |  ❌ {nf}",
        "preview_legend_exact": "✅ Найдено точно",
        "preview_legend_warn": "⚠️ Уточнить",
        "preview_legend_nf": "❌ Не найдено",
        "preview_legend_edit": "✏️ Изменено",
        "preview_constants": "Константы расчёта",
        "preview_margin": "Маржа",
        "preview_logistics": "Логистика",
        "preview_nds": "НДС",
        "preview_currency": "Курс руб.",
        "preview_rate": "Расценка %",
        "preview_saved": "Файл сохранён:\n{path}\n\nПозиций: {count}",
        "preview_open_file": "Открыть файл в Excel?",
        "preview_save_error": "Ошибка сохранения",
        "ctx_copy_article":  "Копировать артикул",
        "ctx_copy_kaznisa":  "Копировать код КазНИИСА",
        "ctx_copy_row":      "Копировать артикул + код (через Tab)",
        "preview_filter_all": "Все",
        "preview_filter_warn": "Требуют уточнения",
        "preview_filter_nf": "Не найдены",
        "preview_search_ph": "Поиск по артикулу...",
        "preview_reset": "↺  Сброс",
        "preview_reset_confirm": "Сбросить таблицу и константы для новой сессии?",

        # Candidate dialog
        "cand_title": "Выбор варианта",
        "cand_label": "Найдено несколько вариантов. Выберите подходящий:",
        "cand_ok": "Выбрать",
        "cand_cancel": "Отмена",
        "cand_no_selection": "Выберите вариант из списка перед нажатием «Выбрать».",

        # Table headers
        "col_num": "№",
        "col_art_pdf": "Артикул (PDF)",
        "col_name_pdf": "Наименование",
        "col_unit": "Ед.",
        "col_qty": "Кол-во",
        "col_art_db": "Артикул (БД)",
        "col_name_db": "Наим. (БД)",
        "col_brand": "Бренд",
        "col_rrts": "РРЦ",
        "col_mrc": "МРЦ",
        "col_opt": "Опт",
        "col_price_kp": "Цена КП",
        "col_sum_kp": "Сумма КП",
        "col_status": "Статус",
        "col_comment": "Комментарий",

        # Status labels
        "status_exact": "✅ Найдено",
        "status_multiple": "⚠️ Несколько",
        "status_fuzzy": "⚠️ Нечёткое",
        "status_nf": "❌ Не найдено",

        "col_mult":          "Кратность",
        "col_const":         "Константа цена",
        "col_price_seb":     "Цена себес",
        "col_sum_seb":       "Сумма себес",
        "col_kaznisa_code":  "Код КазНИИСА",
        "col_delivery":      "Срок поставки",
        "preview_constants_brand": "Константы по бренду",
        "preview_brand_select":    "Бренд:",
        "preview_rate_type":       "Расценка (1-5)",
        "preview_rate_hint":       "Расценка: 1=РРЦ, 2=МРЦ, 3=Опт, 4=Партнёр/Проект, 5=КазНИИСА",
        "save_kp_title":     "Сохранение КП",
        "save_kp_subtitle":  "Заполните данные для коммерческого предложения",
        "save_kp_manager":   "Менеджер:",
        "save_kp_project":   "Проект:",
        "save_kp_client":    "Клиент:",
        "save_kp_ok":        "💾 Сохранить",
        "save_kp_cancel":    "Отмена",

        # Database page
        "db_title": "🗄️  База данных",
        "db_count": "Товаров в базе: {count}",
        "db_refresh": "🔄  Обновить",
        "db_tab_import": "📦  Загрузка БД",
        "db_tab_const": "⚙️  Константы",
        "db_tab_logs": "📋  История",
        "db_import_desc": "Загрузите обновлённый Excel (лист «БД»). Новые позиции добавятся, существующие обновятся.",
        "db_drop_label": "База данных товаров (лист «БД»)",
        "db_import_btn": "📥  Импортировать базу данных",
        "db_const_desc": "Загрузите Excel с константами (лист «Const»). Обновятся коэффициенты и курсы.",
        "db_const_label": "Файл констант (лист «Const»)",
        "db_const_btn": "📥  Импортировать константы",
        "db_password": "Пароль администратора:",
        "db_password_ph": "Введите пароль...",
        "db_import_ok": "Импорт завершён!\n\nДобавлено: {added}\nОбновлено: {updated}",
        "db_import_error": "Ошибка импорта:\n\n{error}",
        "db_no_file": "Сначала выберите файл",
        "db_running": "Выполняется импорт...",
        "db_log_file": "Файл",
        "db_log_added": "Добавлено",
        "db_log_updated": "Обновлено",
        "db_log_status": "Статус",
        "db_log_date": "Дата",
        "db_load_logs": "🔄  Загрузить историю",

        # Status bar
        "status_connected": "Подключено: {url}",
        "status_not_conn": "Не подключено",
    },

    "kz": {
        # App
        "app_title": "APS Parser — Сипаттамаларды өңдеу",
        "app_subtitle": "GQ Group",
        "lang_switch": "РУС",

        # Nav
        "nav_upload": "📄  PDF жүктеу",
        "nav_preview": "📊  Алдын ала қарау",
        "nav_database": "🗄️   Деректер қоры",
        "nav_key_info": "Кілт: ",
        "nav_change_key": "🔑  Кілтті өзгерту",

        # Auth dialog
        "auth_title": "Авторизация",
        "auth_subtitle": "Серверге қосылу деректерін енгізіңіз",
        "auth_server": "Сервер мекенжайы:",
        "auth_server_ph": "http://your-server.com:8000",
        "auth_key": "API кіру кілті:",
        "auth_key_ph": "APS-K1-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
        "auth_show_key": "👁  Кілтті көрсету",
        "auth_hide_key": "🙈  Жасыру",
        "auth_connect": "🔗  Қосылу",
        "auth_checking": "🔄 Қосылым тексерілуде...",
        "auth_success": "✅ Сәтті қосылды!",
        "auth_no_server": "⚠️ Сервер мекенжайын енгізіңіз",
        "auth_no_key": "⚠️ API кілтін енгізіңіз",
        "auth_invalid": "❌ Жарамсыз кілт",
        "auth_no_conn": "❌ Серверге қосылу мүмкін емес",

        # Upload page
        "upload_title": "PDF сипаттамасын жүктеу",
        "upload_desc": "АПС жұмыс жобасының PDF файлын жүктеңіз. Жүйе сипаттаманы шығарып, деректер қорынан табады.",
        "upload_drop_title": "PDF файлын осында апарыңыз",
        "upload_drop_sub": "немесе «Файлды таңдау» батырмасын басыңыз\nPDF форматы қолданылады",
        "upload_browse": "📂  Файлды таңдау",
        "upload_send": "🚀  Серверде өңдеу",
        "upload_no_file": "Файл таңдалмаған",
        "upload_sending": "Файл серверге жіберілуде...",
        "upload_done": "Дайын! Позициялар: ",
        "upload_error_title": "Өңдеу қатесі",
        "upload_error_msg": "PDF өңдеу мүмкін болмады:\n\n",
        "upload_wrong_type": "Файл PDF форматында болуы керек",

        # Preview page
        "preview_title": "📊  Нәтижелерді алдын ала қарау",
        "preview_save": "💾  Excel сақтау",
        "preview_no_data": "Нәтижелерді көрсету үшін PDF жүктеңіз",
        "preview_stat": "Барлығы: {total}  |  ✅ {exact}  |  ⚠️ {warn}  |  ❌ {nf}",
        "preview_legend_exact": "✅ Дәл табылды",
        "preview_legend_warn": "⚠️ Нақтылау керек",
        "preview_legend_nf": "❌ Табылмады",
        "preview_legend_edit": "✏️ Өзгертілді",
        "preview_constants": "Есептеу константалары",
        "preview_margin": "Маржа",
        "preview_logistics": "Логистика",
        "preview_nds": "ҚҚС",
        "preview_currency": "Рубль бағамы",
        "preview_rate": "Баға %",
        "preview_saved": "Файл сақталды:\n{path}\n\nПозициялар: {count}",
        "preview_open_file": "Файлды Excel-де ашу керек пе?",
        "ctx_copy_article":  "Артикулды көшіру",
        "ctx_copy_kaznisa":  "ҚазНИИСА кодын көшіру",
        "ctx_copy_row":      "Артикул + код көшіру (Tab арқылы)",
        "preview_save_error": "Сақтау қатесі",
        "preview_filter_all": "Барлығы",
        "preview_filter_warn": "Нақтылау керек",
        "preview_filter_nf": "Табылмағандар",
        "preview_search_ph": "Артикул бойынша іздеу...",
        "preview_reset": "↺  Қалпына келтіру",
        "preview_reset_confirm": "Жаңа сессия үшін кестені және константаларды қалпына келтіру керек пе?",

        # Candidate dialog
        "cand_title": "Нұсқаны таңдау",
        "cand_label": "Бірнеше нұсқа табылды. Қолайлысын таңдаңыз:",
        "cand_ok": "Таңдау",
        "cand_cancel": "Болдырмау",
        "cand_no_selection": "«Таңдау» түймесін басудан бұрын тізімнен нұсқа таңдаңыз.",

        # Table headers
        "col_num": "№",
        "col_art_pdf": "Артикул (PDF)",
        "col_name_pdf": "Атауы",
        "col_unit": "Өл.б.",
        "col_qty": "Саны",
        "col_art_db": "Артикул (ДҚ)",
        "col_name_db": "Атауы (ДҚ)",
        "col_brand": "Бренд",
        "col_rrts": "РРБ",
        "col_mrc": "МРБ",
        "col_opt": "Опт",
        "col_price_kp": "КҰ баға",
        "col_sum_kp": "КҰ сомасы",
        "col_status": "Мәртебе",
        "col_comment": "Пікір",

        # Status labels
        "status_exact": "✅ Табылды",
        "status_multiple": "⚠️ Бірнеше",
        "status_fuzzy": "⚠️ Жуықтама",
        "status_nf": "❌ Табылмады",

        "col_mult":          "Еселік",
        "col_const":         "Бекітілген баға",
        "col_price_seb":     "Өзіндік құн",
        "col_sum_seb":       "Өзіндік құн сомасы",
        "col_kaznisa_code":  "ҚазНИИСА коды",
        "col_delivery":      "Жеткізу мерзімі",
        "preview_constants_brand": "Бренд бойынша константалар",
        "preview_brand_select":    "Бренд:",
        "preview_rate_type":       "Баға түрі (1-5)",
        "preview_rate_hint":       "Баға түрі: 1=РРБ, 2=МРБ, 3=Опт, 4=Серіктес/Жоба, 5=ҚазНИИСА",
        "save_kp_title":     "КҰ сақтау",
        "save_kp_subtitle":  "Коммерциялық ұсынысқа арналған деректерді толтырыңыз",
        "save_kp_manager":   "Менеджер:",
        "save_kp_project":   "Жоба:",
        "save_kp_client":    "Клиент:",
        "save_kp_ok":        "💾 Сақтау",
        "save_kp_cancel":    "Болдырмау",

        # Database page
        "db_title": "🗄️  Деректер қоры",
        "db_count": "Дерек қорындағы тауарлар: {count}",
        "db_refresh": "🔄  Жаңарту",
        "db_tab_import": "📦  ДҚ жүктеу",
        "db_tab_const": "⚙️  Константалар",
        "db_tab_logs": "📋  Тарих",
        "db_import_desc": "Жаңартылған Excel жүктеңіз («БД» парағы). Жаңа позициялар қосылады, бар позициялар жаңартылады.",
        "db_drop_label": "Тауарлар дерек қоры («БД» парағы)",
        "db_import_btn": "📥  Деректер қорын импорттау",
        "db_const_desc": "Константалары бар Excel жүктеңіз («Const» парағы). Коэффициенттер жаңартылады.",
        "db_const_label": "Константалар файлы («Const» парағы)",
        "db_const_btn": "📥  Константаларды импорттау",
        "db_password": "Әкімші құпия сөзі:",
        "db_password_ph": "Құпия сөзді енгізіңіз...",
        "db_import_ok": "Импорт аяқталды!\n\nҚосылды: {added}\nЖаңартылды: {updated}",
        "db_import_error": "Импорт қатесі:\n\n{error}",
        "db_no_file": "Алдымен файлды таңдаңыз",
        "db_running": "Импорт орындалуда...",
        "db_log_file": "Файл",
        "db_log_added": "Қосылды",
        "db_log_updated": "Жаңартылды",
        "db_log_status": "Мәртебе",
        "db_log_date": "Күні",
        "db_load_logs": "🔄  Тарихты жүктеу",

        # Status bar
        "status_connected": "Қосылды: {url}",
        "status_not_conn": "Қосылмаған",
    }
}


class Lang:
    _lang = "ru"

    @classmethod
    def set(cls, lang: str):
        cls._lang = lang if lang in ("ru", "kz") else "ru"

    @classmethod
    def get(cls) -> str:
        return cls._lang


def t(key: str, **kwargs) -> str:
    """Возвращает строку на текущем языке; fallback → русский."""
    lang = Lang.get()
    text = STRINGS.get(lang, {}).get(key) or STRINGS.get("ru", {}).get(key) or key
    return text.format(**kwargs) if kwargs else text
