# Sosyal Hak Mevzuatı için Yerel Küçük Dil Modeli + İki Aşamalı Doğrulayıcı + Enerji Ölçümü: TÜBİTAK 2209-A Literatür Taraması ve Özgünlük Değerlendirmesi

Taradığımız kaynaklarda, Türkçe sosyal hak mevzuatı (engelli hakları, 2022 sayılı aylıklar, sosyal yardım, evde bakım, SGK) üzerinde çalışan, yerel küçük modelle kurulmuş, iki aşamalı doğrulama yapan ve enerji tüketimini ölçen bir proje bulamadık. Bu nedenle yeni kapsam TÜBİTAK açısından eski üniversite kapsamından daha özgün ve daha yüksek yaygın etkili. Ancak "7B + doğrulayıcı, 14B'ye göre daha az enerji harcar" varsayımı kendiliğinden doğru değil, ölçülerek kanıtlanması gerekiyor. Uluslararası tarafta kamu yardımı (SNAP), vatandaş hizmeti (GOV.UK) ve hukuki yardım alanlarında güçlü emsaller var. Bu emsaller projenin varsayımlarını, yani "daha iyi model değil, daha iyi dayanak", geri soru sormanın faydası ve çekimser kalmanın zorunluluğu gibi noktaları doğruluyor. Bu yüzden özgünlük iddiası "dünyada ilk" diye değil, "Türkçe sosyal hak mevzuatında, yerel 7B için, bileşen düzeyinde güvenilirlik–enerji ödünleşimini açık bir veri setiyle ölçen ilk çalışma (bildiğimiz kadarıyla)" diye kurulmalı.

## TL;DR

- **Boşluk gerçek:** Türkiye'de sosyal hak/engelli/sosyal yardım/SGK mevzuatına özgü, değerlendirmesi yayımlanmış bir LLM/RAG çalışması, açık etiketli Türkçe sosyal hak soru seti ya da bu bağlamda enerji ölçümü görülmedi. Aile ve Sosyal Hizmetler Bakanlığı'nın "yapay zekâ destekli dijital asistanlar devreye alınacak" açıklaması henüz bir plan; somut bir sistem ve değerlendirme yok. Uluslararası emsaller (Vals AI Public Benefits Bench, Nava/Cornell SNAP, ODI CitizenQuery-UK, MÖVE) ise sorunun önemini ve yöntemin gerekçesini güçlü biçimde destekliyor.
- **Ana katkı "kısmen özgün", güçlendirilebilir:** İki aşamalı doğrulama fikri (dayanak + soruyu karşılama) FACTS Grounding, Self-RAG ve RAGChecker'da var. Özgünlük üç şeyin birleşiminde: Türkçe sosyal hak alanı, yerel 7B ile 14B karşılaştırması ve doğrulayıcının enerji maliyetinin bileşen düzeyinde (2³ ablation + GLMM) ölçülmesi. Hesap aracı (rules-as-code) ve geri soru sorma tek başına özgün değil; geri soru için Vals verisi güçlü bir gerekçe sunuyor.
- **En büyük risk enerji hipotezi (H6):** ML.ENERGY v3.0'da yanıt başına enerjiyi model boyutundan çok çıktı uzunluğu belirliyor (Qwen 3 8B ≈1.398 J, Qwen 3 14B ≈1.338 J/yanıt). Ajan adımları da enerjiyi katlıyor (tek turda 0,32 Wh, Reflexion'da 41,53 Wh; 8B). Çok ajanlı 7B hattı, tek çağrılık 14B'yi enerjide geçemeyebilir. H6 "Wh/doğru cevap" üzerinden, kısa doğrulayıcı çıktılarıyla ve wattmetre doğrulamasıyla test edilmeli. Karbon için resmî kaynak ETKB-EVÇED 2023 tüketim noktası faktörü (dağıtım hattı 0,469 tCO₂-eşd./MWh; yayım 26.12.2025).

## Key Findings

1. **Türkiye'de doğrudan emsal görülmedi.** DergiPark, GitHub, TEKNOFEST, kamu kurumları ve genel web taramasında sosyal hak mevzuatına özgü bir LLM/RAG sistemi bulunamadı. Bakanlığın 2025 "Aile Yılı" duyurusu dijital asistanları gelecek zaman kipiyle anlatıyor. ALO 144, ALO 183, SGK ve e-Devlet için resmî bir LLM chatbotu doğrulanamadı. YÖK Tez Merkezi doğrudan sorgulanamadı; bu, başvurudan önce elle kapatılması gereken bir boşluk.
2. **Türkçe hukuk soru setleri var, sosyal hak seti yok.** TRLawBench (97 ÖSYM sorusu), LexVira Türkiye Hukuk AI Benchmark (309 soru; kaynak erişimi alt testi 62 soru, 14 alan), TurkishLegalBench (ODTÜ, 2026) ve TR-MMLU mevcut.\[1\]\[2\]\[3\]\[4\] Hiçbiri sosyal hak/engelli/sosyal yardım mevzuatına özgü değil, hiçbiri hesap gerektiren hak sorularını ve "cevapsız/kapsam dışı" sınıfını sistematik olarak içermiyor.
3. **Uluslararası kanıt projenin tasarım kararlarını doğruluyor:**
   - Vals AI Public Benefits Bench (459 SNAP senaryosu; ortaklar Center for Civic Futures ve Code for America): en iyi model ancak %76,9 doğru. Çok turlu, yani geri soru sorulabilen koşul büyük kazanç sağlıyor (Claude Opus 4.8: %36,6'dan %60,9'a). Sonuç cümlesi: "daha iyi modellere değil, daha iyi dayanağa ihtiyacımız var".
   - ODI CitizenQuery-UK (22.066 soru, 11 LLM): modellerin neredeyse hiç çekimser kalmadığı görülmüş ve bu "tehlikeli bir özellik" olarak nitelendirilmiş. Kısa yanıt istendiğinde doğruluk düşüyor.\[5\]\[6\]
   - Nava/Cornell (770 soruluk SNAP seti): chatbot önerileri vaka çalışanlarının doğruluğunu ortalama 21 puan artırıyor, ancak öneri hatalıysa zarar veriyor.
4. **Kırılgan kullanıcıya özgü risk belgelenmiş.** MIT'nin AAAI 2026 çalışmasında (Poole-Dayan, Roy, Kabbara; arXiv 2406.17737) Claude 3 Opus, eğitimi düşük ve anadili İngilizce olmayan kullanıcı profillerindeki soruların %10,9'unu reddetti; kontrol koşulunda bu oran %3,61'di. Doğruluk da bu gruplarda düştü: SciQ'da Claude'un doğruluğu kontrolde %95,60 iken eğitimi düşük İranlı erkek profilinde %79,80'e indi (p<0,01). Bu bulgu "sade dil + doğrulayıcı + insana yönlendirme" tasarımını meşrulaştırıyor.
5. **Enerji literatürü H6 için hem fırsat hem tuzak.**
   - ML.ENERGY Leaderboard v3.0'a göre akıl yürütme görevleri sohbetten ortalama 25 kat daha fazla enerji harcıyor.
   - Ajan tabanlı test-zamanı ölçeklemede sorgu başına enerji 62–136 kat artıyor ("The Cost of Dynamic Reasoning").\[7\]
   - Yanıt uzunluğu enerjiyi R² > 0,95 ile öngörüyor ("The Price of Prompting").
   - Sonuç: doğrulayıcıyı kısa ve yapılandırılmış çıktıyla (ör. etiket + gerekçe kimliği) tasarlamak, enerji hipotezinin başarısı için belirleyici.
6. **Ölçüm aracı uyarısı.** CodeCarbon, yazılım araçları arasında wattmetreye en yakın sonuç veren araç.\[8\] Yine de bazı deneylerde toplam enerjiyi belirgin biçimde düşük tahmin ediyor (Bouza vd.: CodeCarbon 252 Wh, wattmetre 391 Wh). Projede wattmetre doğrulaması bu yüzden süs değil, zorunlu bir bileşen.
7. **KVKK gerekçesi resmî olarak güçlendi.** KVKK'nın 24.11.2025 tarihli "Üretken Yapay Zekâ ve Kişisel Verilerin Korunması Rehberi (15 Soruda)" Türkiye dışında barındırılan yapay zekâ sistemlerinin kullanımını yurt dışına veri aktarımı olarak niteliyor. Ayrıca özel nitelikli veriler için KVKK m.6 şartlarını hatırlatıyor.\[9\]\[10\] Bu, "yerel model" tercihinin hukuki gerekçesini doğrudan destekliyor.

## Türkiye'deki geçmiş projeler ve çalışmalar

