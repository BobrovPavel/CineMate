# Развёртывание на Oracle Cloud (Always Free) с HTTPS

Инструкция для Windows (PowerShell со встроенными `ssh` и `scp`). Результат: CineMate на машине
Oracle A1 с HTTPS на вашем домене; наружу открыты только порты 22, 80 и 443.

Исходные решения: сервер — Oracle Cloud, бесплатный тариф; домен куплен в Cloudflare Registrar,
DNS там же.

Бесплатный тариф ([Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm)):
Ampere A1 (Arm), суммарно 2 OCPU и 12 ГБ памяти, 200 ГБ диска, 10 ТБ исходящего трафика в месяц.
Неиспользуемую машину Oracle может отозвать: если за 7 дней одновременно 95-й перцентиль CPU,
сеть и память ниже 20 %. Настройки PostgreSQL из `docker-compose.prod.yml` (`shared_buffers=3GB`)
заодно держат память выше порога. Все образы (`python:3.12-slim`, `node:22-alpine`,
`postgres:16`, `caddy:2`) есть для `linux/arm64`, поэтому образы проще собирать прямо на сервере.

## 1. Oracle Cloud

1. Зарегистрируйтесь на <https://www.oracle.com/cloud/free/>. **Домашний регион выбирается один
   раз и потом не меняется.** Для пользователей из СНГ подходят Франкфурт, Амстердам, Стокгольм;
   во Франкфурте часто нет свободных A1.
2. Создайте SSH-ключ в PowerShell (если его ещё нет):
   ```powershell
   ssh-keygen -t ed25519 -f $HOME\.ssh\cinemate
   ```
   Публичный ключ — `$HOME\.ssh\cinemate.pub`.
3. Compute → Instances → Create instance:
   - образ: Ubuntu 24.04 для aarch64 (Canonical Ubuntu, ARM);
   - форма: `VM.Standard.A1.Flex`, 2 OCPU и 12 ГБ памяти;
   - загрузочный диск: 100 ГБ;
   - публичный IPv4 включён; SSH-ключ — содержимое `cinemate.pub`.
4. Ошибка «Out of capacity»: повторите позже или выберите другую зону доступности (Availability
   Domain) в том же регионе.
5. Запишите публичный IP машины (далее `IP`). Подключение:
   ```powershell
   ssh -i $HOME\.ssh\cinemate ubuntu@IP
   ```

## 2. Сеть

В образах Ubuntu от Oracle всё, кроме SSH, закрыто и в облачной сети, и на самой машине.
Нужно открыть порты в обоих местах.

1. **Security List сети VCN.** Networking → Virtual Cloud Networks → ваша сеть → подсеть →
   Security List → Add Ingress Rules: источник `0.0.0.0/0`, протокол TCP, порт назначения `80`;
   то же для `443`. Порт 22 уже открыт.
2. **iptables на машине** (по SSH):
   ```bash
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
   sudo apt-get install -y iptables-persistent   # на вопросы о сохранении правил ответьте Yes
   sudo netfilter-persistent save
   ```
   Позиция `6` стоит перед правилом `REJECT`; проверьте порядок: `sudo iptables -L INPUT -n --line-numbers`.
   Правила ACCEPT для 80 и 443 должны идти выше `REJECT`.

## 3. Проверка доступности из России до покупки домена

