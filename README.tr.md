# Redirect Map Check

Sürüm 1.0.0. Aynı siteye ait basit eski/yeni yol haritasındaki tekrarları, çelişkileri, kendine yönlendirmeleri, döngüleri ve zincirleri çevrimdışı kontrol eden küçük Python CLI. [English](README.md).

Yalnız açıkça verdiğiniz CSV dosyası okunur. Ağ, HTTP isteği, tarama, telemetri, otomatik düzeltme ve sunucu yapılandırması üretimi yoktur. CSV ve sunucu ayarları değiştirilmez. Rapordaki son yol yalnız haritada artık kural bulunmayan yoldur; varlığı, yanıt kodu ve erişilebilirliği doğrulanmaz. Haritada bulgu olmaması sitenin çalıştığını, SEO sonucunu veya güvenliğini kanıtlamaz.

## Çalıştırma

Çıkartılan `redirect-map-check` klasöründe mevcut Python yorumlayıcısını kullanın. Kurulum veya üçüncü taraf paket gerekmez. Hedef sözdizimi Python 3.10+; gerçekten test edilen ortam CachyOS Linux x86_64, CPython 3.14.9'dur. KDE masaüstünde terminalden çalıştırıldı. Windows, macOS ve diğer Python sürümleri denenmedi; destek doğrulanmış sayılmaz.

```text
python -B redirect_map_check.py examples/clean.csv --lang tr
python -B redirect_map_check.py examples/chain.csv --lang en
python -B redirect_map_check.py examples/mixed.csv --format json
python -B -m unittest discover -s tests -v
```

İlk örnek 0, zincir ve karışık örnek 1, `examples/invalid.csv` 2 döndürür. Bulgu bulunan örnekte 1 beklenen sonuçtur. Kendi dosyanızın açık yolunu `csv_file` konumuna verin; boşluklu yolları tırnak içine alın. Standart girdiden, bir URL'den, klasörden veya wildcard ile otomatik dosya arayarak okuma yapılmaz. `--help` İngilizce kullanım özetini, `--version` sürümü gösterir.

## CSV ve desteklenen yol dili

UTF-8, isteğe bağlı tek BOM; virgül ayırıcı; LF veya CRLF satır sonu. İlk fiziksel satırdaki başlık ve sırası tam olarak `from,to,status` olmalı. Standart çift tırnaklı CSV alanları kabul edilir. Her veri kaydı tek fiziksel satırda üç dolu alan içermeli. Boş satır, yorum satırı, çok satırlı kayıt, ek/eksik sütun kabul edilmez. Alanların boşlukları otomatik kırpılmaz.

```csv
from,to,status
/old-guide,/guides,301
/guides,/learn,308
```

Yol `/` olabilir; diğer yollar tek `/` ile başlar, boş olmayan segmentlerden oluşur ve isteğe bağlı tek `/` ile biter. Segmentlerde yalnız ASCII `A-Z a-z 0-9 _ - .` karakterleri vardır. Tek başına `.` veya `..` segmenti yoktur. `/guide`, `/Guide/`, `/docs/page.html`, `/.well-known/file` geçerlidir. `/guide` ve `/guide/`, `/Guide` ve `/guide` ayrı anahtarlardır. Hiçbir normalleştirme veya URL çözme yapılmaz.

Tam URL, `//host/path`, göreli yol, query, fragment, `%` içeren her kodlanmış yol, Unicode yol, boşluk, ters eğik çizgi, çift iç eğik çizgi, wildcard ve regex bu sürümün dışındadır; reddedilir. Örneğin `/a%2Fb` veya `/a?x=1` ayrı bir desteklenen yol gibi yorumlanmaz. Aynı site varsayımı kullanıcının haritayı bu kapsamda hazırlamasına dayanır; araç host kimliğini denetleyemez. Yalnız `301`, `302`, `307`, `308` durumları kabul edilir. Bunların uygunluğunu, istek yöntemini veya HTTP davranışını CSV'den doğrulamaz.

Sınırlar: dosya en çok 2 MiB (2.097.152 bayt, BOM dahil); başlık hariç en çok 2.000 veri kaydı; her yol en çok 512 ASCII karakter; fiziksel satır LF öncesinde en çok 2.048 UTF-8 bayt (CRLF içindeki CR sayılır, çözülen ilk BOM sayılmaz). Kaynak düzenli dosya olmalı; POSIX FIFO beklemeden reddedilir. Bir sembolik bağ düzenli dosyaya işaret ediyorsa okunabilir. Boyut okuma öncesinde ve sınırlı okumadan sonra kontrol edilir. Sınırları aşan girdi analiz edilmez. Bunlar ayrı tavanlardır; geçerli bir dosyanın hepsini aynı anda doldurması gerekmez.

## Bulgular nasıl yorumlanır?