**Kamu kurumları**
- **Aile ve Sosyal Hizmetler Bakanlığı (2025):** "Yapay zekâ destekli yeni dönem" duyurusunda dijital asistanların "devreye alınacağı", başvuru süreçlerinde otomatik yönlendirme yapılacağı ve karar destek mekanizmalarının kurulacağı söyleniyor.\[11\] Model, mimari, doğruluk ya da hata oranı açıklanmamış. Bu bir niyet beyanı; proje bunu "kamunun yöneldiği alan, ancak açık değerlendirme yok" gerekçesi olarak kullanabilir. Aynı bakanlığın "Aile Kart" duyurusundaki "yapay zekâ destekli merkezi ödeme altyapısı" ifadesi de pazarlama dilinde; teknik ayrıntı yok.\[12\]
- **Cumhurbaşkanlığı İletişim Başkanlığı, "Kamu Kurumları İçin Yapay Zekâ Sözlüğü":** "Bir bakanlık asistanı, yanıt üretmeden önce güncel genelgeleri ve resmî SSS havuzunu tarayarak daha doğru açıklama sunabilir" örneğini veriyor. Küçük dil modeli ve bulut kavramlarını da kamu bağlamında tanımlıyor.\[13\] Bu, RAG yaklaşımının kamuda tanınan bir kavram olduğunu göstermek için atıf yapılabilecek resmî bir kaynak.
- **ALO 144 / ALO 183 / SGK / e-Devlet:** Resmî bir LLM chatbotu doğrulanamadı. Bulunan "e-Devlet yapay zekâ asistanı" içerikleri özel firmaların blog ve pazarlama yazıları; kaynak olarak kullanılmamalı.
- **Kıyas için bir kamu örneği (sosyal hak dışı):** MEB Asistan / EBA Asistan, MEB web içeriğinden yanıt veriyor.\[14\] Yayımlanmış bir doğruluk değerlendirmesi görülmedi.

**Akademik çalışmalar (DergiPark ve diğerleri)**
- **"Dijital Öğrenci Hizmetleri: Yapay Zekâ ve RAG Modeli Destekli Akıllı Sohbet Robotu Sistemleri"** (AYBÜ, BAP Proje No 2764; 2026, Cilt 15 Sayı 1). Üniversite öğrenci hizmetleri için RAG chatbotu; değerlendirmesi kullanılabilirlik ve memnuniyet üzerine.\[15\] Eski kapsamın en yakın emsaliydi; yeni kapsamda yalnızca "Türkiye'de RAG kamu/kurum hizmetine uygulanıyor, ama doğruluk-dayanak-enerji ölçümü yapılmıyor" örneği olarak anılmalı.
- **"Engelli Bireylere Yönelik Yapay Zekâ Destekli Uygulamalar"** (DergiPark, 2025) ve **"Sohbet Robotlarının Akademik Yetersizliği Olan Bireylerin İletişim Deneyimlerine Etkisi"** (Mevzu, 2025, 21 katılımcı). Engelli bireylere yönelik yapay zekâ uygulamaları erişilebilirlik ve iletişim odaklı (betimleme, konuşma-metin, işaret dili); hak/mevzuat bilgisi sunan bir sistem içermiyor.\[16\]\[17\]
- **"Sosyal Hizmet Pratiğinde Yapay Zekâ: Saha Deneyimleri ve Uygulama Örnekleri"** (kitap bölümü, ResearchGate). Sohbet robotlarının engelli, yaşlı ve kırsal kesimdeki bireyler için önemini tartışıyor; teknik sistem yok.\[18\] Bölümün 1.1 kısmında "alan yazını ihtiyacı tanımlıyor ama çözüm üretmiyor" diye anılabilir.
- **TÜBİTAK 2209-A/B ve 2204-A:** Sosyal hak chatbotu projesi bulunamadı. Proje listeleri kamuya kapsamlı biçimde açık olmadığından bu "yokluk" kesin kabul edilmemeli.

**TEKNOFEST**
- **Yapay Zekâ Dil Ajanları Yarışması (2026):** Senaryolar kamu evrak/yazışma süreçleri, katılım bankacılığı metinleri ve video analizi; sosyal hak senaryosu yok.\[19\]\[20\]
- **Türkçe Doğal Dil İşleme Yarışması:** Önceki yıllarda "Üretken Yapay Zekâ Destekli Otonom Çağrı Merkezi" senaryosu vardı (ör. İKÇÜ takımının telekom müşteri hizmetleri ajanı).\[21\]\[22\] Bu, "ajan + Türkçe + hizmet" çizgisinin TEKNOFEST'te olgunlaştığını, ama sosyal hak ve enerji boyutunun bulunmadığını gösteriyor.
- **Engelli odaklı ödüllü projeler:** "From Your Eyes" (görme engellilere betimleme) gibi projeler hak bilgisi sunmuyor.\[23\]

**GitHub (yöntemsel emsal)**
- **berkaytaygurt/mevzuat-rag:** mevzuat.gov.tr üzerinde madde bazlı RAG; HyDE, parent-child parçalama ve Danıştay kararları kullanıyor. Depoya göre HyDE ile MRR 0,919, ancak günlük dille sorulan sorularda MRR ≈0,26–0,45 (34 soruluk set).\[24\] Bu fark çok önemli: kırılgan kullanıcılar mevzuat diliyle değil günlük dille soru sorar. Bu, yönlendirici ve geri soru bileşenlerinin gerekçesi olarak kullanılabilir.
- **yusuf-emir-tolan/hukuk-agent-rag:** TCK/TMK/TBK üzerinde ajan tabanlı RAG; dayanak kontrolü yapıyor ve kapsam dışı soruları reddediyor.\[25\] Tek aşamalı doğrulamanın Türkçe emsali.
- **berkecftc/turkish_rag_chatbot:** BGE-M3 + BM25 (RRF), bge-reranker, Ollama üzerinde qwen2.5:7b ve halüsinasyon kontrolü.\[26\] Yerel 7B Türkçe RAG'in açık kaynak emsali; değerlendirme ve enerji ölçümü yok.
- **SYDV sosyal yardım puanlama yazılımı (Edirne):** Kural tabanlı; LLM değil.\[27\] Ancak hesap aracı için "kural motoru" mantığının yerelde de kullanıldığını gösteriyor.

**Önceki taramadan, yeni kapsamda yalnızca yöntemsel emsal olarak anılacaklar (bu turda yeniden doğrulanmadı):** arXiv 2609.28007 (Türkçe yerel 7–8B, McNemar/Wilson), arXiv 2608.26192 (Türkel vd.), KÜBİT AI, TR-Docuquery, TEKNOFEST mevzuat kategorisi. Bunlar istatistiksel tasarım ve Türkçe yerel model emsali olarak kalmalı; sosyal hak odağı taşımıyorlar.

## Uluslararası çalışmalar

### Sosyal hak ve kamu hizmeti asistanları
- **Vals AI – Public Benefits Bench v1.1 (2026; Center for Civic Futures ve Code for America ile):**
  - Uzmanlarca doğrulanmış rubriklerle 459 genelleştirilmiş SNAP senaryosu. Dört koşul var: yalın model, web araması, çok tur ve ikisi birden.\[28\]
  - En iyi model %76,9 doğruluğa ulaşıyor. Haziran 2026'daki dört koşullu analizde "ikisi birden" koşulunda en iyi sonuç %68,1 (Claude Opus 4.8); hiçbir model %70'i geçmiyor.\[28\]
  - Çok tur, tüm modellerde en büyük kazancı sağlıyor. Örneğin Claude Haiku 4.5 %15,2'den %41,0'a çıkıyor.\[28\]
  - Yaşam döngüsü evrelerine göre en zor alan fazla ödeme/dolandırıcılık (%41,5; n=6).\[28\]
  - Raporun önerisi: eyalet kurumlarının bilgisine dayanan, dar kapsamlı RAG chatbotları.\[28\]
  - Veri seti "Proprietary" olarak işaretli.\[28\] Bu, projenin açık veri seti katkısını öne çıkarıyor.
- **Nava/Cornell – "LLMs in social services: How does chatbot accuracy affect human accuracy?" (arXiv 2603.11213):**
  - 770 soruluk, uzmanlarca incelenmiş SNAP seti.\[29\]
  - Chatbot önerileri vaka çalışanı doğruluğunu ortalama 21 puan artırıyor; kontrol grubunun doğruluğu %49.\[30\]
  - Nava chatbotu çoktan seçmeli sorularda %85, açık uçlu sorularda %76 doğru.\[29\]
  - Ders: insan-döngüde kullanımda bile hatalı öneri doğrudan hak kaybına dönüşebilir.
- **Propel (Dave Guarino, Director of Emerging Technology) – "Building a SNAP LLM eval" serisi:**
  - Doğruluğun yanında "güvenli geri çekilme" yanıtlarını ("eligibility worker'ınızla iletişime geçin") olumlu bir davranış olarak tanımlıyor.\[31\]
  - ZenML LLMOps veri tabanındaki özete göre şubat 2025'te test edilen modeller SNAP gelir sınırlarını hâlâ FY2024 değerleriyle veriyordu; yani güncel olmayan parametre, sosyal hak sorularında başlı başına bir hata türü. (Aynı veri tabanındaki "%36 araç kullanımı hatası" rakamı Propel'e değil, ayrı bir sigorta underwriting copiloti kaydına ait; Propel'e atfedilmemeli.)
