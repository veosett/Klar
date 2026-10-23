export function is_valid_email(s: string): boolean {
  if (s.includes(" ")) return false;
  const parts = s.split("@");
  if (parts.length !== 2) return false;
  const [local, domain] = parts;
  return local.length > 0 && domain.includes(".") && !domain.startsWith(".") && !domain.endsWith(".") &&
    !domain.includes("..");
}
