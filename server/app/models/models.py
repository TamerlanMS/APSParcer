from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Text, Boolean, LargeBinary,
    ForeignKey, Enum as SAEnum
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum


# ─── Сегменты ────────────────────────────────────────────────────────────────

class SegmentType(str, enum.Enum):
    ss  = "ss"   # Слаботочные системы
    os  = "os"   # Осветительные системы
    sil = "sil"  # Силовые системы
    gen = "gen"  # Общая база: позиции прейскуранта АГСК без своего сегмента

SEGMENT_DISPLAY = {
    "ss":  "Слаботочные системы",
    "os":  "Осветительные системы",
    "sil": "Силовые системы",
    "gen": "Общая база (АГСК)",
}

# Рабочие сегменты: раскрытие «all» при подборе. Общая база сюда НЕ входит —
# она подключается явным выбором, иначе индекс матчера растёт на четверть.
ALL_SEGMENTS = ["ss", "os", "sil"]

# Все сегменты, допустимые для хранения и фильтрации
KNOWN_SEGMENTS = ["ss", "os", "sil", "gen"]


# ─── Роли ────────────────────────────────────────────────────────────────────

class RoleName(str, enum.Enum):
    superadmin    = "superadmin"     # Полные права + управление пользователями
    administrator = "administrator"  # Обновление БД и констант
    manager       = "manager"        # Обработка PDF → КП
    director      = "director"       # Аналитика + обработка PDF → КП


class Role(Base):
    """Роли пользователей системы"""
    __tablename__ = "roles"

    id           = Column(Integer, primary_key=True, index=True)
    name         = Column(SAEnum(RoleName), unique=True, nullable=False, index=True)
    display_name = Column(String(100), nullable=False)   # Читаемое название
    description  = Column(Text, nullable=True)

    users = relationship("User", back_populates="role")


# ─── Пользователи ────────────────────────────────────────────────────────────

class User(Base):
    """Пользователи системы"""
    __tablename__ = "users"

    id            = Column(Integer, primary_key=True, index=True)
    username      = Column(String(100), unique=True, nullable=False, index=True)
    full_name     = Column(String(200), nullable=False)
    email         = Column(String(200), nullable=True, unique=True)
    phone         = Column(String(100), nullable=True)
    password_hash = Column(String(300), nullable=False)
    role_id       = Column(Integer, ForeignKey("roles.id"), nullable=False)
    segment       = Column(String(10), nullable=True, default="ss")  # ss/os/sil; NULL = все
    is_active     = Column(Boolean, default=True, nullable=False)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), onupdate=func.now())
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    role     = relationship("Role", back_populates="users")
    sessions = relationship("UserSession", back_populates="user",
                            cascade="all, delete-orphan")


# ─── Сессии (JWT) ────────────────────────────────────────────────────────────

class UserSession(Base):
    """Активные JWT-сессии пользователей"""
    __tablename__ = "user_sessions"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    token_jti  = Column(String(64), unique=True, nullable=False, index=True)  # JWT ID
    expires_at = Column(DateTime(timezone=True), nullable=False)
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(String(300), nullable=True)
    is_active  = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="sessions")


# ─── Лог действий ────────────────────────────────────────────────────────────

class AuditLog(Base):
    """Журнал действий пользователей"""
    __tablename__ = "audit_logs"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"),
                        nullable=True, index=True)
    username   = Column(String(100), nullable=True)   # Денормализовано — для истории
    role       = Column(String(50), nullable=True)    # Роль на момент действия
    action     = Column(String(200), nullable=False)  # import_products, parse_pdf…
    resource   = Column(String(300), nullable=True)   # Имя файла / ID объекта
    details    = Column(Text, nullable=True)          # JSON с деталями
    ip_address = Column(String(50), nullable=True)
    status     = Column(String(20), default="success")  # success | error
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", foreign_keys=[user_id])


# ─── Существующие модели ──────────────────────────────────────────────────────

class Product(Base):
    """Таблица товаров — основная БД"""
    __tablename__ = "products"

    id           = Column(Integer, primary_key=True, index=True)
    num          = Column(Integer, nullable=True)
    article      = Column(String(200), index=True)
    name         = Column(Text, nullable=True)
    unit         = Column(String(50), nullable=True)
    kaznisa      = Column(Float, nullable=True)
    rrts         = Column(Float, nullable=True)
    mrc          = Column(Float, nullable=True)
    opt          = Column(Float, nullable=True)
    partner      = Column(Float, nullable=True)
    brand        = Column(String(100), nullable=True, index=True)
    multiplicity = Column(Integer, nullable=True)
    kaznisa_code = Column(String(100), nullable=True)
    segment      = Column(String(10), nullable=False, default="ss", index=True)  # ss/os/sil
    is_active    = Column(Boolean, default=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), onupdate=func.now())


