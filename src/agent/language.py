"""Response language: detect the language of a question and localize fixed answers.

Supported languages (tr, en) get prompts that name the language explicitly, because models drift into
English when the documents, table data, or prompt templates are in English, and fixed answers (no documents
found, greetings, errors) in that language. Questions in other languages are answered in the question's
language on a best-effort basis, with fixed answers in English. See docs/language_support.md.
"""

import re
import unicodedata
from typing import Iterable, Optional

DEFAULT_LANGUAGE = "en"
# Detected, but not a supported language (e.g. Spanish, Chinese)
OTHER_LANGUAGE = "other"
LANGUAGE_NAMES = {"tr": "Turkish", "en": "English"}
SUPPORTED_LANGUAGES = tuple(LANGUAGE_NAMES)

_TURKISH_CHARS = frozenset("çğıöşü")
# Frequent Turkish function words; ASCII spellings cover keyboards without Turkish characters.
# Short words shared with other languages (de, da, en, o, ya, mi, ne, ama, her) are left out: they made
# Spanish, French, and Portuguese questions look Turkish.
_TURKISH_WORDS = frozenset(
    """
    ve veya ile bir bu şu neden nasıl nasil kaç kac hangi hangisi hangileri için icin gibi daha çok cok var yok
    olan olarak göre gore ancak değil degil ise tüm tum sonra önce once kadar peki merhaba selam selamlar nedir
    midir mıdır bana beni bunu şunu onu şirket sirket gerekir gerekiyor olmalı uygun lütfen lutfen evet hayır
    hayir ayrıca ayrica kim nerede zaman neler kurum talep
    talebi talebim talebimi talebime talebimin talepler taleplerim taleplerimin iptal ekle numaralı numarali
    """.split()
)
# Verb suffixes that practically never end English words (unlike -ler/-lar: "controller", "smaller")
_TURKISH_SUFFIXES = (
    "abilir",
    "ebilir",
    "abilirsin",
    "ebilirsin",
    "misin",
    "mısın",
    "musun",
    "müsün",
    "iyor",
    "ıyor",
    "uyor",
    "üyor",
    "siniz",
    "sınız",
    "acak",
    "ecek",
    "mak",
    "mek",
)
_TURKISH_PROGRESSIVE = ("iyor", "ıyor", "uyor", "üyor")
# The question particle is Turkish when it ends the sentence ("... serbest mi?"); elsewhere "mi" is also Spanish
_TURKISH_QUESTION_PARTICLES = frozenset({"mi", "mı", "mu", "mü"})
# Words shared with Romance languages (a, no, as, do, in, on) are left out
_ENGLISH_WORDS = frozenset(
    """
    the an is are was were be been of to for with and or not what which how when who why where does did can
    could should would will this that these those it its there have has i you we our your my please hello hi
    hey from by at if than then only all any yes
    """.split()
)
# Function words of other common Latin-script languages (Spanish, Portuguese, French, Italian, German)
_OTHER_WORDS = frozenset(
    """
    el la los las del que es un una por para con qué cómo cuántos cuántas cuál puedo tengo hay su sus se lo al
    os das dos não com um uma é em na eu posso tenho
    le les des du est une pour avec dans sur je ce cette qui quoi comment combien puis ai pas
    il gli della che di per sono non ho quanti come
    der die das den dem und ist nicht ich wie viele habe mit für auf ein eine kann sie es zu im
    """.split()
)
# Letters used by those languages but not by Turkish or English (â, î, û appear in Turkish, so they are excluded)
_OTHER_LATIN_CHARS = frozenset("áéíóúñàèìòùêôãõäëïßœ")