С июня 2025 года российские провайдеры режут соединения с сайтами за прокси Cloudflare: проходят
примерно первые 16 КБ
([блог Cloudflare](https://blog.cloudflare.com/russian-internet-users-are-unable-to-access-the-open-internet)).
По сообщениям, так же режут часть западных хостингов. Поэтому до покупки домена проверьте, что
ваш сервер доступен из российских сетей.

На сервере (временно, до установки Docker из шага 4 можно поставить его так же; если Docker уже
стоит — просто выполните):
```bash
head -c 1048576 /dev/urandom > test.bin
docker run -d --name tmpnginx -p 80:80 -v "$PWD/test.bin:/usr/share/nginx/html/test.bin:ro" nginx
```
С компьютера в российской **мобильной** сети (и желательно у нескольких провайдеров):
```powershell
curl.exe -o NUL -w "%{size_download} %{time_total}\n" http://IP/test.bin
```
Ожидается `1048576` и несколько секунд. Если загрузка обрывается около 16 КБ (`size_download`
порядка 16000), доступ режется: для пула `ru` нужен другой хостинг, решение за владельцем.
После проверки обязательно удалите тестовый контейнер: `docker rm -f tmpnginx; rm test.bin`.
Иначе он продолжит занимать порт 80, и Caddy не запустится. Docker ставится в шаге 4, поэтому
проверку удобнее делать после него, но до покупки домена.

## 4. Подготовка машины

```bash
sudo apt-get update && sudo apt-get -y upgrade
sudo apt-get install -y ca-certificates curl git
# Docker Engine и плагин compose из официального репозитория Docker
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker ubuntu     # затем выйдите и войдите по SSH заново
```

**Вход только по ключу.** Убедитесь, что вход по ключу работает (отдельным окном), затем:
```bash
sudo tee /etc/ssh/sshd_config.d/99-hardening.conf <<'CONF'
PasswordAuthentication no
PermitRootLogin no
CONF
sudo systemctl restart ssh
```

**Автоматические обновления безопасности:**
```bash
sudo apt-get install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

## 5. Cloudflare

1. Купите домен в Cloudflare Registrar.
2. DNS → Add record: тип `A`, имя `@`, IPv4 — `IP`; ещё одна запись `A` с именем `www` и тем же IP.
3. **Proxy status — «DNS only»** (серое облако) у обеих записей.

Прокси Cloudflare включать нельзя: через него российские провайдеры обрывают соединения (см. ссылку
в шаге 3). Сертификаты Let's Encrypt Caddy получает сам, для этого домен должен напрямую
указывать на сервер.

## 6. Первый запуск

```bash
git clone https://github.com/BobrovPavel/CineMate.git
cd CineMate
cp .env.example .env
nano .env
```
В `.env` заполните:
- `POSTGRES_PASSWORD` — надёжный пароль **без символов `@ / : #`** (он подставляется в URL базы);
- `TMDB_API_KEY`;
- `DOMAIN` — например, `example.com` (без `https://` и без `www`);
- `ACME_EMAIL` — почта для уведомлений Let's Encrypt;
- по желанию `COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml` — тогда в командах ниже
  `-f ...` не нужны. Дальше в инструкции — полный вариант:

```bash
DC="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
$DC build
$DC --profile tools build app
$DC run --rm app migrate
$DC up -d
$DC ps
```
Проверка: `https://ДОМЕН/api/health` в браузере или `curl https://ДОМЕН/api/health`.
Если сертификат не выдаётся — смотрите `$DC logs caddy` (чаще всего DNS ещё не обновился,
включён прокси Cloudflare или закрыт порт 80/443).

## 7. Перенос данных с домашнего компьютера

**Дома** (PowerShell, в папке проекта, стек запущен):
```powershell
docker compose exec -T db pg_dump -U cinemate -Fc cinemate -f /tmp/cinemate.dump
docker compose cp db:/tmp/cinemate.dump .\cinemate.dump
scp -i $HOME\.ssh\cinemate .\cinemate.dump ubuntu@IP:~/
```
**На сервере** (в папке `CineMate`, стек из шага 6 запущен):
```bash
DC="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
$DC stop api frontend
$DC cp ~/cinemate.dump db:/tmp/cinemate.dump
$DC exec db pg_restore -U cinemate -d cinemate --clean --if-exists --no-owner /tmp/cinemate.dump
$DC run --rm app migrate
$DC up -d
$DC restart api    # API держит матрицу оценок в памяти
```
Затем `rm ~/cinemate.dump` (на обоих компьютерах: в дампе пользовательские данные).

**Альтернатива — с нуля:** после `migrate` выполните `import-movielens`, `import-ratings-csv`,
`sync-catalog` (см. README). Из дата-центра запросы к TMDB заметно быстрее.

## 8. Обновление версии

```bash
cd CineMate
git pull
DC="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
$DC build
$DC --profile tools build app
$DC run --rm app migrate
$DC up -d
```

## 9. Логи и состояние

```bash
$DC ps                  # у db и api должно быть healthy
$DC logs -f api         # также: frontend, caddy, db
$DC logs --tail 100 caddy
```
Логи ротируются (`json-file`, 3 файла по 10 МБ на сервис). Все сервисы стартуют сами после
перезагрузки машины (`restart: unless-stopped`).

## Не входит сюда

Расписание фоновых команд и резервные копии, CI/CD и автодеплой, прокси и туннели Cloudflare,
мониторинг — отдельные задачи.
