from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Text, Boolean,
    ForeignKey, Enum as SAEnum
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum


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
    rate          = Column(Float, default=4.0)
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
    rows_added   = Column(Integer, default=0)
    rows_updated = Column(Integer, default=0)
    status       = Column(String(50), default="success")
    message      = Column(Text, nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())


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
