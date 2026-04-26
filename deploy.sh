#!/bin/bash

echo "📥 Pulling latest code..."
cd ~/wealthlens || exit

git fetch origin
git checkout feat-add-stock
git pull origin feat-add-stock

echo "🔁 Restarting bot..."
sudo systemctl restart portfoliobot

echo "🔗 Setting webhook..."

curl -F "url=https://136.116.210.56:8443/webhook" \
     -F "certificate=@/home/sairambandaru009/wealthlens/webhook.crt" \
     https://api.telegram.org/bot8036876869:AAGH_Zg3Z_cx1Ai-BzvirVQq1CH_Qlapqd8/setWebhook

echo "📜 Logs:"
sudo journalctl -u portfoliobot -n 20 --no-pager
