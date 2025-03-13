from babel import Locale
from pathlib import Path
import gettext
import os
from config import I18N_DOMAIN, LOCALES_DIR

class I18nManager:
    def __init__(self, domain, locales_dir):
        self.domain = domain
        self.locales_dir = locales_dir
        self.translations = {}
        
        # Har bir til uchun tarjimalarni yuklab olish
        for lang in os.listdir(locales_dir):
            if os.path.isdir(os.path.join(locales_dir, lang)):
                translation = gettext.translation(
                    domain,
                    localedir=locales_dir,
                    languages=[lang]
                )
                self.translations[lang] = translation

    def get_text(self, message_key, lang='uz'):
        """Berilgan kalit so'z uchun tarjimani qaytaradi"""
        if lang in self.translations:
            return self.translations[lang].gettext(message_key)
        return message_key

# i18n menejerini yaratamiz
i18n = I18nManager(I18N_DOMAIN, LOCALES_DIR)