- **ODI – CitizenQuery-UK (arXiv 2602.04064, 2026):**
  - GOV.UK'den sentetik olarak üretilmiş 22.066 soru–cevap çifti üzerinde 11 LLM test edilmiş.\[6\]\[32\]
  - Modeller neredeyse her soruyu yanıtlamaya çalışıyor; çekimser kalma oranı düşük ve bu "tehlikeli bir özellik" olarak nitelenmiş.\[5\]\[6\]
  - Yanıtlar gereksiz uzun; kısaltılması istendiğinde doğruluk düşüyor.\[6\]
  - Örnek hata: ChatGPT-OSS-20B, Guardian's Allowance için çocuğun ölmüş olması gerektiğini söylüyor.\[32\]
  - Projenin "soruyu karşılama" ve "çekimser kalma" bileşenleri için en doğrudan uluslararası gerekçe.
- **Bundesdruckerei – MÖVE (arXiv 2606.13111, 2026):**
  - Alman kamu sektörü için 39 modeli performans ve yönetişim boyutlarında (halüsinasyon, enerji, şeffaflık) değerlendiriyor.\[33\]
  - Bulgu: "model boyutu kaliteyi kötü öngörüyor".\[33\]
  - Enerji tahmininde EcoLogits kullanılmış ve 31 koşuda CodeCarbon ile karşılaştırılmış: medyan oran 0,9×, aralık 0,3×–9,1×.\[33\]
  - Kamu bağlamında enerji ile kaliteyi birlikte raporlayan en yakın emsal. Ancak enerji tahmine dayalı; yerel ölçüm, doğrulayıcı ve sosyal hak odağı yok.
- **İngiltere hükümeti veri sağlayıcılığı çalışması (arXiv 2412.09632):** Child Benefit ile Universal Credit etkileşimi gibi yardım sorularında model hatalarını örnekliyor.\[34\]

### Hak hesaplaması ve rules-as-code
- **Beeck Center (Georgetown) – "AI-Powered Rules as Code: Experiments with Public Benefits Policy":**
  - SNAP ve Medicaid politikalarının LLM ile sade dile, sözde koda ve koda çevrilmesi üzerine dört deney.\[35\]\[36\]
  - Eyalete özgü belge verildiğinde Georgia SNAP yanıtlarının %73,68'i doğrulukta 4–5 puan almış.\[35\]
  - Sonuç: "Yüksek riskli yardım sistemlerinde doğruluk ve hakkaniyet verimliliğin önüne geçmeli."\[35\]
  - Rubrik (doğruluk, eksiksizlik, ilgililik), projenin iki aşamalı doğrulayıcısıyla doğrudan örtüşüyor.
- **PolicyEngine / OpenFisca:** Vergi-yardım kurallarını açık kaynak kod olarak tutan bir motor. Policy2Code'da LLM, hesaplamayı yapmıyor; motorun ürettiği hesaplamayı sade dille açıklıyor.\[37\]\[38\] Projenin "hesap aracı" yardımcı katkısının uluslararası karşılığı bu. Mesaj net: hesabı LLM değil deterministik araç yapmalı.
- **Policy2Code Demo Day:** RAG modelinin SNAP uygunluk ve hesap kurallarını genel olarak doğru yorumladığı, ancak LLM'lerin uzmanlığın yerini almayacağı bildiriliyor. SSI/SSDI uygunluğunun karmaşıklığı da vurgulanıyor.\[37\]

### Doğrulayıcılar ve "soruyu karşılama"
- **FACTS Grounding (Google DeepMind, 2025):** İki aşamalı değerlendirme yapıyor: önce yanıtın isteği karşılayıp karşılamadığı (uygunluk), sonra belgeye dayanıp dayanmadığı. Projenin 1. ve 2. aşamasının ters sıralı akrabası; ancak bir değerlendirme ölçütü, çalışma zamanında devreye giren bir doğrulayıcı değil.
- **Self-RAG:** ISSUP (destek) ve ISUSE (yararlılık) yansıma belirteçleriyle dayanak ve yararlılık ayrımını model içine gömüyor. 7B/13B modeller kullanıyor; enerji ve Türkçe yok.
- **SCORE / "Small Language Models Need Strong Verifiers to Self-Correct Reasoning":** Küçük modellerin güçlü bir doğrulayıcı olmadan kendini düzeltemediğini gösteriyor. H6'nın kuramsal dayanağı.
- **CRAG, RAGAS, RAGChecker:** Getirim değerlendiricisi ile sadakat, bağlam kullanımı ve iddia düzeyinde tanı metrikleri sunuyor. Projede 1. aşamanın ölçümü RAGChecker tarzı iddia düzeyinde, 2. aşamanın ölçümü ise soru-alt-gereksinim kapsaması olarak tanımlanabilir.
- **Sufficient context (Joren vd.):** Bağlam yetersizken seçici yanıt verme ve çekimser kalma. Projenin "cevapsız/kapsam dışı" soru sınıfıyla birebir ilgili.
- **Hukuki yardım ve adalete erişim:**
  - Magesh vd. (Stanford, arXiv 2405.20362, ön kayıtlı çalışma): Lexis+ AI ile Thomson Reuters araçları (Westlaw AI-Assisted Research, Ask Practical Law AI) bile zamanın %17–33'ünde halüsinasyon üretiyor.
  - Dahl, Magesh, Suzgun ve Ho (2024, "Large Legal Fictions", Journal of Legal Analysis 16(1):64–93; arXiv 2401.01301): genel modellerde federal dava sorularında halüsinasyon oranı %58 (ChatGPT 4) ile %88 (Llama 2) arasında.
  - "Legal LLM Hallucination Should Be Evaluated as Failure of Legal Warrant" (arXiv 2609.17546): LSC 2022 verisine göre düşük gelirli Amerikalılar sivil hukuki sorunlarının %92'sinde yeterli yardım alamıyor. Çalışma, adalete erişim araçlarının yanlış merci ve kaçırılan süre gibi "öngörülebilir kullanıcı hatalarını" önleyip önlemediğiyle değerlendirilmesini öneriyor.\[39\]
  - Bu çerçeve, sosyal hak sorularındaki "süre/oran/merci" hatalarının ayrı kodlanması için iyi bir gerekçe.

### Enerji verimliliği
- **ML.ENERGY Leaderboard v3.0 (son güncelleme 23 Eylül 2026) ve ML.ENERGY Benchmark (arXiv 2505.06371):**
  - Yanıt başına enerjiyi baskın biçimde çıktı uzunluğu belirliyor; akıl yürütme görevleri sohbetten ortalama 25 kat fazla harcıyor.\[40\]
  - B200 üzerinde, enerji-optimal ayarda akıl yürütme görevi için Qwen 3 8B 0,1732 J/token ve 1.398 J/yanıt; Qwen 3 14B 0,1826 J/token ve 1.338 J/yanıt.\[41\]
  - Yorum: veri merkezi ölçeğinde toplu işlemede 8B ile 14B arasındaki token başı fark yalnızca yaklaşık %5. Yerel ve tekli (batch=1) çıkarımda bu fark muhtemelen daha büyük, çünkü kod çözme bellek bant genişliğiyle sınırlı. Bu bir çıkarım; projede ölçülerek doğrulanmalı.
- **"The Cost of Dynamic Reasoning" (arXiv 2506.04301):**
  - Tek turlu çıkarım: 0,32 Wh (8B) ve 2,55 Wh (70B).\[7\]
  - Reflexion: 41,53 Wh (8B) ve 348,41 Wh (70B).\[7\]
  - Ajan tabanlı yaklaşım sorgu başına enerjiyi 62–136 kat artırıyor.\[7\]
  - Çok ajanlı 7B hattının enerji avantajını yiyebilecek mekanizma tam olarak bu.
- **"Where Should Agents Live?" (arXiv 2609.18283):** Qwen2.5-7B ve Llama-3.1-8B ile, NVML ölçümüyle ajan sayısı ve akıl yürütme turuna göre enerji ölçeklenmesini modelliyor.\[42\] Yönlendirici/doğrulayıcı adımlarının enerji maliyetini öngörmek için kullanılabilir.
- **"The Price of Prompting" (arXiv 2407.16893):** Yanıt uzunluğu enerjiyi doğrusal regresyonla R² > 0,95 düzeyinde öngörüyor. GPU ölçümünde CodeCarbon ile EnergyMeter yakın sonuç veriyor.\[43\]
- **Bouza vd. (arXiv 2306.08323 / IOP 2023):** CodeCarbon wattmetreye en yakın yazılım aracı,\[8\] ancak toplamı düşük tahmin edebiliyor (252 Wh'ye karşı 391 Wh; 161 Wh'ye karşı 206 Wh).\[44\]\[45\]
- **Scientific Reports (2026), "Comparing energy consumption and accuracy in text classification inference":** CodeCarbon'un sınırlılıklarını sıralıyor: 15 saniyelik örnekleme, çekirdek düzeyinde CPU ayrıştırması yapamaması, RAM'i GB başına 0,375 W ile yaklaşık hesaplaması.\[46\] Kısa sorgularda örnekleme aralığı kritik.
- **"Energy Use of AI Inference, Efficiency Pathways, and Test-Time Scaling" (arXiv 2509.20241):** Üretim ortamında sorgu başına tipik değerler 0,05–0,4 Wh; üretim dışı ölçümler (AI Energy Score vb.) çok daha yüksek.\[47\] Projenin Wh değerlerini bu aralıkla karşılaştırarak yorumlaması gerekiyor.
- **Önceki taramadan:** Luccioni vd. "Power Hungry Processing", sustainable AI trilemma (arXiv 2501.08262), From Prompts to Power (arXiv 2511.05597) ve DVFS çalışması geçerliliğini koruyor.