def detect_language(text: str) -> Optional[str]:
    """Return 'tr', 'en', OTHER_LANGUAGE, or None when the text gives no clear signal (e.g. only a code)."""
    letters = [c for c in text if c.isalpha()]
    non_latin = sum(1 for c in letters if not unicodedata.name(c, "").startswith("LATIN"))
    if letters and non_latin * 2 > len(letters):
        return OTHER_LANGUAGE  # e.g. Chinese, Hindi, Arabic, Russian

    # Only İ needs care: casefold() would turn it into "i" plus a combining dot
    tokens = re.findall(r"\w+", text.replace("İ", "i").casefold())
    scores = {
        "tr": sum(1 for t in tokens if t in _TURKISH_WORDS or _TURKISH_CHARS.intersection(t) or _has_turkish_suffix(t))
        + (1 if tokens and tokens[-1] in _TURKISH_QUESTION_PARTICLES else 0),
        "en": sum(1 for t in tokens if t in _ENGLISH_WORDS),
        OTHER_LANGUAGE: sum(1 for t in tokens if t in _OTHER_WORDS or _OTHER_LATIN_CHARS.intersection(t)),
    }
    best = max(scores.values())
    winners = [language for language, score in scores.items() if score == best]
    # "not" (a grade) and similar words are Turkish and English; Turkish letters decide such a tie
    if best and sorted(winners) == ["en", "tr"] and any(_TURKISH_CHARS.intersection(t) for t in tokens):
        return "tr"
    if best == 0 or len(winners) > 1:
        return None
    return winners[0]


def foreign_script(text: str, allowed: str = "") -> bool:
    """Whether the text has letters of a non-Latin script (Chinese, Cyrillic, Arabic) that `allowed` (the
    documents, the question) does not have: multilingual models now and then slip into Chinese mid-answer."""
    known = set(str(allowed))
    return any(
        c.isalpha() and c not in known and not unicodedata.name(c, "").startswith("LATIN") for c in str(text or "")
    )


def _has_turkish_suffix(token: str) -> bool:
    if any(token.endswith(suffix) and len(token) > len(suffix) + 1 for suffix in _TURKISH_SUFFIXES):
        return True
    # The present tense "-yor" is followed by further suffixes: etkiliyorsa, geliyorum, istiyoruz
    return len(token) > 5 and any(marker in token[2:] for marker in _TURKISH_PROGRESSIVE)


def response_language(question: str, chat_history: Iterable[dict] = ()) -> str:
    """Language to answer in: the question's, else the latest earlier question's, else DEFAULT_LANGUAGE.

    Returns a code from SUPPORTED_LANGUAGES or OTHER_LANGUAGE.
    """
    language = detect_language(question)
    if language:
        return language
    for turn in reversed(list(chat_history or [])):
        language = detect_language(turn.get("question", ""))
        if language:
            return language
    return DEFAULT_LANGUAGE


_CONFIRM_WORDS = frozenset(
    "evet onaylıyorum onayliyorum onayla onaylı onayli tamam oluştur olustur yes confirm confirmed ok okay sure".split()
)
_REJECT_WORDS = frozenset("hayır hayir iptal vazgeç vazgec vazgeçtim vazgectim istemiyorum no cancel nope".split())


def confirmation_reply(text: str) -> Optional[str]:
    """'confirm' or 'reject' for a short yes/no answer ("Evet, oluştur" / "hayır"), None for anything else."""
    tokens = re.findall(r"\w+", text.replace("İ", "i").casefold())
    if not tokens or len(tokens) > 4:
        return None
    if any(t in _REJECT_WORDS for t in tokens):
        return "reject"
    if any(t in _CONFIRM_WORDS for t in tokens):
        return "confirm"
    return None


def language_name(language: str) -> str:
    """Name to use in prompts ("Turkish"), or a description for unsupported languages."""
    return LANGUAGE_NAMES.get(language, "the language of the user's question")


def language_instruction(language: str) -> str:
    """Prompt sentence that pins the response language."""
    if language in LANGUAGE_NAMES:
        target = f"in {LANGUAGE_NAMES[language]}, the language of the user's question,"
    else:
        target = "in the same language as the user's question,"
    return (
        f"Write your entire response {target} "
        "even if the context, the data, or these instructions are in another language."
    )


