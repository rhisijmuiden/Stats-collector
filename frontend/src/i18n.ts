import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en.json";
import nl from "./locales/nl.json";

const stored = (() => {
  try {
    return localStorage.getItem("sc-lang");
  } catch {
    return null;
  }
})();
const browser = navigator.language?.toLowerCase().startsWith("nl") ? "nl" : "en";

i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, nl: { translation: nl } },
  lng: stored || browser,
  fallbackLng: "en",
  interpolation: { escapeValue: false },
});

export function setLanguage(lang: "en" | "nl") {
  i18n.changeLanguage(lang);
  document.documentElement.lang = lang;
  try {
    localStorage.setItem("sc-lang", lang);
  } catch {
    /* ignore */
  }
}

/** Translate an API error code (e.g. "invalid_credentials") with a readable fallback. */
export function errorText(detail: string): string {
  const [code, ...rest] = detail.split(": ");
  const key = `errors.${code}`;
  if (i18n.exists(key)) return i18n.t(key) + (rest.length ? ` (${rest.join(": ")})` : "");
  return detail;
}

export default i18n;
