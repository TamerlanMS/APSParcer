# Развёртка на сервере 192.168.2.78

## 1. Передача файлов на сервер

С вашего компьютера (Windows — через WSL, Git Bash или PowerShell с openssh):

```bash
# Исключаем лишнее: кэш Python, старые дистрибутивы, __pycache__
rsync -avz --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' \
  --exclude='dist' --exclude='build' --exclude='*.egg-info' \
  /c/projects/APSParcer/ gq@192.168.2.78:~/APSParcer/
```

Или через scp (архивом):
```bash
# На Windows (PowerShell):
tar -czf APSParcer.tar.gz -C C:/projects APSParcer --exclude='APSParcer/.git' --exclude='APSParcer/__pycache__'
scp APSParcer.tar.gz gq@192.168.2.78:~/
# На сервере:
tar -xzf APSParcer.tar.gz
```

## 2. Настройка на сервере

```bash
ssh gq@192.168.2.78
cd ~/APSParcer
```

### Создать .env файл:
```bash
cp .env.example .env
nano .env
```

Заполнить:
```
DB_PASS=ваш_пароль_для_базы
ADM_PASS_HASH=хеш_пароля_администратора
JWT_SECRET_KEY=случайная_строка_32_символа
SUPERADMIN_USERNAME=admin
SUPERADMIN_PASSWORD=ваш_пароль_superadmin
```

### Сгенерировать значения:
```bash
# JWT secret:
python3 -c "import secrets; print(secrets.token_hex(32))"

# Хеш пароля admin (установите bcrypt если нет):
pip3 install bcrypt --break-system-packages
python3 -c "import bcrypt; print(bcrypt.hashpw(b'ВАШ_ПАРОЛЬ', bcrypt.gensalt()).decode())"
```

> ⚠️ В файле `.env` хеш пишется как есть (со знаками $).  
> В `docker-compose.yml` знаки $ экранируются как $$, но в `.env` — нет.

## 3. Запуск

```bash
chmod +x deploy.sh
./deploy.sh
```

Скрипт:
- Проверит наличие .env
- Создаст папку `server/data/`
- Соберёт Docker образ и запустит контейнеры
- Дождётся готовности API

## 4. Проверка

```bash
curl http://192.168.2.78/health
# Ожидается: {"status":"ok"} или аналог

docker compose -f docker-compose.prod.yml logs -f api
```

## 5. Полезные команды

```bash
# Логи
docker compose -f docker-compose.prod.yml logs -f api

# Перезапуск API (после обновления кода)
docker compose -f docker-compose.prod.yml up -d --build api

# Остановить всё
docker compose -f docker-compose.prod.yml down

# Остановить с удалением БД (осторожно!)
docker compose -f docker-compose.prod.yml down -v
```

## 6. Обновление кода

```bash
# Передать новые файлы с компьютера:
rsync -avz --exclude='__pycache__' --exclude='*.pyc' \
  /c/projects/APSParcer/server/ gq@192.168.2.78:~/APSParcer/server/

# На сервере пересобрать и перезапустить:
cd ~/APSParcer
docker compose -f docker-compose.prod.yml up -d --build api
```
