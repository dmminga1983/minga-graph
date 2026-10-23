export interface User { id: number; name: string }

export function formatUser(raw: any): User {
  return { id: Number(raw.id), name: titleCase(raw.name) };
}

function titleCase(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
