export function formatDate(value: string | null | undefined, lang: string): string {
  if (!value) return "–";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString(lang === "nl" ? "nl-NL" : "en-GB", { dateStyle: "medium", timeStyle: "short" });
}

export function formatBytes(n: number | null | undefined): string {
  if (n == null) return "–";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

/** A calendar date (YYYY-MM-DD) without a time, e.g. "10 Nov 2026". */
export function formatDay(value: string | null | undefined, lang: string): string {
  if (!value) return "–";
  const d = new Date(`${value.slice(0, 10)}T12:00:00`);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString(lang === "nl" ? "nl-NL" : "en-GB", { day: "numeric", month: "short", year: "numeric" });
}
