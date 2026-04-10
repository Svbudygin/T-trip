#!/bin/bash
# Открыть порт 5432 для удалённого доступа к PostgreSQL (осторожно: только для доверенных сетей/VPN)
set -e
if command -v ufw &>/dev/null; then
  sudo ufw allow 5432/tcp comment 'PostgreSQL'
  sudo ufw status | grep 5432
  echo "Порт 5432 открыт (ufw). Перезагрузите правила: sudo ufw reload"
elif command -v firewall-cmd &>/dev/null; then
  sudo firewall-cmd --permanent --add-port=5432/tcp
  sudo firewall-cmd --reload
  echo "Порт 5432 открыт (firewalld)"
else
  echo "Установите ufw или firewalld, либо откройте порт 5432 вручную в панели облака (Security Group / firewall)"
fi