class BrandConstant(Base):
    """Константы коэффициентов для брендов"""
    __tablename__ = "brand_constants"

    id            = Column(Integer, primary_key=True, index=True)
    brand         = Column(String(100), unique=True, index=True)
    margin        = Column(Float, default=1.2)
    logistics     = Column(Float, default=1.03)
    rate          = Column(Float, default=1.0)   # 1 = «Сумма АГСК»
    currency_rate = Column(Float, default=1.0)
    nds           = Column(Float, default=1.16)
    gp            = Column(Float, default=0.8)
    updated_at    = Column(DateTime(timezone=True), server_default=func.now(),
                           onupdate=func.now())


class CurrencyRate(Base):
    """Курсы валют"""
    __tablename__ = "currency_rates"

    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String(50), unique=True)
    rate       = Column(Float, default=1.0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now())


class Manager(Base):
    """Менеджеры из листа Const"""
    __tablename__ = "managers"

    id         = Column(Integer, primary_key=True, index=True)
    full_name  = Column(String(200), unique=True, index=True)
    position   = Column(String(200), nullable=True)
    email      = Column(String(200), nullable=True)
    phone      = Column(String(100), nullable=True)
    is_active  = Column(Boolean, default=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now())


class ImportLog(Base):
    """Лог импортов БД"""
    __tablename__ = "import_logs"

    id           = Column(Integer, primary_key=True, index=True)
    filename     = Column(String(300))
    segment      = Column(String(10), nullable=True, default="ss")   # импортированный сегмент
    rows_added   = Column(Integer, default=0)
    rows_updated = Column(Integer, default=0)
    status       = Column(String(50), default="success")
    message      = Column(Text, nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    # ── Расширенная история ────────────────────────────────────────────────────
    action       = Column(String(50), nullable=True, default="import")  # import / clear / vectorize
    count_before = Column(Integer, nullable=True)   # кол-во активных позиций ДО операции
    count_after  = Column(Integer, nullable=True)   # кол-во активных позиций ПОСЛЕ
    changed_by   = Column(String(150), nullable=True)  # username пользователя


class PdfUploadLog(Base):
    """История загрузок PDF-спецификаций"""
    __tablename__ = "pdf_upload_logs"

    id           = Column(Integer, primary_key=True, index=True)
    user_id      = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"),
                          nullable=True, index=True)
    username     = Column(String(100), nullable=True)   # денормализовано
    full_name    = Column(String(200), nullable=True)   # ФИО пользователя
    filename     = Column(String(300), nullable=False)
    project_name = Column(Text, nullable=True)          # из штампа PDF
    items_count  = Column(Integer, default=0)           # кол-во позиций
    uploaded_at  = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    user = relationship("User", foreign_keys=[user_id])



class ExcelTemplate(Base):
    """
    Шаблон WV .xlsm, хранимый в БД.
    Активна одна запись (is_active=True).  
    При загрузке новой версии старая помечается is_active=False.
    """
    __tablename__ = "excel_templates"

    id          = Column(Integer, primary_key=True, index=True)
    version     = Column(Integer, default=1, nullable=False)
    filename    = Column(String(300), nullable=False)            # оригинальное имя файла
    data        = Column(LargeBinary, nullable=False)            # байты .xlsm
    file_size   = Column(Integer, nullable=False)                # bytes
    file_hash   = Column(String(64), nullable=False)             # SHA-256
    description = Column(String(500), nullable=True)             # комментарий менеджера
    uploaded_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"),
                         nullable=True, index=True)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    is_active   = Column(Boolean, default=True, nullable=False, index=True)

    uploader = relationship("User", foreign_keys=[uploaded_by])


