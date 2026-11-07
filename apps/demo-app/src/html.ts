const ESCAPES: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

export function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (c) => ESCAPES[c] as string);
}

/** Tagged template that escapes every interpolated value unless it is already a SafeHtml. */
export class SafeHtml {
  readonly value: string;
  constructor(value: string) {
    this.value = value;
  }
  toString(): string {
    return this.value;
  }
}

export function html(strings: TemplateStringsArray, ...values: unknown[]): SafeHtml {
  let out = strings[0] ?? "";
  values.forEach((v, i) => {
    out += render(v) + (strings[i + 1] ?? "");
  });
  return new SafeHtml(out);
}

function render(v: unknown): string {
  if (v instanceof SafeHtml) {
    return v.value;
  }
  if (Array.isArray(v)) {
    return v.map(render).join("");
  }
  if (v === null || v === undefined || v === false) {
    return "";
  }
  return escapeHtml(String(v));
}

/** Marks a trusted constant string as HTML. Never pass user input. */
export function raw(value: string): SafeHtml {
  return new SafeHtml(value);
}