- **Aynı satır tekrarı:** `from,to,status` üçlüsü aynıdır. Bütün fiziksel satır numaraları korunur; grafikte bir kenar olarak kullanılır.
- **Çelişki:** aynı `from` için birden çok hedef veya durum vardır. Bütün varyantlar raporlanır; hiçbir varyant seçilmez. O kaynağa ulaşan kesin yollar `blocked_routes` içinde durur.
- **Kendine yönlendirme:** `from == to`. Çelişkili bir varyant olsa bile ayrıca gösterilir; `in_conflict` bunu belirtir.
- **Çok düğümlü döngü:** yalnız belirsiz olmayan kurallardaki iki veya daha çok düğümlü kapalı yol. Her döngü bir kez, en küçük ASCII yolundan başlayarak gösterilir. Kendine yönlendirmeler bu listeye tekrar eklenmez.
- **Zincir:** kendisi döngü düğümü olmayan kaynaktan en az iki kesin yönlendirme. Sonlanabilir, döngüye girebilir veya çelişkide durabilir. Her başlangıç kaynağı ayrı kayıttır; `/a -> /b -> /c -> /d` için `/a` üç, `/b` iki adımlı zincirdir. Döngüye giren zincirde `hops`, ilk tekrar görülene kadar olan adımları (döngünün bir turu dahil), `hops_to_cycle` girişe kadarki adımları gösterir. Çelişkide durduğunda yalnız kesin kenarlar sayılır. Döngü/çelişki için son yol yoktur.

Çelişkilerin gizlediği olası döngüler hakkında temiz sonucu çıkarılmaz. `graph_scope=unambiguous_rules_only` bu sınırı belirtir. Kuralların sunucudaki öncelik sırası, harita dışındaki davranış, host/HTTPS veya sondaki eğik çizgi kuralları bilinmez. Rapor tam yolları içerir; paylaşmadan önce kendi ortamınızda inceleyin. Örnekler tamamen sentetiktir.

## Çıktı sözleşmesi

`--format text` varsayılandır, dili `--lang tr|en` belirler (varsayılan TR). Geçerli girdinin raporu stdout'a, girdi/dosya hatasının metni stderr'e yazılır. `--format json` bütün raporları stdout'a tek JSON nesnesi olarak yazar. Shell ile raporu dosyaya yönlendirmek sizin seçiminizdir; CLI dosya yazma seçeneği içermez.

JSON anahtarları İngilizcedir; `--lang` JSON baytlarını değiştirmez. Aynı girdi ve araç sürümü aynı JSON baytlarını üretir: sıralı anahtarlar, sabit sıralı kayıtlar, LF sonlandırma; saat, yerel dosya yolu veya rastgele kimlik yoktur. `schema_version=1`, `tool_version=1.0.0`; `result` geçerli girdide `clean` veya `findings`, geçersizde `invalid_input`, dosya hatasında `io_error` olur.

Geçerli girdide `rules` bütün tekil kuralları ve `lines` alanında fiziksel satırları verir. `routes` her belirsiz olmayan kaynağın sonucunu taşır; `outcome=terminal|cycle|conflict`. `chains`, `duplicates`, `conflicts`, `self_loops`, `cycles`, `blocked_routes` ayrı listelerdir. `counts` liste/grup sayısını belirtir: duplicate sayısı fazladan satır sayısı, zincir sayısı bileşen sayısı değildir. `reachability=not_verified` bütün son yollar için geçerlidir. Grafiğin tam patikaları her başlangıç için tekrar edilmez; kural tablosundan izlenebilir.

Hatalı veya desteklenmeyen tek bir kayıt bile bütün analizi durdurur. İlk hata kodu, biliniyorsa satır/sütun alanı verilir; `analysis_performed=false` olur ve kısmi `counts`, `routes` veya temiz raporu üretilmez. UTF-8, dosya boyutu ve okuma hatalarında güvenilir satır numarası bulunmayabilir.

## Çıkış kodları

| Kod | Anlam |
| --- | --- |
| 0 | Geçerli haritada kapsam içi bulgu yok; ayrıca `--help` / `--version`. Canlı başarı anlamına gelmez. |
| 1 | Geçerli haritada en az bir tekrar, çelişki, kendine yönlendirme, döngü veya zincir var. |
| 2 | Geçersiz/desteklenmeyen/sınır aşan girdi ya da yanlış CLI kullanımı. Analiz sonucu yok. |
| 3 | Dosya okuma/tür hatası veya yakalanan çıktı borusu kesintisi. |

Yanlış argümanlar argparse tarafından stderr'e kullanım metniyle yazılır; `--format json` verilmiş olsa bile argüman ayrıştırma hatası JSON değildir. Beklenmeyen işletim sistemi kesintileri için farklı süreç kodları oluşabilir.

## Test ve sınır

Kanonik kontrol `python -B -m unittest discover -s tests -v`. 45 test, sentetik fixture'lar ve 100 deterministik küçük rastgele grafiği bağımsız basit izleme ile karşılaştırır. Python socket audit olayları testlerde ve CLI alt süreçlerinde hata verir; hiçbir gerçek hedef kullanılmaz. Ağ engelinin aktif olduğu da yerel socket oluşturma girişiminin reddedilmesiyle doğrulanır. Kaynağın SHA-256 ve mtime değeri okuma sonrasında aynı kalır. Kaynak ve ZIP'ten çıkartılan dağıtım aynı testlerle ayrı doğrulandı. Test platformu ve kapsamı [QA](QA.md) içindedir. Bu yerel doğrulamadır; GitHub CI sonucu değildir.

MIT lisansı. Copyright (c) 2026 Muhammet Sarıdoğan. [LICENSE](LICENSE) dosyasına bakın. Depo: [Muhammet0-1/RedirectMapCheck](https://github.com/Muhammet0-1/RedirectMapCheck).
