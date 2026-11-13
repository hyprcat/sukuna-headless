const TOKEN_PATTERN =
  /("(?:\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*"(?=\s*:)|"(?:\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*"|true|false|null|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|[{}[\]:,])/g;

function tokenClass(token: string, source: string, index: number): string {
  const tokenTail = source.slice(index + token.length).trimStart();
  if (/^"/.test(token) && tokenTail.startsWith(':')) return 'token-key';
  if (/^"/.test(token)) return 'token-string';
  if (/^-?\d/.test(token)) return 'token-number';
  if (token === 'true' || token === 'false' || token === 'null') return 'token-literal';
  return 'token-punctuation';
}

function paintHighlight(target: HTMLElement, source: string): void {
  target.textContent = '';
  if (!source) {
    target.append(document.createTextNode(' '));
    return;
  }

  let cursor = 0;
  for (const match of source.matchAll(TOKEN_PATTERN)) {
    const token = match[0];
    const index = match.index ?? 0;
    if (index > cursor) target.append(document.createTextNode(source.slice(cursor, index)));

    const span = document.createElement('span');
    span.className = tokenClass(token, source, index);
    span.textContent = token;
    target.append(span);
    cursor = index + token.length;
  }

  if (cursor < source.length) target.append(document.createTextNode(source.slice(cursor)));
}

class MidsphereCodeEditor extends HTMLElement {
  #cleanup?: () => void;

  connectedCallback(): void {
    const textarea = this.querySelector<HTMLTextAreaElement>('[data-code-textarea]');
    const target = this.querySelector<HTMLElement>('[data-code-highlight]');
    if (!textarea || !target) return;

    const sync = () => {
      paintHighlight(target, textarea.value);
      textarea.style.height = 'auto';
      textarea.style.height = `${textarea.scrollHeight}px`;
    };

    textarea.addEventListener('input', sync);
    this.#cleanup = () => textarea.removeEventListener('input', sync);
    this.setAttribute('data-code-editor-ready', '');
    sync();
  }

  disconnectedCallback(): void {
    this.#cleanup?.();
  }
}

if (!customElements.get('ms-code-editor')) {
  customElements.define('ms-code-editor', MidsphereCodeEditor);
}
