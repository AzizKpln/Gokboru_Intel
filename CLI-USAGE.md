# Gökbörü / Moriarty CLI

## Kaynakları listele

```bash
bash ./moriarty-local phone-audit "+905xxxxxxxxx" --i-own-this-number --list-sources
```

## Seçili kaynakları çalıştır

```bash
xvfb-run -a bash ./moriarty-local phone-audit "+905xxxxxxxxx" \
  --i-own-this-number \
  --sources local,facebook,whatsapp,cybernews,databreach,reputation \
  --timeout 180
```

## Bütün kaynakları çalıştır ve JSON kaydet

```bash
xvfb-run -a bash ./moriarty-local phone-audit "+905xxxxxxxxx" \
  --i-own-this-number \
  --sources all \
  --timeout 180 \
  --output "./reports/phone-audit.json"
```

## Yalnızca Facebook

```bash
xvfb-run -a bash ./moriarty-local facebook-self-check "+905xxxxxxxxx" \
  --i-own-this-number \
  --timeout 180
```

`xvfb-run -a`, tarayıcı tabanlı kaynakları görünür pencere açmadan çalıştırır.
