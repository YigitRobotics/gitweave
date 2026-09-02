# gitweave

Bitmiş bir projeyi tek dev commit yerine mantıklı, incelenebilir parçalara
bölerek git'e ekleyen bir araç. **Sahte bir geliştirme geçmişi üretmez.**

## Neden

Bir projeyi baştan sona lokal olarak yazıp en sonunda GitHub'a tek commit
halinde atmak, dışarıdan "AI ile tek seferde üretilmiş" gibi görünebiliyor —
kod elle, uzun bir süreçte yazılmış olsa bile. gitweave bu görünümü,
**gerçeği çarpıtmadan** düzeltir:

- **`today` modu**: Push bugün yapılıyor, dolayısıyla tüm commit'ler bugünün
  tarihiyle atılır — sadece dosya/modül bazlı mantıklı parçalara bölünür.
  Hiçbir tarih uydurulmaz.
- **`history` modu**: Commit tarihleri, dosyaların **gerçek** son değişiklik
  zamanlarından (mtime) türetilir. Eğer dosyalar arasında anlamlı bir zaman
  farkı yoksa (örn. proje bir zip'ten yeni çıkarılmış), araç bunu **algılar**
  ve otomatik olarak `today` moduna döner — asla rastgele/uydurma tarih
  üretmez.

## Kurulum

```bash
git clone <repo>
cd gitweave
make                       # C bileşenini derler (src/fastscan) — opsiyonel

python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

`gitweave` komutu artık bu sanal ortam aktifken kullanılabilir. Yeni bir
terminal açtığınızda tekrar `source .venv/bin/activate` çalıştırmanız yeterli.

Sisteminizde global `pip install` "externally-managed-environment" hatası
veriyorsa (Debian/Ubuntu 23.04+, Fedora, vb.) — bu normaldir, sanal ortam
kullanmanız zaten önerilen ve bu hatayı otomatik olarak aşan yöntemdir.
`--break-system-packages` ile global kuruluma **zorlamanızı önermiyoruz**;
bu, sistem Python'unuzdaki diğer paketlerle çakışmaya yol açabilir.

Global ve izole bir kurulum istiyorsanız (birden fazla projede kullanacaksanız):

```bash
pipx install .
```

C derleyicisi yoksa araç otomatik olarak saf Python taramasına düşer (daha
yavaş ama tam işlevsel).

## Kullanım

### En basit yol: `run`

```bash
cd my-project
git init          # daha önce yapmadıysan
gitweave run .
```

Projeyi tarar, planı önizler, sana `[y/N]` ile onay sorar, onaylarsan
commit'ler. Author bilgisi `git config user.name`/`user.email`'den otomatik
alınır — ayrıca belirtmen gerekmez.

```bash
gitweave run . --push          # onaydan sonra push de eder
gitweave run . --push -y       # onay sormadan direkt commit + push
```

### Daha kontrollü yol: `analyze` → `plan` → `apply`

Planı JSON olarak inceleyip elle düzenlemek istersen bu üçlü daha uygun.

**1. Analiz (salt okunur, git'e dokunmaz)**
```bash
gitweave analyze ./my-project
```
Dosya sayısı, satır sayısı, dosya türü dağılımı ve `history` modunun bu
proje için mantıklı olup olmadığını gösterir.

**2. Plan oluştur**
```bash
gitweave plan ./my-project --mode today --out plan.json
```
`plan.json` içinde her commit için hangi dosyaların, hangi mesajla, hangi
tarihle gideceği yazılıdır. Git'e hiçbir şey yazılmaz — önce inceleyin,
isterseniz elle düzenleyin.

**3. Uygula**
```bash
# önce dry-run (varsayılan davranış, author bilgisi de otomatik git config'ten):
gitweave apply ./my-project --plan plan.json

# gerçekten commit'lemek için:
gitweave apply ./my-project --plan plan.json --execute

# commit + push (aynı anda):
gitweave apply ./my-project --plan plan.json --execute --push

# ya da önce --execute ile commit'le, sonra ayrı bir çağrıda sadece push et
# (aynı plan dosyasıyla, --execute vermeden --push vermek yeterli;
# zaten commit'lenmiş gruplar otomatik atlanır, tekrar commit denenmez):
gitweave apply ./my-project --plan plan.json --push
```

`--plan` verilmezse `apply` komutu planı o an oluşturup uygular
(`--mode`, `--max-files` vb. parametreleriyle). `--author-name`/
`--author-email` vermezseniz `git config user.name`/`user.email`
kullanılır; hiçbiri yoksa açık hata verir.

## Nasıl gruplanıyor?

1. Kök dizindeki `package.json`, `requirements.txt`, `.gitignore`,
   `Dockerfile` gibi scaffolding dosyaları → ilk commit.
2. Kalan dosyalar üst dizine göre gruplanır (`src/core`, `src/api`, `tests`...).
   Büyük dizinler `--max-files` sınırına göre birden fazla commit'e bölünür.
3. Dizinler kabaca bağımlılık sırasına göre sıralanır: `core/lib/utils` gibi
   temel katmanlar önce, ardından servis/uygulama kodu, sonra testler.
4. `README.md`, `CHANGELOG.md` gibi dokümanlar en sona alınır.

Bu sıralama basit ve şeffaf sezgisel kurallara dayanır — projenin gerçekten
nasıl yazıldığını taklit etme iddiası yoktur, sadece okunabilir bir sıra
sunar.

## Neden C var?

`src/fastscan.c`, büyük repoları (binlerce dosya, büyük binary asset'ler)
hızlıca taramak için satır sayısı, dosya boyutu, mtime ve içerik hash'ini
tek geçişte hesaplayan bir tarayıcı. Python tarafı bu ikiliyi çağırır;
derlenmiş binary yoksa otomatik olarak saf Python taramasına düşer, yani
araç C derleyicisi olmayan ortamlarda da çalışır.

## Sınırlamalar / dürüstlük ilkesi

- Rastgele/keyfi geçmiş tarih üretme özelliği **yoktur ve eklenmeyecektir**.
- `history` modu yeterli gerçek kanıt (mtime farkı) olmadan çalışmaz,
  sessizce `today` moduna döner ve bunu size bildirir.
- `plan` her zaman `apply --execute` öncesi inceleme içindir; `apply`
  varsayılan olarak dry-run çalışır.
- Araç, isterseniz README'nize eklemeniz için otomatik bir "development
  notes" açıklama metni üretir (`gitweave plan` çıktısının sonunda).

## Bilinen sınırlamalar

- `apply`, mevcut bir git repo'sunda çalışır; repo'yu kendisi oluşturmaz.
  Önce `git init` çalıştırmanız gerekir.
- Bir planı `--execute` ile bir kez uyguladıktan sonra aynı planı tekrar
  çalıştırmak güvenlidir: zaten commit edilmiş gruplar sessizce atlanır,
  tekrar commit denenmez.
- `--push`, `--execute` olmadan da kullanılabilir — bu durumda repo'daki
  mevcut commit'ler push edilir, plan tekrar uygulanmaya çalışılmaz.

## Testler

```bash
make test
# veya
python3 -m pytest -q tests/
```
