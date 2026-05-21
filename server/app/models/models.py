from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean
from sqlalchemy.sql import func
from app.core.database import Base


class Product(Base):
    """Таблица товаров — основная БД"""
    __tablename__ = "products"

    id         = Column(Integer, primary_key=True, index=True)
    num        = Column(Integer, nullable=True)          # № GQ
    article    = Column(String(200), index=True)         # Артикул
    name       = Column(Text, nullable=True)             # Наименование
    unit       = Column(String(50), nullable=True)       # Ед. изм.
    kaznisa    = Column(Float, nullable=True)            # КазНИИСА
    rrts       = Column(Float, nullable=True)            # РРЦ
    mrc        = Column(Float, nullable=True)            # МРЦ
    opt        = Column(Float, nullable=True)            # Опт
    partner    = Column(Float, nullable=True)            # Партнёр
    brand      = Column(String(100), nullable=True, index=True)  # Бренд
    multiplicity = Column(Integer, nullable=True)        # Кратность
    kaznisa_code = Column(String(100), nullable=True)   # Код КазНИИСА
    is_active  = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class BrandConstant(Base):
    """Константы коэффициентов для брендов"""
    __tablename__ = "brand_constants"

    id         = Column(Integer, primary_key=True, index=True)
    brand      = Column(String(100), unique=True, index=True)
    margin     = Column(Float, default=1.2)      # Маржа
    logistics  = Column(Float, default=1.03)     # Лог-ка
    rate       = Column(Float, default=4.0)      # Расценка
    currency_rate = Column(Float, default=1.0)   # Курс
    nds        = Column(Float, default=1.16)     # НДС
    gp         = Column(Float, default=0.8)      # ГП
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CurrencyRate(Base):
    """Курсы валют"""
    __tablename__ = "currency_rates"

    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String(50), unique=True)   # Тенге, Рубль, Доллар…
    rate       = Column(Float, default=1.0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Manager(Base):
    """Менеджеры из листа Const (B-E): ФИО, должность, e-mail, телефон.
    Используется dropdown'ом в окне «Сохранение КП» на клиенте."""
    __tablename__ = "managers"

    id        = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(200), unique=True, index=True)
    position  = Column(String(200), nullable=True)
    email     = Column(String(200), nullable=True)
    phone     = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ImportLog(Base):
    """Лог импортов БД"""
    __tablename__ = "import_logs"

    id         = Column(Integer, primary_key=True, index=True)
    filename   = Column(String(300))
    rows_added = Column(Integer, default=0)
    rows_updated = Column(Integer, default=0)
    status     = Column(String(50), default="success")
    message    = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
