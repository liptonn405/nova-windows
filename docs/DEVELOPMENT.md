# Разработка и публикация

## Локально

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Dev
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m nova.app --smoke-test
```

На Linux возможен только просмотр UI и тестирование логики:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
.venv/bin/python -m nova.app --demo
```

Для Linux `--demo` не запускает оконные/аудио адаптеры Windows. Это не замена версии NOVA для GNOME.

## Опубликовать проект, чтобы другие могли клонировать

Создай пустой репозиторий в своём Git-хостинге. В папке проекта:

```bash
git init -b main
git add .
git commit -m "Initial NOVA Windows port"
git remote add origin <URL_СОЗДАННОГО_РЕПОЗИТОРИЯ>
git push -u origin main
```

Если Git ещё не настроен, сначала задай своё имя и почту для коммитов. Затем замени `<URL_РЕПОЗИТОРИЯ>` в README настоящим адресом и закоммить изменение.

`.venv`, локальные модели, `.env` и журналы исключены через `.gitignore`. Пользовательские настройки хранятся вне проекта. Проверь `git status` перед публикацией. GitHub Actions уже описан для Windows и Ubuntu, Python 3.11/3.12; он запустится только после публикации на GitHub.

Лицензия исходников — MIT. Модели Ollama, Vosk, Windows-голоса и сторонние зависимости имеют собственные лицензии, в архив не включены.