_MESSAGES = {
    "no_context": {
        "en": "This information is not found in the organization's documents.",
        "tr": "Bu bilgi kurum dokümanlarında bulunmuyor.",
    },
    "fallback": {
        "en": "This information cannot be fully verified against the organization's documents.",
        "tr": "Bu bilgi kurum dokümanlarıyla tam olarak doğrulanamadı.",
    },
    "greeting": {
        "en": (
            "Hello! I am your AI assistant. My specialist agents answer questions from the organization's "
            "documents and regulations, check whether an action complies with the rules, and analyze connected "
            "databases. How can I help you today?"
        ),
        "tr": (
            "Merhaba! Ben yapay zekâ asistanınızım. Uzman ajanlarım kurum dokümanları ve mevzuattan soruları "
            "cevaplar, bir işlemin kurallara uygunluğunu değerlendirir ve bağlı veritabanlarını analiz eder. "
            "Size nasıl yardımcı olabilirim?"
        ),
    },
    "thanks": {
        "en": "You're welcome! Ask me anytime if you have another question.",
        "tr": "Rica ederim! Başka bir sorunuz olursa her zaman sorabilirsiniz.",
    },
    # Added to greetings and thanks for users who can file requests, so they learn that they can
    "request_hint": {
        "en": (
            "💡 If something is not working (a device, your account, a room), just ask me to open a request, e.g. "
            "“Open a request: the projector in room B204 does not work.” You can also ask about the status of "
            "your requests."
        ),
        "tr": (
            "💡 Bir sorun yaşarsanız (çalışmayan bir cihaz, hesap veya derslik sorunu) benden talep oluşturmamı "
            "isteyebilirsiniz, örneğin: “Talep oluştur: B204'teki projektör çalışmıyor.” Taleplerinizin durumunu "
            "da sorabilirsiniz."
        ),
    },
    "greeting_guest": {
        "en": (
            "Hello! I am the AI assistant of the organization. I answer questions from the documents shared with "
            "visitors. How can I help you?"
        ),
        "tr": (
            "Merhaba! Ben kurumun yapay zekâ asistanıyım. Ziyaretçilerle paylaşılan belgelerle ilgili sorularınızı "
            "cevaplarım. Size nasıl yardımcı olabilirim?"
        ),
    },
    "direct_fallback": {
        "en": (
            "How can I help? Ask about the organization's documents and regulations, whether an action complies "
            "with the rules, or ask me to open a service request."
        ),
        "tr": (
            "Size nasıl yardımcı olabilirim? Kurum dokümanları ve mevzuat hakkında soru sorabilir, bir işlemin "
            "kurallara uygunluğunu sorabilir veya talep kaydı açmamı isteyebilirsiniz."
        ),
    },
    "no_agent": {
        "en": "No suitable specialist agent is available for this request.",
        "tr": "Bu istek için uygun bir uzman ajan bulunmuyor.",
    },
    "db_not_connected": {
        "en": "Database connection is currently not active or not configured.",
        "tr": "Veritabanı bağlantısı şu anda etkin değil veya yapılandırılmamış.",
    },
    "db_generation_error": {
        "en": "An error occurred while generating the database query. Please try again or rephrase your question.",
        "tr": "Veritabanı sorgusu oluşturulurken bir hata oluştu. Lütfen tekrar deneyin veya sorunuzu farklı ifade edin.",
    },
    "db_rejected": {
        "en": "Database query could not be executed due to security or syntax constraints:",
        "tr": "Veritabanı sorgusu güvenlik veya sözdizimi kısıtları nedeniyle çalıştırılamadı:",
    },
    "db_rows_fallback": {
        "en": "Query executed successfully ({count} records found):",
        "tr": "Sorgu başarıyla çalıştı ({count} kayıt bulundu):",
    },
    "compliance_undetermined": {
        "en": (
            "### 📌 1. Audit Verdict\n**[UNDETERMINED]**\n\n"
            "### 📑 2. Supporting Documents\nNo rule, policy, or regulation matching this inquiry was found in "
            "the knowledge base.\n\n"
            "### 🔍 3. Recommendation\nPlease ask the responsible unit (for example legal counsel, the data "
            "protection officer, or the relevant department) for guidance."
        ),
        "tr": (
            "### 📌 1. Denetim Kararı\n**[UNDETERMINED]**\n\n"
            "### 📑 2. Dayanak Dokümanlar\nBilgi tabanında bu talebe uyan bir kural, politika veya mevzuat "
            "bulunamadı.\n\n"
            "### 🔍 3. Öneri\nLütfen yönlendirme için ilgili birime (örneğin hukuk müşavirliği, kişisel veri "
            "koruma sorumlusu veya ilgili daire başkanlığı) başvurun."
        ),
    },
    "compliance_unsupported": {
        "en": (
            "### 📌 1. Audit Verdict\n**[UNDETERMINED]**\n\n"
            "### 📑 2. Underlying Rules\nThe retrieved rules do not support a clear verdict for this scenario.\n\n"
            "### 🔍 3. Recommendation\nPlease ask the responsible unit (for example legal counsel or the data "
            "protection officer) before acting."
        ),
        "tr": (
            "### 📌 1. Denetim Kararı\n**[UNDETERMINED]**\n\n"
            "### 📑 2. Dayanak Dokümanlar\nBulunan kurallar bu senaryo için net bir karar vermeye yetmiyor.\n\n"
            "### 🔍 3. Öneri\nİşlemi yapmadan önce lütfen ilgili birime (örneğin hukuk müşavirliği veya kişisel "
            "veri koruma sorumlusu) danışın."
        ),
    },
    "compliance_error": {
        "en": "A system error occurred while generating the audit report. Please try again later.",
        "tr": "Denetim raporu oluşturulurken bir sistem hatası oluştu. Lütfen daha sonra tekrar deneyin.",
    },
    # Added when the documents do not answer the question, for users who can file requests
    "request_hint_not_found": {
        "en": (
            "💡 If you like, I can pass this question on to the responsible unit: just write "
            "“open a request about this”."
        ),
        "tr": (
            "💡 İsterseniz bu soruyu ilgili birime iletmek için talep oluşturabilirim: “bununla ilgili talep oluştur” "
            "yazmanız yeterli."
        ),
    },
    "step_timeout": {
        "en": "This part could not be completed in time. Please ask again in a moment.",
        "tr": "Bu kısım zamanında tamamlanamadı. Lütfen biraz sonra tekrar sorun.",
    },
    "request_created": {
        "en": "✅ Your request has been filed: **#{id}**, {title}\n\nCategory: {category} · Status: open",
        "tr": "✅ Talebiniz oluşturuldu: **#{id}**, {title}\n\nKategori: {category} · Durum: açık",
    },
    "request_confirm": {
        "en": (
            # A list, so Markdown shows each field on its own line
            "Shall I file this request?\n\n- **Title:** {title}\n- **Category:** {category}\n"
            "- **Details:** {description}\n\nReply **yes** to file it or **no** to discard it. "
            "To change it, describe the request again."
        ),
        "tr": (
            "Şu talebi oluşturmamı onaylıyor musunuz?\n\n- **Başlık:** {title}\n- **Kategori:** {category}\n"
            "- **Açıklama:** {description}\n\nOnaylamak için **evet**, vazgeçmek için **hayır** yazın. "
            "Değiştirmek için talebi yeniden yazabilirsiniz."
        ),
    },
    "request_cancel_confirm": {
        "en": "Shall I cancel request **#{id}**, {title}?\n\nReply **yes** to cancel it or **no** to keep it.",
        "tr": "**#{id}** numaralı talebi ({title}) iptal etmemi onaylıyor musunuz?\n\nOnaylamak için **evet**, "
        "vazgeçmek için **hayır** yazın.",
    },
    "request_cancelled": {
        "en": "Request **#{id}** was cancelled.",
        "tr": "**#{id}** numaralı talep iptal edildi.",
    },
    "request_note_added": {
        "en": "Your information was added to request **#{id}**; the staff working on it will see it.",
        "tr": "Bilginiz **#{id}** numaralı talebe eklendi; talebi inceleyen personel görecek.",
    },
    "request_note_unclear": {
        "en": "What should I add to the request? Please write the information, e.g. “Add to #12: room B204”.",
        "tr": "Talebe ne ekleyeyim? Lütfen bilgiyi yazın, örneğin: “#12 numaralı talebime ekle: B204 dersliği”.",
    },
    "request_which": {
        "en": "Which request do you mean? Please give its number, e.g. “#12”. Your open requests:",
        "tr": "Hangi talebi kastediyorsunuz? Lütfen numarasını yazın, örneğin “#12”. Açık talepleriniz:",
    },
    "request_not_found": {
        "en": "I could not find request #{id} among your requests.",
        "tr": "#{id} numaralı talebi talepleriniz arasında bulamadım.",
    },
    "request_closed": {
        "en": "Request #{id} is already closed, so it cannot be changed.",
        "tr": "#{id} numaralı talep zaten kapatılmış; değiştirilemez.",
    },
    "request_discarded": {
        "en": "OK, the request was not filed.",
        "tr": "Tamam, talep oluşturulmadı.",
    },
    "request_notified": {
        "en": "The responsible unit was notified by e-mail.",
        "tr": "İlgili birime e-posta ile bildirildi.",
    },
    "request_follow_up": {
        # "My requests" in the web UI menu
        "en": "You can follow its status under “My requests”.",
        "tr": "Durumunu “Taleplerim” bölümünden takip edebilirsiniz.",
    },
    "request_login_required": {
        "en": "You need to be logged in to file or list service requests.",
        "tr": "Talep oluşturmak veya listelemek için giriş yapmış olmanız gerekir.",
    },
    "request_unclear": {
        "en": (
            "I could not tell what the request is about. Please describe the problem or need in one or two "
            "sentences, e.g. “Open a request: the projector in room B204 does not work.”"
        ),
        "tr": (
            "Talebin konusunu anlayamadım. Lütfen sorunu veya ihtiyacı bir iki cümleyle yazın, örneğin: "
            "“Talep aç: B204 dersliğindeki projektör çalışmıyor.”"
        ),
    },
    "request_error": {
        "en": "The request could not be saved because of a system error. Please try again later.",
        "tr": "Talep bir sistem hatası nedeniyle kaydedilemedi. Lütfen daha sonra tekrar deneyin.",
    },
    "request_list_empty": {
        "en": "You have no service requests yet.",
        "tr": "Henüz bir talebiniz yok.",
    },
    "request_list_header": {
        "en": "Your most recent requests:",
        "tr": "Son talepleriniz:",
    },
}


def message(key: str, language: str, **values) -> str:
    """Fixed answer `key` in `language` (English when the language has no translation)."""
    variants = _MESSAGES[key]
    text = variants.get(language, variants[DEFAULT_LANGUAGE])
    return text.format(**values) if values else text


_CATEGORY_LABELS = {
    "it_support": {"en": "IT support", "tr": "Bilgi İşlem"},
    "facilities": {"en": "Facilities", "tr": "Yapı ve Teknik İşler"},
    "academic": {"en": "Academic", "tr": "Akademik"},
    "administrative": {"en": "Administrative", "tr": "İdari"},
    "other": {"en": "Other", "tr": "Diğer"},
}


def category_label(category: str, language: str) -> str:
    """Name of a built-in request category in `language`; custom categories are shown as configured."""
    labels = _CATEGORY_LABELS.get(category)
    if not labels:
        return category
    return labels.get(language, labels[DEFAULT_LANGUAGE])


def message_variants(key: str) -> tuple:
    """Every translation of a fixed answer, e.g. to recognize it in evaluations."""
    return tuple(_MESSAGES[key].values())