class PriceHistory(Base):
    """
    История цен по артикулам.
    При каждом импорте сохраняется снимок старых цен для артикулов,
    у которых изменилась хотя бы одна ценовая колонка.
    Текущие цены всегда в таблице products (is_active=True).
    """
    __tablename__ = "price_history"

    id          = Column(Integer, primary_key=True, index=True)
    article     = Column(String(200), index=True, nullable=False)
    segment     = Column(String(10), nullable=False, index=True)
    brand       = Column(String(100), nullable=True)
    name        = Column(Text, nullable=True)
    kaznisa     = Column(Float, nullable=True)
    rrts        = Column(Float, nullable=True)
    mrc         = Column(Float, nullable=True)
    opt         = Column(Float, nullable=True)
    recorded_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class ManagerCorrection(Base):
    """
    История исправлений менеджеров.
    Каждый раз когда менеджер вручную выбирает/заменяет товар в предпросмотре —
    запись сохраняется сюда и индексируется в Pinecone (namespace "corrections").
    Используется для приоритетного подбора перед стандартным AI-матчингом.
    """
    __tablename__ = "manager_corrections"

    id                  = Column(Integer, primary_key=True, index=True)
    user_id             = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"),
                                  nullable=True, index=True)
    username            = Column(String(100), nullable=True)   # денормализовано
    session_id          = Column(String(64), nullable=True, index=True)  # группировка сессии

    # Оригинальный запрос из PDF
    original_name       = Column(Text, nullable=False)
    original_article    = Column(String(300), nullable=True)
    original_status     = Column(String(50), nullable=True)    # not_found / fuzzy / ai_match / ...

    # Выбранный менеджером товар
    selected_product_id = Column(Integer, ForeignKey("products.id", ondelete="SET NULL"),
                                  nullable=True, index=True)
    selected_article    = Column(String(200), nullable=True)   # денормализовано для быстрого поиска
    selected_name       = Column(Text, nullable=True)          # денормализовано

    # Метаданные
    pinecone_indexed    = Column(Boolean, default=False)       # True = вектор в Pinecone
    created_at          = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    user     = relationship("User", foreign_keys=[user_id])
    product  = relationship("Product", foreign_keys=[selected_product_id])


class ProductAnalog(Base):
    """
    Кэш аналогов, найденных по артикулу через внешние провайдеры (DKC, EKF, IEK, CHINT, BonPet).
    Обновляется если запись старше 30 дней или force_refresh=True.
    """
    __tablename__ = "product_analogs"

    id              = Column(Integer, primary_key=True, index=True)
    article         = Column(String(200), nullable=False, index=True)   # оригинальный артикул
    source          = Column(String(50),  nullable=False)               # dkc / ekf / iek / chint / bonpet
    analog_article  = Column(String(200), nullable=False)               # найденный аналог
    analog_name     = Column(Text,        nullable=True)                # название аналога (если есть)
    fetched_at      = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    expires_at      = Column(DateTime(timezone=True), nullable=True)    # NULL = бессрочно


class AnalogDatabase(Base):
    """
    Постоянная база аналогов артикулов.
    В отличие от product_analogs — не кэш, данные хранятся бессрочно.
    Создаётся вручную или переносится из результатов поиска по провайдерам.
    """
    __tablename__ = "analog_database"

    id             = Column(Integer, primary_key=True, index=True)
    article        = Column(String(200), nullable=False, index=True)   # оригинальный артикул
    segment        = Column(String(10),  nullable=True,  index=True)   # ss / os / sil (опционально)
    analog_article = Column(String(200), nullable=False)               # артикул аналога
    analog_name    = Column(Text,        nullable=True)                # наименование аналога
    analog_brand   = Column(String(100), nullable=True)                # бренд аналога
    source         = Column(String(50),  nullable=True)                # manual / provider / correction
    notes          = Column(Text,        nullable=True)                # заметки
    added_by       = Column(String(100), nullable=True)                # username добавившего
    created_at     = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at     = Column(DateTime(timezone=True), onupdate=func.now())
    is_active      = Column(Boolean, default=True, nullable=False)


class AppSetting(Base):
    """
    Глобальные настройки приложения (key-value).
    Редактируются администратором, читаются всеми клиентами.

    Известные ключи:
      prelim_price_coeff — множитель для «Предварительной цены» у позиций
                           без кода АГСК или с пустой ценой КазНИИСА
                           (Партнёр/проект/дистр. × коэффициент). По умолчанию 1.9.
    """
    __tablename__ = "app_settings"

    id          = Column(Integer, primary_key=True, index=True)
    key         = Column(String(100), unique=True, nullable=False, index=True)
    value       = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    updated_by  = Column(String(100), nullable=True)
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(),
                         onupdate=func.now())


# Значения по умолчанию для app_settings
DEFAULT_APP_SETTINGS = {
    "prelim_price_coeff": ("1.9",
                           "Множитель Партнёр/проект/дистр. для предварительной цены "
                           "у позиций без цены КазНИИСА"),
}
