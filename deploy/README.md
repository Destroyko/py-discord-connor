# deploy/

- **`connor.service`** — systemd-юнит (`Restart=on-failure`, `RestartSec`,
  `StartLimitBurst`/`StartLimitIntervalSec` против busy-loop, `RestartPreventExitStatus=2`
  для битого конфига). Пути в нём — конвенция `/opt/connor`, поправить под свой VPS.

Полная инструкция по развёртыванию (Discord-настройка, установка, **прогон
`pytest` перед первым стартом**, systemd, обновление, бэкап БД, траблшутинг) —
[../DEPLOY.md](../DEPLOY.md).
