export function formatNumber(value: number, language: string): string {
  return new Intl.NumberFormat(language).format(value);
}