### Türkiye şebeke emisyon faktörü (resmî kaynak)
- **ETKB-EVÇED, "2023 Türkiye Elektrik Üretimi ve Elektrik Tüketim Noktası Emisyon Faktörleri Bilgi Formu"** (Doküman No ETKB-EVÇED-FRM-042 Rev.01; hesaplama yayım tarihi 26.12.2025; IEA metodolojisi):\[48\]
  - Türkiye geneli üretim: 0,430 tCO₂/MWh; 0,434 tCO₂-eşd./MWh\[48\]
  - İletim hattına bağlı tüketim noktası: 0,433 / 0,436\[48\]
  - Dağıtım hattına bağlı tüketim noktası: 0,465 / 0,469\[48\]
- **Öneri:** Kurum içi sunucu dağıtım şebekesinden beslendiği için gCO₂e hesabında **0,469 kg CO₂-eşd./kWh** kullanılmalı; duyarlılık analizi için 0,434 de raporlanmalı. Örnek: soru başına 1 Wh ≈ 0,47 g CO₂e. 2024 yılı formu bulunamadı. Başvuru tarihinde enerji.gov.tr yeniden kontrol edilmeli.
- **Karıştırılmaması gereken form:** Ayrı bir belge olan "Ulusal Elektrik Şebekesi Emisyon Faktörü" (FRM-039; 2023 için OM 0,7134, CM güneş/rüzgâr 0,6242) yenilenebilir enerji ile azaltım hesapları içindir.\[49\]\[50\] Tüketim ayak izi için kullanılmamalı.

### Etik ve kırılgan kullanıcılar
- **MIT CCC – "LLM Targeted Underperformance Disproportionately Impacts Vulnerable Users" (AAAI 2026):** GPT-4, Claude 3 Opus ve Llama 3, eğitimi düşük, anadili İngilizce olmayan ve ABD dışından kullanıcılara daha düşük doğrulukla ve daha sık retle yanıt veriyor. Kesişimde etki en büyük: Claude'un ret oranı eğitimi düşük ve anadili İngilizce olmayan yabancı kullanıcılarda %10,9, kontrol koşulunda %3,61 (GPT-4'te %0,03, Llama 3'te %1,83); Claude'un eğitimi düşük kullanıcılara verdiği yanıtların %43,74'ünde küçümseyici dil var. Türkçe bağlama doğrudan aktarılamaz, ama "günlük dil/eksik ifadeli soru" alt kümesinin test setine konmasını gerektiriyor.
- **CDT engelli bireyler ve oy kullanma chatbot çalışması, HalluDetect, Lone Star Legal Aid (önceki tarama):** Erişilebilirlik ve hukuki yardım bağlamında hâlâ geçerli emsaller.
- **KVKK, "Üretken Yapay Zekâ ve Kişisel Verilerin Korunması Rehberi (15 Soruda)" (24.11.2025):**
  - Yapay zekânın tüm yaşam döngüsünün, istemler ve çıktılar dahil, KVKK'ya tabi olduğunu belirtiyor.\[9\]
  - Türkiye dışında barındırılan sistemlerin kullanımını yurt dışına aktarım sayıyor.\[9\]
  - Veri koruma etki değerlendirmesi ve istem enjeksiyonuna karşı teknik kontroller öneriyor.\[51\]
  - Bunlara ek olarak, KVKK'nın "Özel Nitelikli Kişisel Verilerin İşlenmesine İlişkin Rehber"i 26 Şubat 2025'te yayımlandı.\[52\] Sağlık ve engellilik bilgisi özel nitelikli veri olduğu için bu rehber ilgili.
- **Tasarım ilkeleri (literatürden derlenen):** Sade Türkçe; her cevapta madde numaralı kaynak; belirsizlikte geri soru; yetersiz bağlamda çekimser kalma ve ALO 144/SYDV/SGK'ya yönlendirme; kişisel veri istememe (soru yeniden yazımıyla kimliksizleştirme); "bu bir hukuki karar değildir" uyarısı.

## Karşılaştırma tablosu

İşaretler: ✓ var · ✗ yok · K kısmen · "görülmedi" bilgi bulunamadı/doğrulanamadı.

| Çalışma | Yerel küçük model | Yönlendirici | Geri soru | Doğrulayıcı | İki aşamalı / soruyu karşılama | Hesap aracı | Bileşen ablation | Model ölçeği karş. | Enerji / Pareto | Sosyal hak / kırılgan odak | Açık etiketli Türkçe sosyal hak seti | İstatistiksel test | Ayarsız genellenebilirlik |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Vals Public Benefits Bench (2026) | ✗ (bulut öncü modeller) | görülmedi | ✓ (çok tur koşulu) | ✗ | K (rubrik değerlendirme) | ✗ | K (4 koşul) | ✓ | ✗ (maliyet var, enerji yok) | ✓ | ✗ (İngilizce, kapalı) | görülmedi | ✗ |
| Nava/Cornell SNAP (arXiv 2603.11213) | görülmedi | görülmedi | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | ✗ |
| Propel SNAP eval | ✗ | görülmedi | K | ✗ | K (yararlılık + doğruluk) | görülmedi | görülmedi | ✓ | ✗ | ✓ | ✗ | görülmedi | ✗ |
| Beeck Center RaC deneyleri | ✗ | ✗ | ✗ | ✗ | K (doğruluk/eksiksizlik/ilgililik) | K (kod üretimi) | ✗ | K | ✗ | ✓ | ✗ | ✗ | K (eyaletler arası) |
| PolicyEngine / OpenFisca + LLM | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ |
| ODI CitizenQuery-UK (arXiv 2602.04064) | K (gpt-oss-20b dahil) | ✗ | ✗ | ✗ | K (aşırı/eksik bilgi ölçümü) | ✗ | ✗ | ✓ | ✗ | K (kamu hizmeti) | ✗ (İngilizce) | görülmedi | ✗ |
| MÖVE (arXiv 2606.13111) | K | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ (39 model) | ✓ (tahmin + CodeCarbon doğrulama) | K (kamu sektörü) | ✗ (Almanca) | ✓ (kesinlik analizi) | görülmedi |
| MIT AAAI 2026 kırılgan kullanıcı | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | K | ✗ | ✓ | ✗ | ✓ | ✗ |
| Magesh vd. (Stanford hukuk araçları) | ✗ | ✗ | ✗ | ✗ | K (doğruluk + dayanak) | ✗ | ✗ | ✗ | ✗ | K | ✗ | görülmedi | ✗ |
| FACTS Grounding | ✗ | ✗ | ✗ | ✓ (yargıç olarak) | ✓ (uygunluk + dayanak) | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | görülmedi | ✗ |
| Self-RAG | ✓ (7B/13B) | K (getirim kararı) | ✗ | ✓ | ✓ (ISSUP + ISUSE) | ✗ | K | ✓ | ✗ | ✗ | ✗ | görülmedi | K |
| SCORE / Strong Verifiers | ✓ | ✗ | ✗ | ✓ | ✗ | ✗ | K | ✓ | ✗ | ✗ | ✗ | görülmedi | görülmedi |
| CRAG / RAGChecker / RAGAS | K | K (CRAG) | ✗ | K | K (iddia düzeyi) | ✗ | K | K | ✗ | ✗ | ✗ | görülmedi | K |
| Sufficient context (Joren vd.) | K | ✗ | ✗ | K | K (çekimserlik) | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | görülmedi | ✓ |
| ML.ENERGY v3.0 | ✓ (8B–14B dahil) | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ (zaman–enerji Pareto) | ✗ | ✗ | ✗ | ✗ |
| Cost of Dynamic Reasoning | ✓ (8B) | ✗ | ✗ | K (Reflexion) | ✗ | ✗ | K | ✓ (8B/70B) | ✓ | ✗ | ✗ | görülmedi | ✗ |
| Where Should Agents Live? | ✓ (7–8B) | ✗ | ✗ | ✗ | ✗ | ✗ | K (ajan sayısı) | ✓ | ✓ | ✗ | ✗ | görülmedi | ✗ |
| Bouza vd. (CodeCarbon–wattmetre) | – | – | – | – | – | – | – | – | ✓ (ölçüm doğrulama) | ✗ | ✗ | ✗ | ✗ |
| berkaytaygurt/mevzuat-rag | K (Gemini isteğe bağlı) | ✗ | ✗ | ✗ | ✗ | ✗ | K (HyDE açık/kapalı) | ✗ | ✗ | ✗ | ✗ (34 soru, genel mevzuat) | ✗ | K (günlük dil alt kümesi) |
| hukuk-agent-rag | ✗ (Groq API) | K | ✗ | ✓ (tek aşama) | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| turkish_rag_chatbot | ✓ (qwen2.5:7b) | ✗ | ✗ | K (halüsinasyon kontrolü) | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| AYBÜ RAG öğrenci hizmetleri (DergiPark) | görülmedi | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | K (ön/son test) | ✗ |
| TRLawBench / LexVira / TurkishLegalBench | K | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ (genel hukuk) | görülmedi | ✗ |
| ASHB dijital asistan planı (2025) | görülmedi | görülmedi | görülmedi | görülmedi | görülmedi | görülmedi | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ |
| arXiv 2609.28007 (önceki tarama) | ✓ (7–8B) | görülmedi | görülmedi | görülmedi | görülmedi | ✗ | görülmedi | K | görülmedi | ✗ | ✗ | ✓ (McNemar/Wilson) | görülmedi |
| **Bu proje** | ✓ (7B, kurum içi) | ✓ | ✓ | ✓ | ✓ (dayanak + karşılama) | ✓ (fonksiyon çağırma) | ✓ (2³ × 2 = 16, GLMM) | ✓ (7B/14B) | ✓ (Wh/doğru, wattmetre, gCO₂e, Pareto) | ✓ | ✓ (≥300, açık) | ✓ (McNemar+Holm, Wilson, NI, kappa) | ✓ (ayarsız ikinci korpus) |

