# Набор «контроль владельца»

В репозитории лежит небольшой набор файлов, который держит его под контролем владельца. Этот же набор можно скопировать в любой другой репозиторий.

**Что на GitHub уже работает без настроек:** пушить в ваш репозиторий не может никто, кроме вас (и соавторов, которых вы сами пригласили). Посторонние могут только сделать форк, завести issue или предложить pull request. Набор закрывает остальные риски: случайный мерж плохого PR, злоупотребление CI из форков, подмену GitHub Actions и утечку секретов.

## Файлы в репозитории

| Файл | Что делает |
|---|---|
| `.github/CODEOWNERS` | Владелец становится обязательным ревьюером для каждого файла. |
| `.github/rulesets/main-protection.json` | Набор правил для импорта: `main` нельзя удалить или перезаписать force-push, изменения только через PR с одобрением владельца и зелёным CI. Владелец (роль admin) может обходить правила. |
| `.github/workflows/ci.yml` | Безопасный CI: только триггер `pull_request`, токен только на чтение, actions закреплены по SHA коммита, проверка на секреты при каждом запуске. |
| `.github/dependabot.yml` | Обновляет закреплённые actions через PR, которые вы проверяете. |
| `SECURITY.md` | Сообщения об уязвимостях приходят приватно, а не публичным issue. |
| `CONTRIBUTING.md`, `pull_request_template.md` | Сразу объясняют правила для внешних участников. |
| `.gitignore` | Не пускает в git файлы `.env`, ключи и артефакты сборки. |

## Разовые настройки (минуты три, в браузере)

Их нельзя сохранить в файлах, поэтому они делаются один раз для каждого репозитория.

1. **Settings → Rules → Rulesets → New ruleset → Import a ruleset**, выбрать `.github/rulesets/main-protection.json`, сохранить.
   Если после этого пуш от автоматизации (например, сессии Claude) отклоняется, пушьте через PR или добавьте это приложение в «Bypass list».
2. **Settings → Code security**: включить *Secret scanning*, *Push protection*, *Private vulnerability reporting* и *Dependabot alerts*.
3. **Settings → Actions → General**:
   - *Fork pull request workflows from outside collaborators*: **Require approval for all outside collaborators**.
   - *Workflow permissions*: **Read repository contents**, галочку «Allow GitHub Actions to create and approve pull requests» **не ставить**.
4. **Settings → General → Features**: выключить *Wikis* и *Projects*, если не пользуетесь (меньше мест для спама).
5. **Settings → Collaborators**: оставить список пустым, если соавтор действительно не нужен.

## Как перенести набор в другой репозиторий

Скопировать `.github/CODEOWNERS`, `.github/rulesets/`, `.github/dependabot.yml`, `SECURITY.md`, `CONTRIBUTING.md` и правила про секреты из `.gitignore`, при необходимости заменить имя пользователя, затем повторить разовые настройки выше.
