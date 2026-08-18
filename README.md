# Piyasa İstihbarat Ağı

GitHub Actions ile 7/24 veri toplayan ve GitHub Pages üzerinde gösteren ücretsiz finans/makro/kripto dashboard projesi.

## Ajanlar

1. Makro
2. Kredi
3. Kripto
4. Kripto Türev
5. Opsiyon / VIX
6. Hisse / Emtia
7. Gizli Baskı
8. Top 200 Coin Tarayıcı
9. Haberler

Tüm site verisi `generate_site_data.py` tarafından `docs/data/*.json` dosyalarına yazılır. `.github/workflows/site.yml` her 6 saatte bir çalışır.

## GitHub kurulumu

Repo → **Settings → Secrets and variables → Actions** altında `FRED_API_KEY` eklenmelidir.

Repo → **Settings → Pages** altında **Deploy from a branch → main → /docs** seçilmelidir.

`Site Verisini Güncelle` workflow'u ayrıca Actions ekranından manuel çalıştırılabilir.

## Veri kaynakları

FRED, Yahoo Finance, CoinGecko, Binance Futures, Deribit, Bybit, OKX, Alternative.me ve Google News RSS. Bazı özel göstergeler güvenilir ücretsiz veri kaynağı olmadığı için kasıtlı olarak gösterilmez.