**Tablonun anlamı:** Satırların hiçbiri sağdaki son sütunların (enerji + sosyal hak + açık Türkçe set + ayarsız genellenebilirlik) üçünü birden taşımıyor. Boşluk bileşimde; tek tek bileşenlerde değil. Bu yüzden 1.1 ve 1.2 bölümlerinde "bileşenler bilinir, birlikte ve ölçülerek sınanmamıştır" söylemi kullanılmalı.

## Özgünlük değerlendirmesi

| # | Proje iddiası | Sınıf | Gerekçe | Nasıl daraltılmalı / güçlendirilmeli |
|---|---|---|---|---|
| 1 | Türkçe sosyal hak mevzuatı için yerel RAG asistanı | **Kısmen özgün** | Uluslararası SNAP ve GOV.UK emsalleri var; Türkçe sosyal hak alanında görülmedi | "Türkçe sosyal hak mevzuatında değerlendirmesi yayımlanmış ilk yerel RAG (bildiğimiz kadarıyla)"; YÖK Tez taraması eklenmeli |
| 2 | İki aşamalı doğrulayıcı (dayanak + soruyu karşılama), ana katkı | **Kısmen özgün** | FACTS Grounding (değerlendirme), Self-RAG (ISSUP/ISUSE) ve RAGChecker benzer ayrımı yapıyor | Özgünlüğü, (a) çalışma zamanında küçük yerel model ile, (b) "sadık ama eksik" hata türünü hak sorularında ayrı ölçme ve (c) her aşamanın marjinal güvenilirlik ve Wh katkısını ablation ile ayrıştırma üzerine kurun. "Yeni doğrulama paradigması" demeyin |
| 3 | H6: 7B + iki aşamalı doğrulayıcı, doğrulayıcısız 14B'ye göre en az eşit güvenilirliği daha düşük enerjiyle sağlar | **Kısmen özgün (ve riskli)** | SCORE kuramsal dayanak; ML.ENERGY ve Cost of Dynamic Reasoning, çok adımın enerjiyi katladığını gösteriyor | Hipotezi "Wh/doğru cevap" ve ön kayıtlı bir non-inferiority marjıyla kurun. Olumsuz sonucun da yayımlanabilir bir bulgu olduğunu yazın. Doğrulayıcı çıktısını kısa tutun |
| 4 | 2 × 2³ tasarım + GLMM etkileşimleri | **Kısmen özgün** (yöntemsel olarak güçlü) | Ajan/RAG literatüründe tam faktöriyel + karma model nadir; görülen çalışmalar tek bileşen ablation'ı yapıyor | Özgünlük iddiası değil, "titizlik" olarak sunun. Hakem gözünde en güçlü yöntem kanıtı |
| 5 | ≥300 soruluk açık, bağımsız etiketli Türkçe sosyal hak seti (belge / çıkarım-hesap / cevapsız) | **Gerçekten özgün** | Türkçe hukuk setleri genel hukuk/sınav odaklı; Vals seti kapalı | Lisans (CC BY), etiketleme kılavuzu, kappa ve sürüm tarihi (mevzuat yürürlük tarihi) ile yayımlayın. Projenin en kalıcı katkısı bu |
| 6 | Bileşen düzeyinde enerji ölçümü, Wh/doğru, wattmetre, Türkiye faktörüyle gCO₂e, Pareto | **Kısmen özgün** | MÖVE kamu bağlamında enerji raporluyor ama tahmine dayalı; ML.ENERGY genel görevlerde ölçüyor | "Türkçe kamu hizmeti RAG'inde bileşen düzeyinde ölçülmüş enerji" olarak daraltın. EVÇED 2023 faktörünü künyeyle verin |
| 7 | Hesap aracı (fonksiyon çağırma), yardımcı katkı | **Özgün değil** (Türkçe uygulaması kısmen) | PolicyEngine/OpenFisca ve rules-as-code yerleşik yaklaşımlar | "Türk sosyal hak kurallarının küçük bir kural kütüphanesi olarak kodlanması" diye sunun. Atıf takipli getirime göre daha ölçülebilir olduğu için tercih doğru |
| 8 | Geri soru (netleştirme) ajanı | **Özgün değil** | Vals: çok tur en büyük kazanç; Propel: güvenli geri çekilme | Gerekçe olarak Vals verisini kullanın; katkı iddiası yapmayın |
| 9 | KVKK gerekçeli yerel model | **Özgün değil** (ama güçlü gerekçe) | KVKK 2025 rehberi | 1.1'de resmî kaynak olarak kullanın |
| 10 | Kırılgan kullanıcı odağı | **Özgün değil** (motivasyon) | MIT AAAI 2026, CDT, ODI | Etki bölümünde kullanın; gerçek kullanıcı çalışması yapılmıyorsa "kullanıcı etkisi" iddiasından kaçının |

**İstatistik için somut uyarı (kaba hesap):** Eşleştirilmiş ikili sonuçlarda uyumsuzluk oranı ~%20 ve n=300 ise farkın standart hatası ≈ √(0,20/300) ≈ 2,6 puan. Tek yönlü %95 alt sınır, gözlenen farkın yaklaşık 4,2 puan altına düşer. 5 puanlık non-inferiority marjı ancak gerçek fark sıfıra çok yakınsa kanıtlanabilir. Bu nedenle ya n ≥ 400 olmalı ya da marj 7 puan olarak ön kayda alınmalı. H6'nın "güvenilirlik" tanımı da önceden sabitlenmeli: doğru + dayanaklı + soruyu karşılayan yanıt; cevapsız sorularda doğru çekimserlik.

## Yeni kapsamın TÜBİTAK açısından güçlü ve zayıf yanları

