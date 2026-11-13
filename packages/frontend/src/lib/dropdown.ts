/**
 * Shared dropdown/menu behavior for trigger + popup menus.
 * Used by: Topbar agent selector, Topbar account menu.
 *
 * Convention: the root element carries a data attribute; inside it,
 * a trigger button and a menu container hold child items. The menu
 * starts with `hidden` and is toggled by this code.
 */

interface DropdownSelectors {
  trigger: string;
  menu: string;
  items: string;
}

export function initDropdown(root: Element, selectors: DropdownSelectors): void {
  const trigger = root.querySelector(selectors.trigger) as HTMLButtonElement | null;
  const menu = root.querySelector(selectors.menu) as HTMLElement | null;
  if (!trigger || !menu) return;

  function getItems(): HTMLElement[] {
    return Array.from(menu!.querySelectorAll(selectors.items));
  }

  function focusItem(index: number): void {
    const items = getItems();
    if (items.length === 0) return;
    const clamped = Math.max(0, Math.min(index, items.length - 1));
    items[clamped].focus();
  }

  function focusedIndex(): number {
    return getItems().indexOf(document.activeElement as HTMLElement);
  }

  function open(): void {
    menu!.classList.remove('hidden');
    trigger!.setAttribute('aria-expanded', 'true');
    const checked = menu!.querySelector('[aria-checked="true"]') as HTMLElement | null;
    if (checked) checked.focus();
    else focusItem(0);
  }

  function close(restoreFocus = true): void {
    menu!.classList.add('hidden');
    trigger!.setAttribute('aria-expanded', 'false');
    if (restoreFocus) trigger!.focus();
  }

  function isOpen(): boolean {
    return !menu!.classList.contains('hidden');
  }

  trigger.addEventListener('click', (e) => {
    e.stopPropagation();
    if (isOpen()) close();
    else open();
  });

  trigger.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
      if (!isOpen()) {
        e.preventDefault();
        open();
      }
    }
  });

  menu.addEventListener('keydown', (e) => {
    const items = getItems();
    const idx = focusedIndex();

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        focusItem(idx < items.length - 1 ? idx + 1 : 0);
        break;
      case 'ArrowUp':
        e.preventDefault();
        focusItem(idx > 0 ? idx - 1 : items.length - 1);
        break;
      case 'Home':
        e.preventDefault();
        focusItem(0);
        break;
      case 'End':
        e.preventDefault();
        focusItem(items.length - 1);
        break;
      case 'Escape':
        e.preventDefault();
        close();
        break;
      case 'Tab':
        close(false);
        break;
    }
  });

  document.addEventListener('click', (e) => {
    if (isOpen() && !root.contains(e.target as Node)) close(false);
  });
}