**Güçlü yanlar**
- **Özgünlük:** Türkçe sosyal hak alanında doğrudan emsal görülmedi. Eski üniversite kapsamında ise AYBÜ RAG çalışması, KÜBİT AI ve TR-Docuquery gibi yakın emsaller vardı.
- **Yaygın etki:** Hedef kitle engelli bireyler, 65 yaş üstü ve düşük gelirli haneler. Kamu (ASHB, SYDV, belediyeler) dijital asistan planladığı için bulguların karşılığı olan bir kullanıcı var. Açık veri seti kamu alımlarında bir değerlendirme ölçütü olarak kullanılabilir (ODI ve MÖVE'nin gerekçesiyle aynı).
- **Çevre boyutu:** Yeşil yapay zekâ ve ölçülmüş Wh/gCO₂e, 2209-A değerlendirmesinde "bilimsel nitelik" ve "sürdürülebilirlik" başlıklarında ek puan getirebilir. Türkiye'ye özgü resmî emisyon faktörü kullanmak yerel bir katkı.
- **KVKK gerekçesi:** 2025 rehberleriyle somut ve güncel.

**Zayıf yanlar ve riskler**
- **Pilot verinin kaybı:** 127 soruluk set farklı alanda. Yeni alanda fizibilite verisi yok; bu, ilk iş paketinde küçük bir sosyal hak pilotuyla (ör. 40–60 soru) kapatılmalı.
- **Etik kurul yükü:** Gerçek kırılgan kullanıcı katılımı (kullanılabilirlik testi, gerçek soru toplama) etik kurul onayı gerektirir ve takvimi uzatır. Öneri: Soruları ekip ve uzman (sosyal hizmet uzmanı/avukat) yazsın; gerçek kişisel veri toplanmasın. ALO 144 gibi kanallardaki kamuya açık SSS'ler soru şablonu olarak kullanılsın. Kullanıcı çalışması kapsam dışı ya da isteğe bağlı bırakılsın.
- **Mevzuatın oynaklığı:** Aylık tutarları katsayı ve genelgelerle her dönem değişir. Veri setinin yürürlük tarihli sürümü sabitlenmeli; tutar soruları "formül + o dönemin parametresi" ile etiketlenmeli.
- **Uzman etiketleme:** Hesap sorularında doğru cevap için alan uzmanı gerekir. Bağımsız iki etiketleyici + uzman hakem + Cohen kappa raporu şart.
- **Enerji hipotezinin başarısız olma olasılığı:** Yukarıda açıklandı. Proje metni olumsuz sonucu da katkı sayacak biçimde yazılmalı.

## Pilot verinin yeni kapsamda konumlandırılması

- **Fizibilite kanıtı olarak kullanın, alan kanıtı olarak değil.** "Önceki pilotta (127 soruluk Türkçe yükseköğretim mevzuatı seti) yerel boru hattı %91,4 belge doğruluğuna ulaştı; çıkarım soruları zayıf kaldı (2/8); 14B daha yavaş ve daha kötü sonuç verdi; 'soruyu karşılamama' hataları gözlendi." Bu cümle üç şeyi kanıtlar: ekip boru hattını kurabiliyor; hesap/çıkarım zaafı hesap aracını gerekçelendiriyor; "sadık ama eksik" hata türü gerçek ve 2. aşama doğrulayıcıyı gerekçelendiriyor.
- **14B bulgusunu genellemeyin.** Pilot küçük (çıkarımda n=8) ve farklı alanda. H6'nın motivasyonu olarak "ön gözlem" düzeyinde anılmalı.
- **Ayarsız ikinci korpus seçeneği:** Ekip isterse 127 soruluk seti, sosyal hak korpusunda ayarlanmış sistemin hiç dokunulmadan test edileceği "alan dışı genellenebilirlik" seti olarak kullanabilir. Bu, pilot emeğini boşa çıkarmaz. Yine de projenin ana anlatısı sosyal hak olmalı; tercih edilen ayarsız korpus aşağıdaki sosyal yardım ↔ engelli hakları ayrımı.

## Korpus önerisi

**Ana (ayar) korpusu: Engelli ve yaşlı hakları**
- **5378 sayılı Engelliler Hakkında Kanun:** Tanımlar, erişilebilirlik, istihdam, bakım hizmeti dayanakları. Kavramsal ve belge soruları için temel.
- **2022 sayılı 65 Yaşını Doldurmuş Muhtaç, Güçsüz ve Kimsesiz Türk Vatandaşlarına Aylık Bağlanması Hakkında Kanun:** Yaşlı aylığı, engelli aylığı (engel oranı dilimleri), 18 yaş altı engelli yakını aylığı; gelir ölçütü ve kesilme halleri. Aylık tutarı, Kanundaki göstergenin memur aylık katsayısıyla çarpımına dayandığı için hesap aracının ideal hedefi.
- **Evde bakım mevzuatı:** Bakıma Muhtaç Engellilerin Tespiti ve Bakım Hizmeti Esaslarına İlişkin Yönetmelik ve ilgili ASHB düzenlemeleri. Hane içi kişi başı gelir ölçütü hesap sorusu üretmeye uygun.
- **5510 sayılı Kanun'un ilgili hükümleri:** Malullük, engelli sigortalıların yaşlılık aylığına hak kazanma koşulları (engel oranına göre prim günü/sigortalılık süresi), genel sağlık sigortası primi ve gelir testi. Süre ve oran hesapları için.
- **Engelli istihdamı ve vergi:** 4857 sayılı İş Kanunu m.30 (engelli çalıştırma yükümlülüğü) ve 193 sayılı GVK m.31 (engellilik indirimi dereceleri). Oran ve derece soruları için.

**Ayarsız (genellenebilirlik) korpusu: Sosyal yardım**
- 3294 sayılı Sosyal Yardımlaşma ve Dayanışmayı Teşvik Kanunu, SYDV işleyişine ilişkin yönetmelik/yönergeler ve ASHB sosyal yardım programlarına ilişkin kamuya açık düzenlemeler.
- **Gerekçe:** Aynı hedef kitle, farklı terminoloji ve kural yapısı; ayarı engelli korpusunda yapılan sistemin dokunulmadan test edilmesi.
- **Uygunluk değerlendirmesi:** 3294 kısa ve çerçeve niteliğinde bir kanun; asıl kurallar ikincil düzenlemelerde. Ayarsız korpus için bu bir dezavantaj gibi görünse de "mevzuat dağınıklığı" gerçek kullanıcı koşulunu temsil ettiği için uygun. Ancak her belgenin resmî kaynağı (mevzuat.gov.tr, Resmî Gazete, ASHB) ve erişim tarihi kaydedilmeli; yalnızca resmî metinler alınmalı.

**Soru türleri ve hedef dağılım (≥300; tercihen ≥400)**
- **Belge sorusu (~%45):** "Evde bakım ücreti için engel raporunda hangi ibare aranır?"
- **Çıkarım/hesap (~%30):**
  - "Hanede 4 kişi var, hanenin aylık net geliri X TL; kişi başı gelir ölçütüne göre evde bakım ücretine başvurabilir mi?" (eşik formülü araçla hesaplanır)
  - "Engel oranım %75; 2022 sayılı Kanun'a göre aylığım hangi göstergeye göre hesaplanır, bu dönemki katsayıyla tutar nedir?"
  - "Engel oranı %50 olan bir sigortalı 5510'a göre kaç prim günü ve kaç yıl sigortalılıkla emekli olabilir?"
  - "50 işçili özel sektör işyeri kaç engelli çalıştırmak zorundadır?"
  - "Engellilik indirimi 2. derece için hangi engel oranı aralığı geçerli?"
- **Cevapsız/kapsam dışı (~%15):** Korpusta olmayan bir hak, başka bir ülkenin mevzuatı, kişisel tıbbi değerlendirme talebi. Beklenen davranış: çekimser kalma ve doğru kuruma yönlendirme.
- **Belirsiz/eksik bilgili (~%10):** "Annem için bakım parası alabilir miyim?" Beklenen davranış: geri soru (engel oranı, hane geliri, birlikte yaşama).
- **Dil çeşitliliği:** Her türde mevzuat dili ve günlük dil (yazım hatalı, eksik ifadeli) varyantları. mevzuat-rag deposundaki MRR düşüşü (0,92'den 0,26–0,45'e) bu alt kümenin önemini gösteriyor.\[24\]

## Önerilen atıf listesi (1.1 "Konunun önemi ve bilimsel nitelik")

**Sorunun önemi ve kırılgan kullanıcılar**
1. Vals AI, Center for Civic Futures, Code for America (2026). *Public Benefits Bench v1.1: SNAP benefits navigation support.* https://www.vals.ai/benchmarks/public-benefits-bench
2. (Nava/Cornell) "LLMs in social services: How does chatbot accuracy affect human accuracy?" arXiv:2603.11213. https://arxiv.org/abs/2603.11213
3. Open Data Institute (2026). "The CitizenQuery Benchmark: A Novel Dataset and Evaluation Pipeline for Measuring LLM Performance in Citizen Query Tasks." arXiv:2602.04064. https://arxiv.org/abs/2602.04064 \[53\]
4. Poole-Dayan, E., Roy, D., Kabbara, J. "LLM Targeted Underperformance Disproportionately Impacts Vulnerable Users." AAAI 2026. arXiv:2406.17737. https://arxiv.org/abs/2406.17737 \[54\]
5. Beeck Center for Social Impact + Innovation, Georgetown Univ. "AI-Powered Rules as Code: Experiments with Public Benefits Policy." https://beeckcenter.georgetown.edu/report/ai-powered-rules-as-code-experiments-with-public-benefits-policy/
6. Dalerci, C., Michael, T., Schaefer, R., Weinland, D. (2026). "MÖVE: A Holistic LLM Benchmark for the German Public Sector." arXiv:2606.13111. https://arxiv.org/abs/2606.13111 \[33\]
7. Magesh, V. vd. (2024). "Hallucination-Free? Assessing the Reliability of Leading AI Legal Research Tools." arXiv:2405.20362. https://arxiv.org/abs/2405.20362
8. "Legal Reasoning Is Not Lawyering: Rethinking Legal Benchmarks for Pro Se Access to Justice." arXiv:2606.23716. https://arxiv.org/abs/2606.23716 \[55\]

**Doğrulama ve dayanak**
9. Asai, A. vd. (2023). "Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection." arXiv:2310.11511. https://arxiv.org/abs/2310.11511
10. Jacovi, A. vd. (2025). "The FACTS Grounding Leaderboard." arXiv:2501.03200. https://arxiv.org/abs/2501.03200
11. Zhang, Y. vd. (2024). "Small Language Models Need Strong Verifiers to Self-Correct Reasoning." arXiv:2404.17140. https://arxiv.org/abs/2404.17140
12. Yan, S.-Q. vd. (2024). "Corrective Retrieval Augmented Generation." arXiv:2401.15884. https://arxiv.org/abs/2401.15884
13. Ru, D. vd. (2024). "RAGChecker: A Fine-grained Framework for Diagnosing Retrieval-Augmented Generation." arXiv:2408.08067. https://arxiv.org/abs/2408.08067
14. Es, S. vd. (2023). "RAGAS: Automated Evaluation of Retrieval Augmented Generation." arXiv:2309.15217. https://arxiv.org/abs/2309.15217
15. Joren, H. vd. (2025). "Sufficient Context: A New Lens on Retrieval Augmented Generation Systems." arXiv:2411.06037. https://arxiv.org/abs/2411.06037

**Enerji ve yeşil yapay zekâ**
16. Chung, J.-W. vd. (2025). "The ML.ENERGY Benchmark: Toward Automated Inference Energy Measurement and Optimization." arXiv:2505.06371. https://arxiv.org/abs/2505.06371 ; Leaderboard v3.0: https://ml.energy/leaderboard/
17. "The Cost of Dynamic Reasoning: Demystifying AI Agents and Test-Time Scaling from an AI Infrastructure Perspective." arXiv:2506.04301. https://arxiv.org/abs/2506.04301 \[7\]
18. "Where Should Agents Live? Energy-Memory Characterization of Agentic AI for the Edge-Cloud Continuum." arXiv:2609.18283. https://arxiv.org/abs/2609.18283 \[42\]
19. Luccioni, A. S., Jernite, Y., Strubell, E. (2024). "Power Hungry Processing: Watts Driving the Cost of AI Deployment?" FAccT 2024. arXiv:2311.16863. https://arxiv.org/abs/2311.16863
20. Bouza, L., Bugeau, A., Lannelongue, L. (2023). "How to estimate carbon footprint when training deep learning models? A guide and review." Environmental Research Communications. arXiv:2306.08323. https://arxiv.org/abs/2306.08323
21. "The Price of Prompting: Profiling Energy Use in Large Language Models Inference." arXiv:2407.16893. https://arxiv.org/abs/2407.16893
22. "Comparing energy consumption and accuracy in text classification inference." Scientific Reports (2026). https://www.nature.com/articles/s41598-026-45023-0

**Türkiye'ye özgü resmî kaynaklar**
23. T.C. Enerji ve Tabii Kaynaklar Bakanlığı, EVÇED (2025). *2023 Türkiye Elektrik Üretimi ve Elektrik Tüketim Noktası Emisyon Faktörleri Bilgi Formu* (ETKB-EVÇED-FRM-042 Rev.01; hesaplama yayım tarihi 26.12.2025). https://enerji.gov.tr/Media/Dizin/EVCED/tr/%C3%87evreVe%C4%B0klim/%C4%B0klimDe%C4%9Fi%C5%9Fikli%C4%9Fi/EmisyonFaktorleri/2023_Turkiye_Elektrik_UretimiveElektrik_Tuketim_Noktasi_Emisyon_Faktorleri.pdf
24. Kişisel Verileri Koruma Kurumu (2025). *Üretken Yapay Zekâ ve Kişisel Verilerin Korunması Rehberi (15 Soruda)*, Yayın No 113, Kasım 2025. https://www.kvkk.gov.tr/SharedFolderServer/CMSFiles/MTY5MjNmNmIwZWY3YTE.pdf \[56\]
25. T.C. Cumhurbaşkanlığı İletişim Başkanlığı. *Kamu Kurumları İçin Yapay Zekâ Sözlüğü.* https://yayinlar.iletisim.gov.tr/uploads/kamu_kurumlari_yapay_zeka_sozlugu.pdf
26. T.C. Aile ve Sosyal Hizmetler Bakanlığı (2025). "Aile ve Sosyal Hizmetler Bakanlığında yapay zeka destekli yeni dönem." https://www.aile.gov.tr/haberler/aile-ve-sosyal-hizmetler-bakanliginda-yapay-zeka-destekli-yeni-donem

**Türkçe yöntemsel emsaller**
27. "Dijital Öğrenci Hizmetleri: Yapay Zekâ ve RAG Modeli Destekli Akıllı Sohbet Robotu Sistemleri" (AYBÜ BAP 2764), 2026. https://dergipark.org.tr/tr/download/article-file/5960362
28. Erkan, M. A., Yozgatlıgil, C. (2026). "TurkishLegalBench: A Comprehensive Multi-Task Benchmark Suite for Turkish Legal NLP." https://open.metu.edu.tr/handle/11511/118433

## Sınırlılıklar

- **Türkiye taraması eksik:** YÖK Tez Merkezi doğrudan sorgulanamadı; 2209-A/B proje listeleri kamuya kapsamlı biçimde açık değil. "Türkiye'de emsal yok" ifadesi "taradığımız kaynaklarda görülmedi" diye yazılmalı. Başvurudan önce tez.yok.gov.tr'de "sohbet robotu/büyük dil modeli" ile "engelli/sosyal yardım/SGK" anahtar kelimeleri birlikte aranmalı.
- **İkincil kaynaklar:** Propel'in SNAP değerlendirmesine ilişkin bazı ayrıntılar (ör. FY2024 gelir sınırları) ikincil bir özetten (ZenML) alındı; Propel'in kendi "Building a SNAP LLM eval" yazılarından doğrulanmalı. MIT çalışmasının bazı ayrıntıları basın bültenlerinden. Atıfta birincil kaynaklar kullanılmalı.
- **Önceki taramadaki bazı kalemler** (arXiv 2609.28007, 2608.26192, KÜBİT AI, TR-Docuquery, CDT, HalluDetect, Lone Star Legal Aid, 2501.08262, 2511.05597) bu turda yeniden doğrulanmadı. Künyeleri başvuru öncesi kontrol edilmeli.
- **Enerji karşılaştırmaları donanıma bağlı:** ML.ENERGY değerleri B200/H100 üzerinde toplu işleme için. Yerel tek GPU, batch=1 ve nicelemeli (4-bit) çıkarımda oranlar farklı olacaktır. Projede niceleme düzeyi sabitlenmeli ya da ek bir faktör olarak raporlanmalı.
- **Sentetik/kapalı setlerin temsil gücü:** CitizenQuery-UK sentetik, Vals seti kapalı. Bu çalışmaların oranları Türkiye'deki kullanıcı davranışını doğrudan temsil etmez; motivasyon olarak kullanılmalı, karşılaştırma tabanı olarak değil.
- **Mevzuat ayrıntıları:** Korpus önerisindeki madde/kural özetleri (ör. 4857 m.30, GVK m.31 dereceleri, evde bakım gelir ölçütü) yön göstermek içindir. Soru seti yazılmadan önce mevzuat.gov.tr'deki yürürlükteki metinden ve güncel ASHB/SGK düzenlemelerinden doğrulanmalı; tutarlar dönemsel parametrelerle etiketlenmeli.
- **Emisyon faktörü güncelliği:** En güncel resmî değer 2023 yılına ait (yayım 26.12.2025).\[48\] 2024 formu yayımlanırsa güncellenmeli; ortalama faktör marjinal emisyonu yansıtmaz, bu raporda belirtilmeli.

## Sources

1. [GitHub - saidsurucu/TRLawBench: A Benchmark for Evaluating Large Language Models in Turkish Law · GitHub](https://github.com/saidsurucu/TRLawBench)
2. [LexVira Türkiye Hukuk AI Benchmark Raporu](https://www.lexvira.com/tr/legal-ai-source-benchmark/turkey)
3. [TurkishLegalBench: A Comprehensive Multi-Task Benchmark Suite for Turkish Legal NLP](https://open.metu.edu.tr/handle/11511/118433)
4. [Büyük Dil Modelleri için TR-MMLU Benchmark’ı: Performans Değerlendirmesi, Zorluklar ve İyileştirme Fırsatları TR-MMLU Benchmark for Large Language Models: Performance Evaluation, Challenges, and Opportunities for Improvement](https://arxiv.org/html/2508.13044v1)
5. [CivicShield: A Cross-Domain Defense-in-Depth Framework for Securing Government-Facing AI Chatbots Against Multi-Turn Adversarial Attacks](https://arxiv.org/html/2603.29062)
6. [Chatbots can be too chatty for government queries](https://www.theregister.com/on-prem/2026/02/19/chatbots-can-be-too-chatty-for-government-queries/4403943)
7. [The Cost of Dynamic Reasoning: Demystifying AI Agents and Test-Time Scaling from an AI Infrastructure Perspective](https://arxiv.org/html/2506.04301v2)
8. [Towards Sustainable NLP: Insights from Benchmarking Inference Energy in Large Language Models](https://arxiv.org/pdf/2502.05610)
9. [Kişisel verilerin korunması hukukunda güncel gelişmeler - Data Protection - Turkey](https://www.mondaq.com/turkey/data-protection/1740012/ki%C5%9Fisel-verilerin-korunmas%C4%B1-hukukunda-g%C3%BCncel-geli%C5%9Fmeler)
10. [Üretken Yapay Zekâ ve Kişisel Verilerin Korunması Rehberi 24.11.2025 tarihinde Kişisel Verileri Koruma Kurumu’nun internet sitesinde yayımlanmıştır. - Srp-Legal](https://www.srp-legal.com/tr/uretken-yapay-zeka-ve-kisisel-verilerin-korunmasi-rehberi-24-11-2025-tarihinde-kisisel-verileri-koruma-kurumunun-internet-sitesinde-yayimlanmistir/)
11. [Aile ve Sosyal Hizmetler Bakanliginda yapay zeka destekli yeni donem](https://www.aile.gov.tr/haberler/aile-ve-sosyal-hizmetler-bakanliginda-yapay-zeka-destekli-yeni-donem)
12. [Sosyal Yardım Ödemelerinde Yeni Dönem: Aile Kart](https://www.aile.gov.tr/btgmd/haberler/sosyal-yardim-odemelerinde-yeni-donem-aile-kart/)
13. [T.C. CUMHURBAŞKANLIĞI İLETİŞİM BAŞKANLIĞI KAMU KURUMLARI İÇİN YAPAY ZEKÂ](https://yayinlar.iletisim.gov.tr/uploads/kamu_kurumlari_yapay_zeka_sozlugu.pdf)
14. [MEB'İN YAPAY ZEKÂLI ASİSTANLARI MİLYONLARCA SORUYU CEVAPLIYOR](https://tokat.meb.gov.tr/www/meb039in-yapay-zekali-asistanlari-milyonlarca-soruyu-cevapliyor/icerik/4289)
15. [Digital Student Services: Intelligent Chatbot Systems ...](https://dergipark.org.tr/tr/download/article-file/5960362)
16. [Engelli Bireylere Yönelik Yapay Zekâ Destekli Uygulamalar](https://dergipark.org.tr/tr/download/article-file/5223968)
17. [(PDF) Sohbet Robotlarının Akademik Yetersizliği Olan Bireylerin İletişim Deneyimlerine Etkisi](https://www.researchgate.net/publication/389297495_Sohbet_Robotlarinin_Akademik_Yetersizligi_Olan_Bireylerin_Iletisim_Deneyimlerine_Etkisi)
18. [(PDF) Sosyal Hizmet Pratiğinde Yapay Zekâ: Saha Deneyimleri ve Uygulama Örnekleri](https://www.researchgate.net/publication/402763526_Sosyal_Hizmet_Pratiginde_Yapay_Zeka_Saha_Deneyimleri_ve_Uygulama_Ornekleri)
19. [Yapay Zeka Dil Ajanları Yarışması](https://teknofest.org/tr/yarismalar/yapay-zeka-dil-ajanlari-yarismasi/)
20. [TEKNOFEST’te Türkçe yapay zekâ ajanları yarışacak - Mavi Marmara Gazetesi](https://www.mavimarmaragazetesi.com/haber/28174496/teknofestte-turkce-yapay-zeka-ajanlari-yarisacak)
21. [Bilgisayar Mühendisliği Bölümü](https://ceng.ikcu.edu.tr/Haber/18910/ikcu-ogrencilerinin-teknofest-turkce-dogal-dil-isleme-yarismasi-ndaki-basarisi)
22. [TEKNOFEST Türkçe Doğal Dil İşleme Yarışması başvuruları sürüyor - Son Dakika Haberleri](https://www.trthaber.com/haber/bilim-teknoloji/teknofest-turkce-dogal-dil-isleme-yarismasi-basvurulari-suruyor-909265.html)
23. [Yapay zekayla güçlenen uygulamalar engellilerin hayatını ...](https://www.aa.com.tr/tr/bilim-teknoloji/yapay-zekayla-guclenen-uygulamalar-engellilerin-hayatini-kolaylastiriyor/3071681)
24. [GitHub - berkaytaygurt/mevzuat-rag: Türk mevzuatı üzerinde madde bazlı RAG sistemi. HyDE ile MRR 0.919, parent-child, Danıştay kararları ve yerel vektör araması. · GitHub](https://github.com/berkaytaygurt/mevzuat-rag)
25. [GitHub - yusuf-emir-tolan/hukuk-agent-rag · GitHub](https://github.com/yusuf-emir-tolan/hukuk-agent-rag)
26. [GitHub - berkecftc/turkish\_rag\_chatbot · GitHub](https://github.com/berkecftc/turkish_rag_chatbot)
27. [GitHub - gokhanSucsuz/SOSYAL-YARDIM-DE-ERLEND-RME-VE-PUANLAMA-Y-NERGES-: SOSYAL YARDIM DEĞERLENDİRME VE PUANLAMA YÖNERGESİ · GitHub](https://github.com/gokhanSucsuz/SOSYAL-YARDIM-DE-ERLEND-RME-VE-PUANLAMA-Y-NERGES-)
28. [Public Benefits Bench v1.1](https://www.vals.ai/benchmarks/public-benefits-bench)
29. [LLMs in social services: How does chatbot accuracy affect human accuracy?](https://arxiv.org/html/2603.11213)
30. [(PDF) LLMs in social services: How does chatbot accuracy affect human accuracy?](https://www.researchgate.net/publication/401911912_LLMs_in_social_services_How_does_chatbot_accuracy_affect_human_accuracy)
31. [Building a SNAP LLM eval: part 1](https://www.propel.app/insights/building-a-snap-llm-eval-part-1/)
32. [Chatbots can be too chatty for government queries • The Register](https://www.theregister.com/2026/02/19/chatbots_too_chatty_government/)
33. [M\\"OVE: A Holistic LLM Benchmark for the German Public Sector](https://arxiv.org/pdf/2606.13111)
34. [Methods to assess the UK government’s current role as a data provider for AI](https://arxiv.org/html/2412.09632)
35. [AI-Powered Rules as Code: Experiments with Public Benefits Policy - Digital Government Hub](https://digitalgovernmenthub.org/publications/ai-powered-rules-as-code-experiments-with-public-benefits-policy/)
36. [AI-Powered Rules as Code: Experiments with Public Benefits Policy - Beeck Center](https://beeckcenter.georgetown.edu/report/ai-powered-rules-as-code-experiments-with-public-benefits-policy/)
37. [Policy2Code Demo Day Recap - Digital Government Hub](https://digitalgovernmenthub.org/publications/policy2code-demo-day-recap/)
38. [Project Snapshot: PolicyEngine - Digital Government Hub](https://digitalgovernmenthub.org/publications/policyengine/)
39. [Legal LLM Hallucination Should Be Evaluated as Failure of Legal Warrant](https://arxiv.org/pdf/2609.17546)
40. [Diagnosing Inference Energy Consumption with the ML.ENERGY Leaderboard v3.0 - ML.ENERGY Blog](https://ml.energy/blog/measurement/energy/diagnosing-inference-energy-consumption-with-the-mlenergy-leaderboard-v30/)
41. [The ML.ENERGY Leaderboard](https://ml.energy/leaderboard/)
42. [Where Should Agents Live? Energy-Memory Characterization of Agentic AI for the Edge-Cloud Continuum](https://arxiv.org/pdf/2609.18283)
43. [The Price of Prompting: Profiling Energy Use in Large Language Models Inference](https://arxiv.org/pdf/2407.16893)
44. [How to estimate carbon footprint when training deep learning models? A guide and review - IOPscience](https://iopscience.iop.org/article/10.1088/2515-7620/acf81b)
45. [HOW TO ESTIMATE CARBON FOOTPRINT WHEN TRAINING DEEP](https://arxiv.org/pdf/2306.08323)
46. [Comparing energy consumption and accuracy in text classification inference](https://www.nature.com/articles/s41598-026-45023-0)
47. [Energy Use of AI Inference, Efficiency Pathways, and Test-Time Scaling](https://arxiv.org/pdf/2509.20241)
48. <https://enerji.gov.tr/Media/Dizin/EVCED/tr/%C3%87evreVe%C4%B0klim/%C4%B0klimDe%C4%9Fi%C5%9Fikli%C4%9Fi/EmisyonFaktorleri/2023_Turkiye_Elektrik_UretimiveElektrik_Tuketim_Noktasi_Emisyon_Faktorleri.pdf>
49. [2023 yılı elektrik şebekesi emisyon faktörleri yayımlandı : Yeşil Ekonomi](https://yesilekonomi.com/2023-yili-elektrik-sebekesi-emisyon-faktorleri-yayimlandi/)
50. [1 TÜRKİYE ULUSAL ELEKTRİK ŞEBEKESİ EMİSYON FAKTÖRÜ BİLGİ FORMU Doküman No](https://enerji.gov.tr/Media/Dizin/EVCED/tr/%C3%87evreVe%C4%B0klim/%C4%B0klimDe%C4%9Fi%C5%9Fikli%C4%9Fi/TUESEmisyonFktr/Belgeler/TUESEF_Bilgi_Formu.pdf)
51. [Üretken Yapay Zekâ ve Kişisel Verilerin Korunması Rehberi (15 Soruda) Yayınlanmıştır - Duyurular](https://www.zumbul.av.tr/tr/duyurular/uretken-yapay-zeka-rehberi-kvkk-yayinlanmistir)
52. [Üretken Yapay Zekâ ve Kişisel Verilerin Korunmasına İlişkin Rehber Yayımlandı](https://www.erdem-erdem.av.tr/bilgi-bankasi/uretken-yapay-zeka-ve-kisisel-verilerin-korunmasina-iliskin-rehber-yayimlandi)
53. [The CitizenQuery Benchmark: A Novel Dataset and Evaluation Pipeline for Measuring LLM Performance in Citizen Query Tasks](https://arxiv.org/html/2602.04064v1)
54. [LLM Targeted Underperformance Disproportionately Impacts Vulnerable Users](https://arxiv.org/pdf/2406.17737)
55. [Legal Reasoning Is Not Lawyering: Rethinking Legal Benchmarks for Pro Se Access to Justice](https://arxiv.org/pdf/2606.23716)
56. [Yayın No : 113 Kasım 2025](https://www.kvkk.gov.tr/SharedFolderServer/CMSFiles/MTY5MjNmNmIwZWY3YTE.pdf)
